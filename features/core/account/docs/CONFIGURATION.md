<!-- Gerado por templates/feature/configuration_guide.py a partir dos settings.py dos papéis. Não edite: altere o código e regenere. -->
# Configuração de core.account: guia de parâmetros

Referência de **todas** as configurações dos papéis de `core.account` (`core-account-<papel>`), na ordem de precedência, e de como executar cada um. Decisões: [`0067`](../../../../.decisions/0067-configuracao-por-papel-com-config-toml-e-segredos-em-arquivo.md) (configuração), [`0069`](../../../../.decisions/0069-prefixo-smarkee-nas-variaveis-de-infraestrutura.md) (prefixo) e [`0070`](../../../../.decisions/0070-senhas-dos-servicos-como-arquivos-montados.md) (senhas como arquivos).

> Gerado dos `settings.py` de `src/core_account/<papel>/` e de `common/settings.py`. Para atualizar: `cd features/core/account && uv run python ../../../templates/feature/configuration_guide.py`.

## 1. Precedência

Cada campo é resolvido pela **primeira** fonte que o informa, da maior para a menor prioridade:

| # | Fonte | Como informar | Observações |
|---|---|---|---|
| 1 | **Linha de comando** | `--<seção>.<campo> <valor>` | Só no entrypoint do papel. **Segredo é recusado** (aparece em `ps`): qualquer argumento que cite `password` encerra o serviço. |
| 2 | **Variável de ambiente** | `CORE_ACCOUNT_<PAPEL>_<SEÇÃO>_<CAMPO>` | Em dev vem do `.env` (`docker compose` ou `uv run --env-file .env`). |
| 3 | **`config.toml`** | tabela `[tool.core.account.<papel>.<seção>]` | Caminho em `SMARKEE_CONFIG_PATH` (padrão `config.toml`). Arquivo ou tabela ausente equivale a vazio. **Nunca tem segredo.** |
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
| Linha de comando | O `command` é só o nome do papel (`[core-account-receiver]`), sem argumentos. |
| Ambiente | `environment:` repassa do `.env` só o que não é senha (por exemplo, audiência e IDs do Zitadel). |
| `config.toml` | Montado em `/etc/smarkee/config.toml` (`SMARKEE_CONFIG_PATH`). Endereços usam os nomes da rede Docker (`database.smarkee.internal`, `messaging.smarkee.internal`). |
| Arquivo de segredo | Bloco `secrets:` com `environment: <VARIÁVEL>`: cada papel monta só as suas senhas. |

Fora do Docker, os nomes `*.smarkee.internal` não resolvem: use as portas publicadas em `127.0.0.1` (Postgres `5432`, NATS `4222`) por flag ou variável.

## 3. `core-account-receiver`

Entrypoint do Receiver de Account (`core-account-receiver`, decisão 0015).

