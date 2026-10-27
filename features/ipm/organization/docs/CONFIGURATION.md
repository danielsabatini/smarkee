<!-- Gerado por templates/feature/configuration_guide.py a partir dos settings.py dos papéis. Não edite: altere o código e regenere. -->
# Configuração de ipm.organization: guia de parâmetros

Referência de **todas** as configurações dos papéis de `ipm.organization` (`ipm-organization-<papel>`), na ordem de precedência, e de como executar cada um. Decisões: [`0067`](../../../../.decisions/0067-configuracao-por-papel-com-config-toml-e-segredos-em-arquivo.md) (configuração), [`0069`](../../../../.decisions/0069-prefixo-smarkee-nas-variaveis-de-infraestrutura.md) (prefixo) e [`0070`](../../../../.decisions/0070-senhas-dos-servicos-como-arquivos-montados.md) (senhas como arquivos).

> Gerado dos `settings.py` de `src/ipm_organization/<papel>/` e de `common/settings.py`. Para atualizar: `cd features/ipm/organization && uv run python ../../../templates/feature/configuration_guide.py`.

## 1. Precedência

Cada campo é resolvido pela **primeira** fonte que o informa, da maior para a menor prioridade:

| # | Fonte | Como informar | Observações |
|---|---|---|---|
| 1 | **Linha de comando** | `--<seção>.<campo> <valor>` | Só no entrypoint do papel. **Segredo é recusado** (aparece em `ps`): qualquer argumento que cite `password` encerra o serviço. |
| 2 | **Variável de ambiente** | `IPM_ORGANIZATION_<PAPEL>_<SEÇÃO>_<CAMPO>` | Em dev vem do `.env` (`docker compose` ou `uv run --env-file .env`). |
| 3 | **`config.toml`** | tabela `[tool.ipm.organization.<papel>.<seção>]` | Caminho em `SMARKEE_CONFIG_PATH` (padrão `config.toml`). Arquivo ou tabela ausente equivale a vazio. **Nunca tem segredo.** |
| 4 | **Arquivo de segredo** | `/run/secrets/<NOME-DA-VARIÁVEL>` | Diretório em `SMARKEE_SECRETS_DIR` (padrão `/run/secrets`). O nome do arquivo é o da variável completa. Em dev o compose monta as senhas aqui a partir do `.env`. |
| 5 | **Default do código** | — | Só para o que não é credencial nem endereço de conexão. |

Pontos que costumam surpreender:

- O **ambiente vence o arquivo de segredo**. Uma variável `*_PASSWORD` definida no ambiente anula o segredo montado: os manifestos não devem defini-las.
- **Sem default no código**: `database.host|port|name|user|password` e `messaging.url|user|password`, além do que cada papel marca como obrigatório. Faltando algum, o serviço sai com `missing required configuration` e lista as variáveis.
- **Campo desconhecido** é rejeitado (`extra="forbid"`): variável, chave do `config.toml` ou flag com nome errado falha, em vez de ser ignorada.
- O nome da variável separa só a **seção** do **campo**: `MESSAGING_URL` é `messaging.url`; `LOOP_REEVALUATION_INTERVAL_SECONDS` é `loop.reevaluation_interval_seconds`.
- Valores compostos (listas e dicionários) vão como **JSON** na variável e na flag.

### Variáveis de execução (não são de um papel)

| Variável | Padrão | Para quê |
|---|---|---|
| `SMARKEE_CONFIG_PATH` | `config.toml` | Caminho do arquivo de configuração. |
| `SMARKEE_SECRETS_DIR` | `/run/secrets` | Diretório dos arquivos de segredo. |
| `SMARKEE_ENVIRONMENT` | `dev` | Ambiente informado à telemetria (`dev`, `stg`, `prd`). |

## 2. Como o dev entrega cada fonte

