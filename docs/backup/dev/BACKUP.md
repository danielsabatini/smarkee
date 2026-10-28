# Backup e Recuperação — Ambiente de Desenvolvimento (dev)

Estratégia, escopo, segurança e procedimentos operacionais para backup, verificação de integridade, restauração e reset seguro do **ambiente de desenvolvimento**.

A ferramenta operacional que executa essas rotinas é o utilitário `scripts/dev/backup` (`smarkee-dev-backup`).

---

## 1. Princípios e Escopo

Conforme `AGENTS.md` (§2.1, §4, §14):
1. **O que entra no backup:** exclusivamente o que **não pode ser reconstruído apenas pelo repositório Git**.
   - Configurações manuais e entidades da instância do provedor de identidade (Zitadel) persistem no PostgreSQL (`identity`).
   - Recursos e estado de negócio da plataforma residem no SSOT (`ssot`).
   - Chaves privadas/públicas das Service Accounts e tokens persistem no volume Docker `identity-bootstrap`.
   - Estado externo simulado de Billing Accounts (fase P0) persiste no volume `bsm-account-state`.
   - Variáveis de ambiente locais (`.env`), em especial `SMARKEE_IDENTITY_MASTERKEY` (que decifra as credenciais no banco do Zitadel) e os IDs da instância em `clients/cli/.env`.
2. **O que não entra no backup:**
   - O gateway Apache APISIX é puramente stateless: reconstrói rotas, plugins e upstreams a partir de `infrastructure/dev/gateway/bootstrap/adc.yaml` via ADC.
   - Estado transitório de mensageria (NATS JetStream) e e-mails do Mailpit: recriados dinamicamente nos bootstraps do Compose. Em caso de perda do stream `DESIRED`, o estado é recuperável a partir do SSOT via `scripts/dev/republish`.
   - Volumes de outros projetos (a ferramenta valida listas estritas e imutáveis).

---

## 2. Estrutura do Backup

Os backups são gravados localmente em `~/.smarkee/backups/<AAAAMMDDTHHMMSSZ>/`, **isolados do diretório do repositório e do ciclo de vida do Docker** (um `docker system prune --volumes` não os atinge).

```text
~/.smarkee/backups/<AAAAMMDDTHHMMSSZ>/
├── db/
│   ├── identity.dump     # Dump custom format (pg_dump -Fc) do banco do Zitadel
│   ├── ssot.dump         # Dump custom format (pg_dump -Fc) do SSOT da Smarkee
│   └── globals.sql       # Papéis, permissões globais e logins (pg_dumpall --globals-only)
├── volumes/
│   ├── identity-bootstrap.tar.gz  # Chaves das service accounts e PATs
│   └── bsm-account-state.tar.gz   # Estado de Billing Account
├── env/
│   └── ...               # Cópias privadas dos arquivos .env existentes
├── manifest.json         # Metadados: commit git, versão postgres, bancos, volumes, envs
└── SHA256SUMS            # Hash criptográfico de todos os arquivos do backup
```

### Segurança e Permissões em Disco
- Diretório raiz do backup criado estritamente com permissão `0700` (`drwx------`).
- Arquivos de dump, chaves e cópias de `.env` criados com permissão `0600` (`-rw-------`).
- Nenhuma credencial ou secret é logado ou exposto na saída do terminal.

---

## 3. Garantias da Verificação (`verify`)

Antes de qualquer operação destrutiva ou restauração, o motor executa uma verificação formal composta por duas provas:

1. **Prova Criptográfica de Integridade:**
   - Valida cada checksum presente no arquivo `SHA256SUMS`.
   - Recusa qualquer manifesto que referencie bancos, volumes ou arquivos fora da allowlist estrita (`ALLOWED_DATABASES`, `VOLUMES`, `ENV_FILES`).
2. **Prova Real de Restauração em Contêiner Descartável:**
   - Sobe um contêiner temporário e isolado do PostgreSQL (imagem `postgres:18.6-alpine`, sem portas expostas no host, com credenciais e rede efêmeras).
   - Restaura os papéis globais e cada banco de dados via `pg_restore`.
   - Normaliza e compara linha a linha o conteúdo lógico (esquema, tabelas e dados) do banco restaurado contra o arquivo de origem (descartando tokens voláteis como timestamps e flags `\restrict` do `pg_dump`).
   - Destrói o contêiner descartável ao final.

---

## 4. Guia de Procedimentos Operacionais

A ferramenta deve ser executada a partir de `scripts/dev/backup`:

```bash
cd scripts/dev/backup && uv sync
```

### 4.1 Criar e Confirmar um Backup Novo
Gera o dump completo de todos os bancos e volumes e executa a verificação descartável imediata:
```bash
uv run smarkee-dev-backup
```
*Saída esperada:* `backup CONFIRMADO: ~/.smarkee/backups/<TIMESTAMP>`

### 4.2 Listar Backups Existentes
```bash
uv run smarkee-dev-backup list
```

### 4.3 Verificar Integridade de um Backup
Verifica o backup mais recente ou um timestamp específico:
```bash
uv run smarkee-dev-backup verify [TIMESTAMP]
```

### 4.4 Restaurar o Ambiente de Desenvolvimento Ativo
Para restaurar o estado dos bancos e volumes no ambiente ativo:
```bash
# 1. Simular e inspecionar o plano de execução (modo seguro - dry-run)
uv run smarkee-dev-backup restore [TIMESTAMP]

# 2. Aplicar a restauração no ambiente dev ativo
uv run smarkee-dev-backup restore [TIMESTAMP] --apply
```

**Etapas executadas pelo `--apply`:**
1. Valida a integridade do backup no banco descartável.
2. Compara os `.env` locais: recusa se houver divergência em relação ao backup (evita corromper descriptografia da masterkey).
3. Para os serviços e componentes dependentes do PostgreSQL.
4. Aplica `globals.sql` e recria os bancos (`DROP DATABASE ... WITH (FORCE)` e `pg_restore --create`).
5. Extrai e substitui os arquivos nos volumes Docker.
6. Reinicia e aguarda a estabilização de todos os serviços.

### 4.5 Reset Seguro do Ambiente (`reset --apply`)
Quando for necessário destruir contêineres e volumes locais para recriar o ambiente limpo do zero, **nunca execute `docker compose down -v` diretamente**:
```bash
# 1. Simular e inspecionar o plano de reset (modo seguro)
uv run smarkee-dev-backup reset

# 2. Executar o reset com trava de segurança
uv run smarkee-dev-backup reset --apply
```

O comando:
1. Gera um backup novo do estado atual.
2. Prova a restauração completa desse backup num banco descartável.
3. **Apenas após a confirmação** do backup, derruba e remove os contêineres e volumes locais.
4. Para reconstruir o ambiente imediatamente a partir do backup garantido:
   ```bash
   uv run smarkee-dev-backup restore --apply
   ```

---

## 5. Recuperação de Mensageria (NATS JetStream)

Como o estado do JetStream não faz parte do backup físico do PostgreSQL, caso haja perda de dados do NATS ou reinício do volume `messaging-data`:
1. O SSOT (`database.smarkee.internal`, banco `ssot`) permanece como a **Fonte Única da Verdade** (`docs/data/SSOT.md`).
2. Utilize o utilitário `scripts/dev/republish` para ler o `desired` vigente de cada recurso e reinjetar no NATS com deduplicação determinística:
   ```bash
   cd scripts/dev/republish && uv sync
   # Enfileira na outbox do SSOT para publicação controlada pelos Publishers
   uv run smarkee-dev-republish --apply
   ```
