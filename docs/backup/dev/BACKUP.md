# Backup e Recuperação — Ambiente de Desenvolvimento (dev)

Estratégia, escopo, segurança e procedimentos operacionais para **backup e restauração completos do ambiente Kubernetes de desenvolvimento** (`kind` `smarkee` + ArgoCD), inclusive para recriá-lo em **outra máquina**.

A ferramenta operacional é o utilitário `scripts/dev/k8s-backup`. Ele cobre o cluster `kind`; o utilitário `scripts/dev/backup` (`smarkee-dev-backup`) é do ambiente Docker Compose legado e **não serve** para o cluster (§8).

---

## 1. Princípios e escopo

Conforme `AGENTS.md` (§2.1, §4, §14):

1. **Entra no backup** o que não se reconstrói só com o repositório Git:

| Estado | Onde vive no cluster | Como é salvo |
|---|---|---|
| Configuração do Zitadel (orgs, projetos, roles, usuários, service accounts) | banco `identity` (CloudNativePG) | `pg_dump -Fc` |
| Recursos e estado de negócio (SSOT, outbox, idempotência) | banco `ssot` (CloudNativePG) | `pg_dump -Fc` |
| Papéis e logins do PostgreSQL | cluster CloudNativePG | `pg_dumpall --globals-only` |
| Estado pretendido e histórico (`DESIRED`, `UPDATED`, `AUDIT`) | JetStream (PVC `data-messaging-0`) | `nats stream backup` (com consumers) |
| Segredos, CA raiz/intermediária, chaves de criptografia | OpenBao (raft, PVC `data-vault-0`) | `bao operator raft snapshot save` |
| Chave de unseal e root token do OpenBao | `.workspace/vault-init.json` | cópia |
| Chaves das service accounts e `login-client.pat` | volume Docker `identity-bootstrap` | `tar` |
| `SMARKEE_IDENTITY_MASTERKEY` e demais variáveis locais | `.env` de `clients/cli`, `features/*/*` e `infrastructure/dev/*` | cópia |
| Estado auxiliar de bootstrap | `.workspace/{vault-oidc-app,service-account-platform-bootstrap,zitadel-state,controllers-keys,seed_ids}.json` | cópia |
| Imagens `smarkee-*` já construídas | registry local `smarkee-registry` (`/var/lib/registry`) | `tar` do volume |
| Commit do repositório e estado das 19 Applications | Git / ArgoCD | `manifest.json` |

2. **Não entra no backup** (reconstruído pelo GitOps ou sem valor):
   - Manifestos, operadores e CRDs: o `cluster-up` e o ArgoCD os recriam a partir do repositório.
   - Certificados TLS (`database-server-tls`, `messaging-server-tls`, `trust-manager-tls`): reemitidos pelo cert-manager a partir da CA do OpenBao restaurada.
   - Gateway (etcd), Mailpit, telemetria (`.jsonl`) e imagens de terceiros (baixadas de novo na restauração).
   - Dados de outros projetos que usam o mesmo Docker.

3. **A CA vem do OpenBao.** O OpenBao é restaurado **antes** do `vault-bootstrap`; se ele fosse recriado, a CA raiz seria outra e os certificados do backup deixariam de ser confiáveis.

---

## 2. Segurança do backup

O backup contém segredos em claro dentro do pacote: **trate-o como credencial**.

- Gravado em `~/.smarkee/k8s-backups/` (fora do repositório e do ciclo de vida do Docker: `docker system prune --volumes` não o atinge). Diretório `0700`, arquivos `0600`. Nunca versione.
- **Cifrado**: pacote `tar` + `zstd` + `openssl enc -aes-256-cbc -pbkdf2 -iter 600000`. A frase-senha é gerada na primeira execução em `~/.smarkee/backup-passphrase` (`0600`) e **precisa ser guardada em outro canal** (cofre de senhas): sem ela o backup não abre.
- Credenciais do NATS e o root token do OpenBao são passados por variável de ambiente ou `stdin`, nunca por argumento de processo, e não são impressos.
- Pastas temporárias ficam em `.workspace/` (ignorado pelo Git) e são removidas ao fim.

Variáveis opcionais: `SMARKEE_BACKUP_DIR`, `SMARKEE_BACKUP_PASSPHRASE_FILE`, `SMARKEE_NATS_URL`, `SMARKEE_KIND_CLUSTER_NAME`, `SMARKEE_KIND_REGISTRY_NAME`.

Conteúdo do pacote (após decifrar):

