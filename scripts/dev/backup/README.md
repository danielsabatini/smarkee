# smarkee-dev-backup

Backup, verificação, restauração e reset seguro do **ambiente de desenvolvimento**. É uma **ferramenta de operação**, e não um componente da plataforma nem um teste.

Guarda o que não se reconstrói só com o repositório: configurações feitas direto no Zitadel ficam no banco (o gateway se reconstrói a partir de `infrastructure/dev/gateway/bootstrap/adc.yaml` e não entra no backup), as chaves das service accounts ficam num volume, e o `ZITADEL_MASTERKEY` dos `.env` é o que decifra o banco do Zitadel.

```bash
cd scripts/dev/backup && uv sync
uv run smarkee-dev-backup                  # grava um backup novo e o verifica
uv run smarkee-dev-backup list             # lista os backups
uv run smarkee-dev-backup verify [NOME]    # prova que o backup restaura (padrão: o mais recente)
uv run smarkee-dev-backup restore [NOME]           # mostra o plano e verifica; não altera nada
uv run smarkee-dev-backup restore [NOME] --apply   # restaura no ambiente de dev
uv run smarkee-dev-backup reset            # mostra o plano
uv run smarkee-dev-backup reset --apply    # backup, verificação e SÓ ENTÃO zera o ambiente
```

**Antes de zerar o ambiente, use `reset --apply`** em vez de `docker compose down -v` à mão: ele só remove contêineres e volumes depois de um backup confirmado.

## O que entra no backup

| Item | Origem |
|---|---|
| Bancos `identity` (Zitadel) e `smarkee` (SSOT) | `pg_dump -Fc` no contêiner `database.smarkee.internal` |
| Papéis do PostgreSQL | `pg_dumpall --globals-only` |
| Volume `identity-bootstrap` (chaves das service accounts e PAT do login) | `tar` somente leitura |
| `.env` de `infrastructure/dev/{messaging,database,gateway,identity}` e das features | cópia (os que existirem) |
| `manifest.json` e `SHA256SUMS` | commit do git, versão do PostgreSQL, lista e somas dos arquivos |

**Não entram:** o estado do NATS (JetStream, volume `messaging-data`) e o Mailpit (`mail-data`). Um `reset` os perde. Os volumes de outros projetos nunca são tocados (a lista de volumes é fixa).

O backup fica em `~/.smarkee/backups/<AAAAMMDDTHHMMSSZ>/`, **fora do repositório e do Docker**: um `docker system prune --volumes` não o apaga. A pasta e os arquivos são só do dono (0700/0600): há hashes de senha, chaves e a masterkey. Nada é impresso.

## O que `verify` prova

1. **Integridade:** as somas SHA-256 de todos os arquivos conferem, sem arquivo a mais nem a menos.
2. **Restauração:** sobe um PostgreSQL descartável (rede padrão, sem porta publicada, senha aleatória), restaura os papéis e cada banco, e compara o conteúdo lógico (esquema e dados) do banco restaurado com o do dump. A comparação ignora o que muda a cada dump (data e o token `\restrict`) e a posição física das linhas. O contêiner é removido ao final.

Isso prova que o backup restaura os **dados**. Não prova que os serviços sobem: para isso, suba o Zitadel contra o banco restaurado, como foi feito na primeira validação (2026-10-16, quando o gateway ainda era o Kong e entrava no backup: organizações, usuários, projetos, apps, serviços, rotas e plugins iguais ao ambiente ativo).

## Restauração

`restore --apply`, com a plataforma de pé (`infrastructure/dev`), faz:

1. verifica o backup (integridade e restauração) e recusa se algo falhar;
2. recusa se um `.env` existente **difere** do backup (resolva à mão; a masterkey do Zitadel precisa ser a do backup);
3. para os componentes das features e `identity` e `identity-login`;
4. recria os papéis e substitui os bancos (`DROP DATABASE ... WITH (FORCE)` e `pg_restore --create`);
5. substitui o conteúdo do volume `identity-bootstrap`;
6. copia os `.env` que faltam;
7. sobe de novo os serviços parados.

Depois de um `reset`, recrie o ambiente (plataforma e features, `docker compose up -d --build`) e rode `restore --apply`.

## Segurança

- Só atua no ambiente de dev local (contêineres, volumes e diretórios fixos); qualquer variável `BACKUP_*` é **recusada**.
- Sem `--apply`, `restore` e `reset` não alteram nada. `reset` não remove nada se o backup não for confirmado.
- O nome de banco que entra em comandos SQL é validado por um padrão fixo.
- Não há remoção automática de backups antigos: apague-os à mão quando quiser.

## Desenvolvimento

```bash
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest        # a lógica roda contra portas falsas; não toca no Docker
```

Os testes não cobrem os adaptadores do `docker`. Eles foram exercitados à mão: `backup`, `verify` e os métodos de restauração de banco e de volume (contra um PostgreSQL descartável, em duas rodadas), e os comandos do Compose só com `--dry-run`. **O `restore --apply` e o `reset --apply` completos contra o ambiente ativo ainda não foram executados.**