| Fonte | No `compose.yaml` |
|---|---|
| Linha de comando | O `command` é só o nome do papel (`[ipm-organization-receiver]`), sem argumentos. |
| Ambiente | `environment:` repassa do `.env` só o que não é senha (por exemplo, audiência e IDs do Zitadel). |
| `config.toml` | Montado em `/etc/smarkee/config.toml` (`SMARKEE_CONFIG_PATH`). Endereços usam os nomes da rede Docker (`database.smarkee.internal`, `messaging.smarkee.internal`). |
| Arquivo de segredo | Bloco `secrets:` com `environment: <VARIÁVEL>`: cada papel monta só as suas senhas. |

Fora do Docker, os nomes `*.smarkee.internal` não resolvem: use as portas publicadas em `127.0.0.1` (Postgres `5432`, NATS `4222`) por flag ou variável.

## 3. `ipm-organization-receiver`

Entrypoint do Receiver de Organization (`ipm-organization-receiver`, decisão 0015).

- **Prefixo das variáveis:** `IPM_ORGANIZATION_RECEIVER_`
- **Tabela do `config.toml`:** `[tool.ipm.organization.receiver.<seção>]`
- **Comando:** `ipm-organization-receiver` (entrypoint `ipm_organization.receiver.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_ORGANIZATION_RECEIVER_AUTH_AUDIENCE`
- `IPM_ORGANIZATION_RECEIVER_MESSAGING_URL`
- `IPM_ORGANIZATION_RECEIVER_MESSAGING_USER`
- `IPM_ORGANIZATION_RECEIVER_MESSAGING_PASSWORD`
- `IPM_ORGANIZATION_RECEIVER_DATABASE_HOST`
- `IPM_ORGANIZATION_RECEIVER_DATABASE_PORT`
- `IPM_ORGANIZATION_RECEIVER_DATABASE_NAME`
- `IPM_ORGANIZATION_RECEIVER_DATABASE_USER`
- `IPM_ORGANIZATION_RECEIVER_DATABASE_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_ORGANIZATION_RECEIVER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_ORGANIZATION_RECEIVER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `IPM_ORGANIZATION_RECEIVER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Obrigatória. Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `IPM_ORGANIZATION_RECEIVER_DATABASE_PORT` | `--database.port` | `int \| None` | — | Obrigatória. |
| `database.name` | `IPM_ORGANIZATION_RECEIVER_DATABASE_NAME` | `--database.name` | `str \| None` | — | Obrigatória. |
| `database.user` | `IPM_ORGANIZATION_RECEIVER_DATABASE_USER` | `--database.user` | `str \| None` | — | Obrigatória. Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `IPM_ORGANIZATION_RECEIVER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `IPM_ORGANIZATION_RECEIVER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_ORGANIZATION_RECEIVER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_ORGANIZATION_RECEIVER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `auth.issuer` | `IPM_ORGANIZATION_RECEIVER_AUTH_ISSUER` | `--auth.issuer` | `str` | `'http://localhost:8080'` | Valor esperado de `iss`: o endereço público do provedor de identidade. |
| `auth.jwks_url` | `IPM_ORGANIZATION_RECEIVER_AUTH_JWKS_URL` | `--auth.jwks_url` | `str` | `'http://localhost:8000/oauth/v2/keys'` | Endereço (da rede interna) em que as chaves públicas são buscadas. |
| `auth.userinfo_url` | `IPM_ORGANIZATION_RECEIVER_AUTH_USERINFO_URL` | `--auth.userinfo_url` | `str` | `'http://localhost:8000/oidc/v1/userinfo'` |  |
| `auth.host_header` | `IPM_ORGANIZATION_RECEIVER_AUTH_HOST_HEADER` | `--auth.host_header` | `str` | `'localhost:8080'` | `Host` enviado ao provedor nas chamadas internas: ele resolve a instância por esse valor. |
| `auth.audience` | `IPM_ORGANIZATION_RECEIVER_AUTH_AUDIENCE` | `--auth.audience` | `str \| None` | — | Obrigatória. ID do projeto da plataforma (audience dos access tokens). Sem default. |
| `auth.jwks_cache_seconds` | `IPM_ORGANIZATION_RECEIVER_AUTH_JWKS_CACHE_SECONDS` | `--auth.jwks_cache_seconds` | `int` | `300` |  |
| `auth.userinfo_cache_seconds` | `IPM_ORGANIZATION_RECEIVER_AUTH_USERINFO_CACHE_SECONDS` | `--auth.userinfo_cache_seconds` | `int` | `300` |  |
| `api.host` | `IPM_ORGANIZATION_RECEIVER_API_HOST` | `--api.host` | `str` | `'0.0.0.0'` |  |
| `api.port` | `IPM_ORGANIZATION_RECEIVER_API_PORT` | `--api.port` | `int` | `8000` |  |
| `api.organization_quota` | `IPM_ORGANIZATION_RECEIVER_API_ORGANIZATION_QUOTA` | `--api.organization_quota` | `int` | `1` | Organizations por dono para quem não é operador (decisão 0010). |
| `peers.users_url` | `IPM_ORGANIZATION_RECEIVER_PEERS_USERS_URL` | `--peers.users_url` | `str` | `'http://localhost:8000'` |  |
| `peers.serviceaccounts_url` | `IPM_ORGANIZATION_RECEIVER_PEERS_SERVICEACCOUNTS_URL` | `--peers.serviceaccounts_url` | `str` | `'http://localhost:8000'` |  |
| `peers.billing_accounts_url` | `IPM_ORGANIZATION_RECEIVER_PEERS_BILLING_ACCOUNTS_URL` | `--peers.billing_accounts_url` | `str` | `'http://localhost:8000'` |  |
| `peers.timeout_seconds` | `IPM_ORGANIZATION_RECEIVER_PEERS_TIMEOUT_SECONDS` | `--peers.timeout_seconds` | `float` | `5.0` |  |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.organization.receiver.auth]
host_header = "ipm-dev.smarkee.com.br:8080"
issuer = "http://ipm-dev.smarkee.com.br:8080"
jwks_url = "http://gateway.smarkee.internal:8000/oauth/v2/keys"
userinfo_url = "http://gateway.smarkee.internal:8000/oidc/v1/userinfo"