```text
db/            identity.dump  ssot.dump  globals.sql  <banco>.rowcounts.tsv
nats/          DESIRED/  UPDATED/  AUDIT/  counts.tsv
vault/         raft.snap
registry/      registry.tar.zst  catalog.json
volumes/       identity-bootstrap.tar
env/           cópias dos .env (mesmos caminhos relativos do repositório)
workspace/     vault-init.json e demais .json de bootstrap
manifest.json  commit Git, versões, estado das Applications
SHA256SUMS     checksum de cada arquivo acima
```

---

## 3. Pré-requisitos

Na máquina de origem e na de destino: `docker`, `kind`, `kubectl`, `jq`, `openssl`, `zstd`, `python3` e a CLI `nats` (0.4+). Na de destino ainda: acesso à internet (inclusive a `raw.githubusercontent.com`, de onde o `cluster-up` baixa os manifestos do CloudNativePG e do ArgoCD) para baixar as imagens dos operadores e do PostgreSQL/NATS/OpenBao, e as portas `8080 9180 5432 4222 8222 8025 8200 8443 5001` livres no host (o `kind` as publica, conforme `infrastructure/k8s/kind/cluster.yaml`).

Também precisam existir na máquina de destino:
- O repositório clonado, no **commit registrado no `manifest.json`** (a restauração avisa se divergir).
- A entrada `127.0.0.1 ipm-dev.smarkee.com.br api-dev.smarkee.com.br` em `/etc/hosts`.

---

## 4. Fazer o backup

O cluster precisa estar de pé, com o OpenBao **desselado** e as Applications `Healthy`.

```bash
# 1. Conferir o estado (todas as 19 devem estar Synced Healthy)
kubectl -n gitops-operator get applications.argoproj.io
kubectl -n vault exec vault-0 -- env BAO_ADDR=http://127.0.0.1:8200 bao status | grep Sealed

# 2. Se o OpenBao estiver selado (ex.: após reiniciar o Docker), desselar
./scripts/dev/vault-bootstrap
# e, se ExternalSecrets ficaram em SecretSyncedError, forçar nova sincronização:
kubectl annotate externalsecrets -A --all force-sync=$(date +%s) --overwrite

# 3. Criar o backup (já o verifica ao final)
./scripts/dev/k8s-backup create
```

Saída esperada: `backup CONFIRMADO: ~/.smarkee/k8s-backups/smarkee-k8s-<AAAAMMDDTHHMMSSZ>.tar.zst.enc`.

O backup é um **retrato lógico**, feito sem parar o cluster: bancos por `pg_dump` (consistente por banco), streams por snapshot do servidor e OpenBao por snapshot raft. Mensagens publicadas entre as etapas podem ficar fora de uma ou de outra; o `scripts/dev/republish` (§7) reconcilia o `desired` a partir do SSOT.

Outros comandos:

```bash
./scripts/dev/k8s-backup list                 # lista os backups
./scripts/dev/k8s-backup verify [ARQUIVO]     # checksums + estrutura, sem cluster (usa o mais recente por padrão)
```

> `verify` prova a **integridade e a estrutura** do pacote. A prova de que ele **restaura** é a restauração real descrita no §6.

---

## 5. Restaurar o ambiente (em outra máquina)

### 5.1 Copiar para a máquina de destino

```bash
# arquivos a levar (por canais separados: o backup e a frase-senha)
~/.smarkee/k8s-backups/smarkee-k8s-<TS>.tar.zst.enc
~/.smarkee/k8s-backups/smarkee-k8s-<TS>.tar.zst.enc.sha256     # opcional, confere a cópia
~/.smarkee/backup-passphrase                                    # ou informe SMARKEE_BACKUP_PASSPHRASE_FILE
```

Na destino, o diretório `~/.smarkee` deve ser `0700` e a frase-senha `0600`.

### 5.2 Preparar o repositório

```bash
git clone https://github.com/danielsabatini/smarkee.git && cd smarkee
git checkout <commit do manifest.json>        # `verify` mostra o commit
```

### 5.3 Conferir e executar

```bash
# 1. Integridade do arquivo copiado
./scripts/dev/k8s-backup verify <ARQUIVO>

# 2. Plano (dry-run, nada é alterado)
./scripts/dev/k8s-backup restore <ARQUIVO>

# 3. Restaurar (cluster novo; leva de 10 a 25 minutos)
./scripts/dev/k8s-backup restore <ARQUIVO> --apply
```

### 5.4 O que o `--apply` faz, em ordem