- **Prefixo das variáveis:** `CORE_ACCOUNT_RECEIVER_`
- **Tabela do `config.toml`:** `[tool.core.account.receiver.<seção>]`
- **Comando:** `core-account-receiver` (entrypoint `core_account.receiver.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `CORE_ACCOUNT_RECEIVER_AUTH_AUDIENCE`
- `CORE_ACCOUNT_RECEIVER_MESSAGING_URL`
- `CORE_ACCOUNT_RECEIVER_MESSAGING_USER`
- `CORE_ACCOUNT_RECEIVER_MESSAGING_PASSWORD`
- `CORE_ACCOUNT_RECEIVER_DATABASE_HOST`
- `CORE_ACCOUNT_RECEIVER_DATABASE_PORT`
- `CORE_ACCOUNT_RECEIVER_DATABASE_NAME`
- `CORE_ACCOUNT_RECEIVER_DATABASE_USER`
- `CORE_ACCOUNT_RECEIVER_DATABASE_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `CORE_ACCOUNT_RECEIVER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `CORE_ACCOUNT_RECEIVER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `CORE_ACCOUNT_RECEIVER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Obrigatória. Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `CORE_ACCOUNT_RECEIVER_DATABASE_PORT` | `--database.port` | `int \| None` | — | Obrigatória. |
| `database.name` | `CORE_ACCOUNT_RECEIVER_DATABASE_NAME` | `--database.name` | `str \| None` | — | Obrigatória. |
| `database.user` | `CORE_ACCOUNT_RECEIVER_DATABASE_USER` | `--database.user` | `str \| None` | — | Obrigatória. Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `CORE_ACCOUNT_RECEIVER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `CORE_ACCOUNT_RECEIVER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `CORE_ACCOUNT_RECEIVER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `CORE_ACCOUNT_RECEIVER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `auth.issuer` | `CORE_ACCOUNT_RECEIVER_AUTH_ISSUER` | `--auth.issuer` | `str` | `'http://localhost:8080'` | Valor esperado de `iss`: o endereço público do provedor de identidade. |
| `auth.jwks_url` | `CORE_ACCOUNT_RECEIVER_AUTH_JWKS_URL` | `--auth.jwks_url` | `str` | `'http://localhost:8000/oauth/v2/keys'` | Endereço (da rede interna) em que as chaves públicas são buscadas. |
| `auth.host_header` | `CORE_ACCOUNT_RECEIVER_AUTH_HOST_HEADER` | `--auth.host_header` | `str` | `'localhost:8080'` | `Host` enviado ao provedor nas chamadas internas: ele resolve a instância por esse valor. |
| `auth.audience` | `CORE_ACCOUNT_RECEIVER_AUTH_AUDIENCE` | `--auth.audience` | `str \| None` | — | Obrigatória. ID do projeto da plataforma (audience dos access tokens). Sem default. |
| `auth.jwks_cache_seconds` | `CORE_ACCOUNT_RECEIVER_AUTH_JWKS_CACHE_SECONDS` | `--auth.jwks_cache_seconds` | `int` | `300` |  |
| `api.host` | `CORE_ACCOUNT_RECEIVER_API_HOST` | `--api.host` | `str` | `'0.0.0.0'` |  |
| `api.port` | `CORE_ACCOUNT_RECEIVER_API_PORT` | `--api.port` | `int` | `8000` |  |
| `api.anonymous_rate_limit` | `CORE_ACCOUNT_RECEIVER_API_ANONYMOUS_RATE_LIMIT` | `--api.anonymous_rate_limit` | `int` | `5` |  |
| `api.anonymous_rate_window_seconds` | `CORE_ACCOUNT_RECEIVER_API_ANONYMOUS_RATE_WINDOW_SECONDS` | `--api.anonymous_rate_window_seconds` | `int` | `60` |  |
| `api.client_address_header` | `CORE_ACCOUNT_RECEIVER_API_CLIENT_ADDRESS_HEADER` | `--api.client_address_header` | `str \| None` | `'x-forwarded-for'` | Cabeçalho com o endereço do cliente, definido pelo gateway (único acesso ao serviço). |
| `peers.organizations_url` | `CORE_ACCOUNT_RECEIVER_PEERS_ORGANIZATIONS_URL` | `--peers.organizations_url` | `str` | `'http://localhost:8000'` |  |
| `peers.services_url` | `CORE_ACCOUNT_RECEIVER_PEERS_SERVICES_URL` | `--peers.services_url` | `str` | `'http://localhost:8000'` |  |
| `peers.timeout_seconds` | `CORE_ACCOUNT_RECEIVER_PEERS_TIMEOUT_SECONDS` | `--peers.timeout_seconds` | `float` | `5.0` |  |

**Definido no `config.toml` de dev:**

```toml
[tool.core.account.receiver.auth]
host_header = "ipm-dev.smarkee.com.br:8080"
issuer = "http://ipm-dev.smarkee.com.br:8080"
jwks_url = "http://gateway.smarkee.internal:8000/oauth/v2/keys"

[tool.core.account.receiver.database]
host = "database.smarkee.internal"
name = "smarkee"
port = 5432
user = "core_account_receiver_login"

[tool.core.account.receiver.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"

[tool.core.account.receiver.peers]
organizations_url = "http://ipm-organization-receiver.smarkee.internal:8000"
services_url = "http://sum-service-receiver.smarkee.internal:8000"
```

**Executar** (de `features/core/account`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d core-account-receiver
docker compose logs -f core-account-receiver

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env core-account-receiver \
    --api.port 8001 \
    --database.host localhost \
    --messaging.url nats://localhost:4222

# Lista todas as flags aceitas pelo papel
uv run core-account-receiver --help
```

## 4. `core-account-manager`

Entrypoint do Manager de Account (`core-account-manager`, decisões 0015, 0019 e 0063).

- **Prefixo das variáveis:** `CORE_ACCOUNT_MANAGER_`
- **Tabela do `config.toml`:** `[tool.core.account.manager.<seção>]`
- **Comando:** `core-account-manager` (entrypoint `core_account.manager.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `CORE_ACCOUNT_MANAGER_MESSAGING_URL`
- `CORE_ACCOUNT_MANAGER_MESSAGING_USER`
- `CORE_ACCOUNT_MANAGER_MESSAGING_PASSWORD`
- `CORE_ACCOUNT_MANAGER_DATABASE_HOST`
- `CORE_ACCOUNT_MANAGER_DATABASE_PORT`
- `CORE_ACCOUNT_MANAGER_DATABASE_NAME`
- `CORE_ACCOUNT_MANAGER_DATABASE_USER`
- `CORE_ACCOUNT_MANAGER_DATABASE_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `CORE_ACCOUNT_MANAGER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `CORE_ACCOUNT_MANAGER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `CORE_ACCOUNT_MANAGER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Obrigatória. Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `CORE_ACCOUNT_MANAGER_DATABASE_PORT` | `--database.port` | `int \| None` | — | Obrigatória. |
| `database.name` | `CORE_ACCOUNT_MANAGER_DATABASE_NAME` | `--database.name` | `str \| None` | — | Obrigatória. |
| `database.user` | `CORE_ACCOUNT_MANAGER_DATABASE_USER` | `--database.user` | `str \| None` | — | Obrigatória. Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `CORE_ACCOUNT_MANAGER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `CORE_ACCOUNT_MANAGER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `CORE_ACCOUNT_MANAGER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `CORE_ACCOUNT_MANAGER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `loop.failure_limit` | `CORE_ACCOUNT_MANAGER_LOOP_FAILURE_LIMIT` | `--loop.failure_limit` | `int` | `5` | Falhas por geração antes de `Failed` (`schemas/core/account/desired`, `failureLimit`). |
| `loop.progress_deadline_seconds` | `CORE_ACCOUNT_MANAGER_LOOP_PROGRESS_DEADLINE_SECONDS` | `--loop.progress_deadline_seconds` | `int` | `300` | Prazo para a geração convergir antes de `Failed` com `ProgressDeadlineExceeded` (`schemas/core/account/desired`, `progressDeadline`; decisão 0078). |
| `platform.roles` | `CORE_ACCOUNT_MANAGER_PLATFORM_ROLES` | `--platform.roles` | `tuple[str, ...]` | `('core.account.delete', 'core.account.get', 'sum.ipm.disable', 'sum.ipm.enable', 'sum.ipm.get')` | Roles de ação gravadas no `desired` do usuário cadastrado (decisão 0025). Lista em JSON. |
| `health.port` | `CORE_ACCOUNT_MANAGER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.core.account.manager.database]
host = "database.smarkee.internal"
name = "smarkee"
port = 5432
user = "core_account_manager_login"

[tool.core.account.manager.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/core/account`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d core-account-manager
docker compose logs -f core-account-manager

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env core-account-manager \
    --health.port 8002 \
    --database.host localhost \
    --messaging.url nats://localhost:4222 \
    --loop.failure_limit 3

# Lista todas as flags aceitas pelo papel
uv run core-account-manager --help
```

## 5. `core-account-publisher`

Entrypoint do Publisher de `core.account` (decisões 0015 e 0033).

- **Prefixo das variáveis:** `CORE_ACCOUNT_PUBLISHER_`
- **Tabela do `config.toml`:** `[tool.core.account.publisher.<seção>]`
- **Comando:** `core-account-publisher` (entrypoint `core_account.publisher.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `CORE_ACCOUNT_PUBLISHER_MESSAGING_URL`
- `CORE_ACCOUNT_PUBLISHER_MESSAGING_USER`
- `CORE_ACCOUNT_PUBLISHER_MESSAGING_PASSWORD`
- `CORE_ACCOUNT_PUBLISHER_DATABASE_HOST`
- `CORE_ACCOUNT_PUBLISHER_DATABASE_PORT`
- `CORE_ACCOUNT_PUBLISHER_DATABASE_NAME`
- `CORE_ACCOUNT_PUBLISHER_DATABASE_USER`
- `CORE_ACCOUNT_PUBLISHER_DATABASE_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `CORE_ACCOUNT_PUBLISHER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `CORE_ACCOUNT_PUBLISHER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `CORE_ACCOUNT_PUBLISHER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Obrigatória. Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `CORE_ACCOUNT_PUBLISHER_DATABASE_PORT` | `--database.port` | `int \| None` | — | Obrigatória. |
| `database.name` | `CORE_ACCOUNT_PUBLISHER_DATABASE_NAME` | `--database.name` | `str \| None` | — | Obrigatória. |
| `database.user` | `CORE_ACCOUNT_PUBLISHER_DATABASE_USER` | `--database.user` | `str \| None` | — | Obrigatória. Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `CORE_ACCOUNT_PUBLISHER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `CORE_ACCOUNT_PUBLISHER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `CORE_ACCOUNT_PUBLISHER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `CORE_ACCOUNT_PUBLISHER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `health.port` | `CORE_ACCOUNT_PUBLISHER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.core.account.publisher.database]
host = "database.smarkee.internal"
name = "smarkee"
port = 5432
user = "core_account_publisher_login"

[tool.core.account.publisher.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/core/account`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d core-account-publisher
docker compose logs -f core-account-publisher

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env core-account-publisher \
    --health.port 8003 \
    --database.host localhost \
    --messaging.url nats://localhost:4222

# Lista todas as flags aceitas pelo papel
uv run core-account-publisher --help
```

## 6. `core-account-reconciler`

Entrypoint do Reconciler de Account (`core-account-reconciler`, decisões 0015 e 0063).

- **Prefixo das variáveis:** `CORE_ACCOUNT_RECONCILER_`
- **Tabela do `config.toml`:** `[tool.core.account.reconciler.<seção>]`
- **Comando:** `core-account-reconciler` (entrypoint `core_account.reconciler.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `CORE_ACCOUNT_RECONCILER_MESSAGING_URL`
- `CORE_ACCOUNT_RECONCILER_MESSAGING_USER`
- `CORE_ACCOUNT_RECONCILER_MESSAGING_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `CORE_ACCOUNT_RECONCILER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `CORE_ACCOUNT_RECONCILER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `messaging.url` | `CORE_ACCOUNT_RECONCILER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `CORE_ACCOUNT_RECONCILER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `CORE_ACCOUNT_RECONCILER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.consumer_inactive_threshold_seconds` | `CORE_ACCOUNT_RECONCILER_MESSAGING_CONSUMER_INACTIVE_THRESHOLD_SECONDS` | `--messaging.consumer_inactive_threshold_seconds` | `int` | `300` | Tempo sem uso após o qual o servidor remove o consumer da instância. |
| `loop.observation_validity_seconds` | `CORE_ACCOUNT_RECONCILER_LOOP_OBSERVATION_VALIDITY_SECONDS` | `--loop.observation_validity_seconds` | `int` | `600` | `observationValidity` (PT10M): idade máxima de um `observed` para decidir. |
| `loop.action_deadline_seconds` | `CORE_ACCOUNT_RECONCILER_LOOP_ACTION_DEADLINE_SECONDS` | `--loop.action_deadline_seconds` | `int` | `120` | `actionDeadline` (PT2M): prazo da `action` pendente e da espera pela observação causada. |
| `loop.reevaluation_interval_seconds` | `CORE_ACCOUNT_RECONCILER_LOOP_REEVALUATION_INTERVAL_SECONDS` | `--loop.reevaluation_interval_seconds` | `int` | `30` | Período da reavaliação periódica de todos os recursos (com jitter). |
| `loop.reevaluation_jitter` | `CORE_ACCOUNT_RECONCILER_LOOP_REEVALUATION_JITTER` | `--loop.reevaluation_jitter` | `float` | `0.2` |  |
| `loop.failure_backoff_seconds` | `CORE_ACCOUNT_RECONCILER_LOOP_FAILURE_BACKOFF_SECONDS` | `--loop.failure_backoff_seconds` | `int` | `5` | Atraso após o primeiro `failed`; dobra a cada falha seguida, até o máximo. |
| `loop.failure_backoff_maximum_seconds` | `CORE_ACCOUNT_RECONCILER_LOOP_FAILURE_BACKOFF_MAXIMUM_SECONDS` | `--loop.failure_backoff_maximum_seconds` | `int` | `300` |  |
| `health.port` | `CORE_ACCOUNT_RECONCILER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.core.account.reconciler.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/core/account`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d core-account-reconciler
docker compose logs -f core-account-reconciler

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env core-account-reconciler \
    --health.port 8004 \
    --messaging.url nats://localhost:4222 \
    --loop.reevaluation_interval_seconds 10

# Lista todas as flags aceitas pelo papel
uv run core-account-reconciler --help
```

## 7. `core-account-observer`

Entrypoint do Observer de Account (`core-account-observer`, decisões 0015 e 0063).

- **Prefixo das variáveis:** `CORE_ACCOUNT_OBSERVER_`
- **Tabela do `config.toml`:** `[tool.core.account.observer.<seção>]`
- **Comando:** `core-account-observer` (entrypoint `core_account.observer.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `CORE_ACCOUNT_OBSERVER_MESSAGING_URL`
- `CORE_ACCOUNT_OBSERVER_MESSAGING_USER`
- `CORE_ACCOUNT_OBSERVER_MESSAGING_PASSWORD`
- `CORE_ACCOUNT_OBSERVER_IDENTITY_REGISTER_ORGANIZATION_ID`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `CORE_ACCOUNT_OBSERVER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `CORE_ACCOUNT_OBSERVER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `messaging.url` | `CORE_ACCOUNT_OBSERVER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `CORE_ACCOUNT_OBSERVER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `CORE_ACCOUNT_OBSERVER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.consumer_inactive_threshold_seconds` | `CORE_ACCOUNT_OBSERVER_MESSAGING_CONSUMER_INACTIVE_THRESHOLD_SECONDS` | `--messaging.consumer_inactive_threshold_seconds` | `int` | `300` | Tempo sem uso após o qual o servidor remove o consumer da instância. |
| `identity.base_url` | `CORE_ACCOUNT_OBSERVER_IDENTITY_BASE_URL` | `--identity.base_url` | `str` | `'http://localhost:8080'` | Endereço da API do Zitadel na rede interna (não passa pelo gateway público). |
| `identity.host_header` | `CORE_ACCOUNT_OBSERVER_IDENTITY_HOST_HEADER` | `--identity.host_header` | `str` | `'localhost:8080'` | `Host` enviado ao Zitadel: ele resolve a instância pelo domínio externo. |
| `identity.issuer` | `CORE_ACCOUNT_OBSERVER_IDENTITY_ISSUER` | `--identity.issuer` | `str` | `'http://localhost:8080'` | Audience da assertion JWT da conta de serviço. |
| `identity.key_file` | `CORE_ACCOUNT_OBSERVER_IDENTITY_KEY_FILE` | `--identity.key_file` | `str` | `'/run/secrets/zitadel-key.json'` | Chave JSON da conta de serviço do papel (montada só no contêiner dele). |
| `identity.timeout_seconds` | `CORE_ACCOUNT_OBSERVER_IDENTITY_TIMEOUT_SECONDS` | `--identity.timeout_seconds` | `float` | `5.0` |  |
| `identity.register_organization_id` | `CORE_ACCOUNT_OBSERVER_IDENTITY_REGISTER_ORGANIZATION_ID` | `--identity.register_organization_id` | `str \| None` | — | Obrigatória. ID da organização `register`: onde estão os usuários e as autorizações deles. Sem default. |
| `partition.index` | `CORE_ACCOUNT_OBSERVER_PARTITION_INDEX` | `--partition.index` | `int` | `0` |  |
| `partition.count` | `CORE_ACCOUNT_OBSERVER_PARTITION_COUNT` | `--partition.count` | `int` | `1` | Partição por `resourceId`: a instância observa só `hash mod count == index`. |
| `health.port` | `CORE_ACCOUNT_OBSERVER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |
| `loop.observation_interval_seconds` | `CORE_ACCOUNT_OBSERVER_LOOP_OBSERVATION_INTERVAL_SECONDS` | `--loop.observation_interval_seconds` | `int` | `300` | `observationInterval` (PT5M) de `schemas/core/account/desired`. |
| `loop.observation_jitter` | `CORE_ACCOUNT_OBSERVER_LOOP_OBSERVATION_JITTER` | `--loop.observation_jitter` | `float` | `0.2` |  |
| `loop.maximum_concurrent_reads` | `CORE_ACCOUNT_OBSERVER_LOOP_MAXIMUM_CONCURRENT_READS` | `--loop.maximum_concurrent_reads` | `int` | `4` | Leituras simultâneas no Zitadel: limita a pressão sobre o provedor. |

**Definido no `config.toml` de dev:**

```toml
[tool.core.account.observer.identity]
base_url = "http://identity.smarkee.internal:8080"
host_header = "ipm-dev.smarkee.com.br:8080"
issuer = "http://ipm-dev.smarkee.com.br:8080"

[tool.core.account.observer.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/core/account`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d core-account-observer
docker compose logs -f core-account-observer

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env core-account-observer \
    --health.port 8005 \
    --messaging.url nats://localhost:4222 \
    --identity.base_url http://localhost:8080 \
    --loop.observation_interval_seconds 60

# Lista todas as flags aceitas pelo papel
uv run core-account-observer --help
```

## 8. `core-account-executor`

Entrypoint do Executor de Account (`core-account-executor`, decisões 0015 e 0063).

- **Prefixo das variáveis:** `CORE_ACCOUNT_EXECUTOR_`
- **Tabela do `config.toml`:** `[tool.core.account.executor.<seção>]`
- **Comando:** `core-account-executor` (entrypoint `core_account.executor.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `CORE_ACCOUNT_EXECUTOR_MESSAGING_URL`
- `CORE_ACCOUNT_EXECUTOR_MESSAGING_USER`
- `CORE_ACCOUNT_EXECUTOR_MESSAGING_PASSWORD`
- `CORE_ACCOUNT_EXECUTOR_IDENTITY_REGISTER_ORGANIZATION_ID`
- `CORE_ACCOUNT_EXECUTOR_IDENTITY_PROJECT_IDS`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `CORE_ACCOUNT_EXECUTOR_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `CORE_ACCOUNT_EXECUTOR_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `messaging.url` | `CORE_ACCOUNT_EXECUTOR_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `CORE_ACCOUNT_EXECUTOR_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `CORE_ACCOUNT_EXECUTOR_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `identity.base_url` | `CORE_ACCOUNT_EXECUTOR_IDENTITY_BASE_URL` | `--identity.base_url` | `str` | `'http://localhost:8080'` | Endereço da API do Zitadel na rede interna (não passa pelo gateway público). |
| `identity.host_header` | `CORE_ACCOUNT_EXECUTOR_IDENTITY_HOST_HEADER` | `--identity.host_header` | `str` | `'localhost:8080'` | `Host` enviado ao Zitadel: ele resolve a instância pelo domínio externo. |
| `identity.issuer` | `CORE_ACCOUNT_EXECUTOR_IDENTITY_ISSUER` | `--identity.issuer` | `str` | `'http://localhost:8080'` | Audience da assertion JWT da conta de serviço. |
| `identity.key_file` | `CORE_ACCOUNT_EXECUTOR_IDENTITY_KEY_FILE` | `--identity.key_file` | `str` | `'/run/secrets/zitadel-key.json'` | Chave JSON da conta de serviço do papel (montada só no contêiner dele). |
| `identity.timeout_seconds` | `CORE_ACCOUNT_EXECUTOR_IDENTITY_TIMEOUT_SECONDS` | `--identity.timeout_seconds` | `float` | `10.0` |  |
| `identity.register_organization_id` | `CORE_ACCOUNT_EXECUTOR_IDENTITY_REGISTER_ORGANIZATION_ID` | `--identity.register_organization_id` | `str \| None` | — | Obrigatória. ID da organização `register`: onde os usuários são criados e recebem as autorizações. Sem default. |
| `identity.project_ids` | `CORE_ACCOUNT_EXECUTOR_IDENTITY_PROJECT_IDS` | `--identity.project_ids` | `dict[str, str]` | `{}` | Obrigatória. IDs dos projetos de roles que o Executor pode conceder, por módulo (`{"core": "<ID>", ...}`). A role `<módulo>.<tipo>.<ação>` vai para o projeto do seu módulo. Um módulo ausente aqui é rejeitado antes de chamar o Zitadel; o Zitadel também nega o que o Executor não tem como `PROJECT_GRANT_OWNER` (decisão 0032). Sem default. |
| `partition.count` | `CORE_ACCOUNT_EXECUTOR_PARTITION_COUNT` | `--partition.count` | `int` | `4` | Partições do Stream `ACTION` (bootstrap do messaging): um consumer e um laço por partição. |
| `health.port` | `CORE_ACCOUNT_EXECUTOR_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.core.account.executor.identity]
base_url = "http://identity.smarkee.internal:8080"
host_header = "ipm-dev.smarkee.com.br:8080"
issuer = "http://ipm-dev.smarkee.com.br:8080"

[tool.core.account.executor.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/core/account`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d core-account-executor
docker compose logs -f core-account-executor

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env core-account-executor \
    --health.port 8006 \
    --messaging.url nats://localhost:4222 \
    --identity.base_url http://localhost:8080 \
    --partition.count 4

# Lista todas as flags aceitas pelo papel
uv run core-account-executor --help
```