[tool.ipm.organization.receiver.database]
host = "database.smarkee.internal"
name = "ssot"
port = 5432
user = "ipm_organization_receiver_login"

[tool.ipm.organization.receiver.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"

[tool.ipm.organization.receiver.peers]
users_url = "http://ipm-user-receiver.smarkee.internal:8000"
serviceaccounts_url = "http://ipm-serviceaccount-receiver.smarkee.internal:8000"
billing_accounts_url = "http://bsm-account-receiver.smarkee.internal:8000"
```

**Executar** (de `features/ipm/organization`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-organization-receiver
docker compose logs -f ipm-organization-receiver

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-organization-receiver \
    --api.port 8001 \
    --database.host localhost \
    --messaging.url nats://localhost:4222

# Lista todas as flags aceitas pelo papel
uv run ipm-organization-receiver --help
```

## 4. `ipm-organization-manager`

Entrypoint do Manager de Organization (`ipm-organization-manager`, decisões 0015, 0019 e 0063).

- **Prefixo das variáveis:** `IPM_ORGANIZATION_MANAGER_`
- **Tabela do `config.toml`:** `[tool.ipm.organization.manager.<seção>]`
- **Comando:** `ipm-organization-manager` (entrypoint `ipm_organization.manager.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_ORGANIZATION_MANAGER_MESSAGING_URL`
- `IPM_ORGANIZATION_MANAGER_MESSAGING_USER`
- `IPM_ORGANIZATION_MANAGER_MESSAGING_PASSWORD`
- `IPM_ORGANIZATION_MANAGER_DATABASE_HOST`
- `IPM_ORGANIZATION_MANAGER_DATABASE_PORT`
- `IPM_ORGANIZATION_MANAGER_DATABASE_NAME`
- `IPM_ORGANIZATION_MANAGER_DATABASE_USER`
- `IPM_ORGANIZATION_MANAGER_DATABASE_PASSWORD`
- `IPM_ORGANIZATION_MANAGER_USER_ACCESS_USER_EXECUTOR_ACCOUNT_ID`
- `IPM_ORGANIZATION_MANAGER_USER_ACCESS_USER_OBSERVER_ACCOUNT_ID`
- `IPM_ORGANIZATION_MANAGER_USER_ACCESS_SERVICEACCOUNT_EXECUTOR_ACCOUNT_ID`
- `IPM_ORGANIZATION_MANAGER_USER_ACCESS_SERVICEACCOUNT_OBSERVER_ACCOUNT_ID`
- `IPM_ORGANIZATION_MANAGER_USER_ACCESS_SERVICEACCOUNT_CONTROLLER_ACCOUNT_ID`
- `IPM_ORGANIZATION_MANAGER_USER_ACCESS_USER_CONTROLLER_ACCOUNT_ID`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_ORGANIZATION_MANAGER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_ORGANIZATION_MANAGER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `IPM_ORGANIZATION_MANAGER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Obrigatória. Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `IPM_ORGANIZATION_MANAGER_DATABASE_PORT` | `--database.port` | `int \| None` | — | Obrigatória. |
| `database.name` | `IPM_ORGANIZATION_MANAGER_DATABASE_NAME` | `--database.name` | `str \| None` | — | Obrigatória. |
| `database.user` | `IPM_ORGANIZATION_MANAGER_DATABASE_USER` | `--database.user` | `str \| None` | — | Obrigatória. Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `IPM_ORGANIZATION_MANAGER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `IPM_ORGANIZATION_MANAGER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_ORGANIZATION_MANAGER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_ORGANIZATION_MANAGER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `loop.failure_limit` | `IPM_ORGANIZATION_MANAGER_LOOP_FAILURE_LIMIT` | `--loop.failure_limit` | `int` | `5` | Falhas por geração antes de `Failed` (`schemas/ipm/organization/desired`, `failureLimit`). |
| `loop.progress_deadline_seconds` | `IPM_ORGANIZATION_MANAGER_LOOP_PROGRESS_DEADLINE_SECONDS` | `--loop.progress_deadline_seconds` | `int` | `300` | Prazo para a geração convergir antes de `Failed` com `ProgressDeadlineExceeded` (`schemas/ipm/organization/desired`, `progressDeadline`; decisão 0078). |
| `user_access.user_executor_account_id` | `IPM_ORGANIZATION_MANAGER_USER_ACCESS_USER_EXECUTOR_ACCOUNT_ID` | `--user_access.user_executor_account_id` | `str \| None` | — | Obrigatória. Conta `ipm-user-executor` (organização `core`). |
| `user_access.user_observer_account_id` | `IPM_ORGANIZATION_MANAGER_USER_ACCESS_USER_OBSERVER_ACCOUNT_ID` | `--user_access.user_observer_account_id` | `str \| None` | — | Obrigatória. Conta `ipm-user-observer` (organização `core`). |
| `user_access.serviceaccount_executor_account_id` | `IPM_ORGANIZATION_MANAGER_USER_ACCESS_SERVICEACCOUNT_EXECUTOR_ACCOUNT_ID` | `--user_access.serviceaccount_executor_account_id` | `str \| None` | — | Obrigatória. Conta `ipm-serviceaccount-executor` (organização `core`; decisão 0094). |
| `user_access.serviceaccount_observer_account_id` | `IPM_ORGANIZATION_MANAGER_USER_ACCESS_SERVICEACCOUNT_OBSERVER_ACCOUNT_ID` | `--user_access.serviceaccount_observer_account_id` | `str \| None` | — | Obrigatória. Conta `ipm-serviceaccount-observer` (organização `core`; decisão 0094). |
| `user_access.serviceaccount_controller_account_id` | `IPM_ORGANIZATION_MANAGER_USER_ACCESS_SERVICEACCOUNT_CONTROLLER_ACCOUNT_ID` | `--user_access.serviceaccount_controller_account_id` | `str \| None` | — | Obrigatória. Conta `ipm-serviceaccount-controller` (organização `core`; decisão 0096). |
| `user_access.user_controller_account_id` | `IPM_ORGANIZATION_MANAGER_USER_ACCESS_USER_CONTROLLER_ACCOUNT_ID` | `--user_access.user_controller_account_id` | `str \| None` | — | Obrigatória. Conta `ipm-user-controller` (organização `core`; decisão 0096). |
| `health.port` | `IPM_ORGANIZATION_MANAGER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.organization.manager.database]
host = "database.smarkee.internal"
name = "ssot"
port = 5432
user = "ipm_organization_manager_login"

[tool.ipm.organization.manager.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/ipm/organization`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-organization-manager
docker compose logs -f ipm-organization-manager

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-organization-manager \
    --health.port 8002 \
    --database.host localhost \
    --messaging.url nats://localhost:4222 \
    --loop.failure_limit 3

# Lista todas as flags aceitas pelo papel
uv run ipm-organization-manager --help
```

## 5. `ipm-organization-publisher`

Entrypoint do Publisher de `ipm.organization` (decisões 0015 e 0033).

- **Prefixo das variáveis:** `IPM_ORGANIZATION_PUBLISHER_`
- **Tabela do `config.toml`:** `[tool.ipm.organization.publisher.<seção>]`
- **Comando:** `ipm-organization-publisher` (entrypoint `ipm_organization.publisher.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_ORGANIZATION_PUBLISHER_MESSAGING_URL`
- `IPM_ORGANIZATION_PUBLISHER_MESSAGING_USER`
- `IPM_ORGANIZATION_PUBLISHER_MESSAGING_PASSWORD`
- `IPM_ORGANIZATION_PUBLISHER_DATABASE_HOST`
- `IPM_ORGANIZATION_PUBLISHER_DATABASE_PORT`
- `IPM_ORGANIZATION_PUBLISHER_DATABASE_NAME`
- `IPM_ORGANIZATION_PUBLISHER_DATABASE_USER`
- `IPM_ORGANIZATION_PUBLISHER_DATABASE_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_ORGANIZATION_PUBLISHER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_ORGANIZATION_PUBLISHER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `IPM_ORGANIZATION_PUBLISHER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Obrigatória. Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `IPM_ORGANIZATION_PUBLISHER_DATABASE_PORT` | `--database.port` | `int \| None` | — | Obrigatória. |
| `database.name` | `IPM_ORGANIZATION_PUBLISHER_DATABASE_NAME` | `--database.name` | `str \| None` | — | Obrigatória. |
| `database.user` | `IPM_ORGANIZATION_PUBLISHER_DATABASE_USER` | `--database.user` | `str \| None` | — | Obrigatória. Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `IPM_ORGANIZATION_PUBLISHER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `IPM_ORGANIZATION_PUBLISHER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_ORGANIZATION_PUBLISHER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_ORGANIZATION_PUBLISHER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `health.port` | `IPM_ORGANIZATION_PUBLISHER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.organization.publisher.database]
host = "database.smarkee.internal"
name = "ssot"
port = 5432
user = "ipm_organization_publisher_login"

[tool.ipm.organization.publisher.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/ipm/organization`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-organization-publisher
docker compose logs -f ipm-organization-publisher

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-organization-publisher \
    --health.port 8003 \
    --database.host localhost \
    --messaging.url nats://localhost:4222

# Lista todas as flags aceitas pelo papel
uv run ipm-organization-publisher --help
```