1. Decifra o pacote e confere o `SHA256SUMS`.
2. **Recusa** se o cluster já tiver o OpenBao (restauração é só para cluster novo; para refazer: `kind delete cluster --name smarkee`).
3. Restaura os `.env` e `.workspace/*.json`; **recusa** se algum já existir e for diferente (evita sobrescrever a masterkey).
4. `cluster-up` com `SMARKEE_CLUSTER_UP_STOP_BEFORE_VAULT=1`: cria `kind`, registry e instala os operadores, parando antes do OpenBao.
5. Restaura o registry local (as imagens `smarkee-*`) e o volume `identity-bootstrap`.
6. Restaura o OpenBao (snapshot raft), desbloqueia com a chave do backup e roda `vault-bootstrap` (idempotente).
7. Aplica o App-of-Apps do ArgoCD; aguarda `database` e `messaging` ficarem prontos.
8. **Pausa** o controlador do ArgoCD e as cargas (`identity`, `cam`, `bsm`, `sum`, `ipm`), restaura os bancos `identity` e `ssot` (`DROP DATABASE … WITH (FORCE)` + `pg_restore --create`), confere as **contagens de linhas por tabela** contra o backup, restaura os streams `DESIRED`, `UPDATED` e `AUDIT` conferindo o **nº de mensagens**, e retoma tudo.
9. Aguarda as Applications ficarem `Synced Healthy`.

### 5.5 Conferir o resultado

```bash
kubectl -n gitops-operator get applications.argoproj.io          # 19 Synced Healthy
kubectl get pods -A | grep -v "Running\|Completed"               # vazio
nats --server nats://127.0.0.1:4222 stream ls                    # DESIRED / UPDATED / AUDIT (credenciais do Secret messaging-secret)
```

Fluxo funcional: `sk auth login` e `sk cam account list` devem responder com os dados do ambiente de origem (OIDC do Zitadel e cadeia de certificados restaurados).

---

## 6. Estado da validação da restauração

- **Verificado:** a criação do backup e o `verify` (checksum do arquivo cifrado, descriptografia, `SHA256SUMS` interno, dumps `PGDMP`, backup dos 3 streams, snapshot raft, `vault-init.json` e registry). O plano (`restore` sem `--apply`) também foi executado.
- **Verificado parcialmente:** a restauração real num cluster `kind` novo (`SMARKEE_KIND_CLUSTER_NAME=smarkee-restore-test SMARKEE_KIND_REGISTRY_NAME=smarkee-registry-test`) executou as etapas 1 a 3 e parte da 4 (`kind`, registry, cert-manager e trust-manager), e parou ao instalar o CloudNativePG porque `raw.githubusercontent.com` estava inacessível na rede usada.
- **Não verificado:** as etapas 5 a 9 (registry e `identity-bootstrap`, restore raft do OpenBao, `pg_restore`, restore dos streams e `Synced Healthy` das Applications). O script cobre essas etapas, mas **ainda não foi provado que a restauração completa funciona**. Repita o teste (§5.3) numa rede que alcance `raw.githubusercontent.com` antes de depender do backup.

---

## 7. Pós-restauração

- Se um recurso estiver sem `desired` publicado, reenfileire pelo SSOT: `cd scripts/dev/republish && uv sync && uv run smarkee-dev-republish --apply` (`docs/loop/`, `docs/data/SSOT.md`).
- Para reconstruir uma imagem de feature em vez de usar a restaurada: `./scripts/dev/build-push <módulo>/<tipo>`.
- `./scripts/dev/cleanup` e `./scripts/dev/retention` funcionam normalmente depois da restauração.

---

## 8. Backup legado (Docker Compose)

`scripts/dev/backup` (`smarkee-dev-backup`) opera sobre o ambiente Compose (contêiner `database.smarkee.internal`, volumes `identity-bootstrap` e `bsm-account-state`). Não cobre NATS, OpenBao, registry nem o cluster `kind`, e só vale enquanto o Compose existir. Seu `README.md` descreve o uso.

---

## 9. Limitações e riscos conhecidos

- **Retrato lógico, não físico**: não há PITR nem WAL arquivado. O CloudNativePG de dev tem 1 instância e sem Barman.
- **Segredos no pacote**: a cifra protege em repouso, mas quem tiver o arquivo e a frase-senha controla o ambiente. Em `stg`/`prd` o OpenBao não pode ter chave de unseal e root token em arquivo local (pendência já registrada no `MEMORY.md`).
- **Mesmas portas**: o restore em máquina com outro projeto usando 5432/8080/etc. falha; libere-as antes.
- **Repositório no commit do backup**: o git-server do ArgoCD serve o repositório local; se o código divergir, as Applications sincronizam o que está no repositório, e não o que estava no backup.
- **Cluster de teste ao lado do original**: como as portas são fixas, é preciso parar o cluster original para testar a restauração na mesma máquina (`docker stop smarkee-control-plane smarkee-registry`).
