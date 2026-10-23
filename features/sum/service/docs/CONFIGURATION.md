<!-- Gerado por templates/feature/configuration_guide.py a partir dos settings.py dos papéis. Não edite: altere o código e regenere. -->
# Configuração de sum.service: guia de parâmetros

Referência de **todas** as configurações dos papéis de `sum.service` (`sum-service-<papel>`), na ordem de precedência, e de como executar cada um. Decisões: [`0067`](../../../../.decisions/0067-configuracao-por-papel-com-config-toml-e-segredos-em-arquivo.md) (configuração), [`0069`](../../../../.decisions/0069-prefixo-smarkee-nas-variaveis-de-infraestrutura.md) (prefixo) e [`0070`](../../../../.decisions/0070-senhas-dos-servicos-como-arquivos-montados.md) (senhas como arquivos).

> Gerado dos `settings.py` de `src/sum_service/<papel>/` e de `common/settings.py`. Para atualizar: `cd features/sum/service && uv run python ../../../templates/feature/configuration_guide.py`.

## 1. Precedência

Cada campo é resolvido pela **primeira** fonte que o informa, da maior para a menor prioridade:

| # | Fonte | Como informar | Observações |
|---|---|---|---|
| 1 | **Linha de comando** | `--<seção>.<campo> <valor>` | Só no entrypoint do papel. **Segredo é recusado** (aparece em `ps`): qualquer argumento que cite `password` encerra o serviço. |
| 2 | **Variável de ambiente** | `SUM_SERVICE_<PAPEL>_<SEÇÃO>_<CAMPO>` | Em dev vem do `.env` (`docker compose` ou `uv run --env-file .env`). |
| 3 | **`config.toml`** | tabela `[tool.sum.service.<papel>.<seção>]` | Caminho em `SMARKEE_CONFIG_PATH` (padrão `config.toml`). Arquivo ou tabela ausente equivale a vazio. **Nunca tem segredo.** |
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
| Linha de comando | O `command` é só o nome do papel (`[sum-service-receiver]`), sem argumentos. |
| Ambiente | `environment:` repassa do `.env` só o que não é senha (por exemplo, audiência e IDs do Zitadel). |
| `config.toml` | Montado em `/etc/smarkee/config.toml` (`SMARKEE_CONFIG_PATH`). Endereços usam os nomes da rede Docker (`database.smarkee.internal`, `messaging.smarkee.internal`). |
| Arquivo de segredo | Bloco `secrets:` com `environment: <VARIÁVEL>`: cada papel monta só as suas senhas. |

Fora do Docker, os nomes `*.smarkee.internal` não resolvem: use as portas publicadas em `127.0.0.1` (Postgres `5432`, NATS `4222`) por flag ou variável.

## 3. `sum-service-receiver`

Entrypoint do Receiver de `sum.service` (`sum-service-receiver`, decisões 0015 e 0033).

- **Prefixo das variáveis:** `SUM_SERVICE_RECEIVER_`
- **Tabela do `config.toml`:** `[tool.sum.service.receiver.<seção>]`
- **Comando:** `sum-service-receiver` (entrypoint `sum_service.receiver.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `SUM_SERVICE_RECEIVER_AUTH_AUDIENCE`
- `SUM_SERVICE_RECEIVER_MESSAGING_URL`
- `SUM_SERVICE_RECEIVER_MESSAGING_USER`
- `SUM_SERVICE_RECEIVER_MESSAGING_PASSWORD`
- `SUM_SERVICE_RECEIVER_DATABASE_HOST`
- `SUM_SERVICE_RECEIVER_DATABASE_PORT`
- `SUM_SERVICE_RECEIVER_DATABASE_NAME`
- `SUM_SERVICE_RECEIVER_DATABASE_USER`
- `SUM_SERVICE_RECEIVER_DATABASE_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `SUM_SERVICE_RECEIVER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `SUM_SERVICE_RECEIVER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `SUM_SERVICE_RECEIVER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Obrigatória. Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `SUM_SERVICE_RECEIVER_DATABASE_PORT` | `--database.port` | `int \| None` | — | Obrigatória. |
| `database.name` | `SUM_SERVICE_RECEIVER_DATABASE_NAME` | `--database.name` | `str \| None` | — | Obrigatória. |
| `database.user` | `SUM_SERVICE_RECEIVER_DATABASE_USER` | `--database.user` | `str \| None` | — | Obrigatória. Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `SUM_SERVICE_RECEIVER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `SUM_SERVICE_RECEIVER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `SUM_SERVICE_RECEIVER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `SUM_SERVICE_RECEIVER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `auth.issuer` | `SUM_SERVICE_RECEIVER_AUTH_ISSUER` | `--auth.issuer` | `str` | `'http://localhost:8080'` | Valor esperado de `iss`: o endereço público do provedor de identidade. |
| `auth.jwks_url` | `SUM_SERVICE_RECEIVER_AUTH_JWKS_URL` | `--auth.jwks_url` | `str` | `'http://localhost:8000/oauth/v2/keys'` |  |
| `auth.host_header` | `SUM_SERVICE_RECEIVER_AUTH_HOST_HEADER` | `--auth.host_header` | `str` | `'localhost:8080'` |  |
| `auth.audience` | `SUM_SERVICE_RECEIVER_AUTH_AUDIENCE` | `--auth.audience` | `str \| None` | — | Obrigatória. ID do projeto de roles do SUM (`roles-sum`): audience dos tokens aceitos. |
| `auth.jwks_cache_seconds` | `SUM_SERVICE_RECEIVER_AUTH_JWKS_CACHE_SECONDS` | `--auth.jwks_cache_seconds` | `int` | `300` |  |
| `api.host` | `SUM_SERVICE_RECEIVER_API_HOST` | `--api.host` | `str` | `'0.0.0.0'` |  |
| `api.port` | `SUM_SERVICE_RECEIVER_API_PORT` | `--api.port` | `int` | `8000` |  |
| `peers.organizations_url` | `SUM_SERVICE_RECEIVER_PEERS_ORGANIZATIONS_URL` | `--peers.organizations_url` | `str` | `'http://localhost:8000'` |  |
| `peers.billing_accounts_url` | `SUM_SERVICE_RECEIVER_PEERS_BILLING_ACCOUNTS_URL` | `--peers.billing_accounts_url` | `str` | `'http://localhost:8000'` |  |
| `peers.timeout_seconds` | `SUM_SERVICE_RECEIVER_PEERS_TIMEOUT_SECONDS` | `--peers.timeout_seconds` | `float` | `5.0` |  |

**Definido no `config.toml` de dev:**

```toml
[tool.sum.service.receiver.auth]
host_header = "ipm-dev.smarkee.com.br:8080"
issuer = "http://ipm-dev.smarkee.com.br:8080"
jwks_url = "http://gateway.smarkee.internal:8000/oauth/v2/keys"

[tool.sum.service.receiver.database]
host = "database.smarkee.internal"
name = "smarkee"
port = 5432
user = "sum_service_receiver_login"

[tool.sum.service.receiver.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"

[tool.sum.service.receiver.peers]
organizations_url = "http://ipm-organization-receiver.smarkee.internal:8000"
billing_accounts_url = "http://bsm-account-receiver.smarkee.internal:8000"
```

**Executar** (de `features/sum/service`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d sum-service-receiver
docker compose logs -f sum-service-receiver

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env sum-service-receiver \
    --api.port 8001 \
    --database.host localhost \
    --messaging.url nats://localhost:4222

# Lista todas as flags aceitas pelo papel
uv run sum-service-receiver --help
```

## 4. `sum-service-manager`

Entrypoint do Manager de `sum.service` (`sum-service-manager`, decisões 0015 e 0033).

- **Prefixo das variáveis:** `SUM_SERVICE_MANAGER_`
- **Tabela do `config.toml`:** `[tool.sum.service.manager.<seção>]`
- **Comando:** `sum-service-manager` (entrypoint `sum_service.manager.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `SUM_SERVICE_MANAGER_MESSAGING_URL`
- `SUM_SERVICE_MANAGER_MESSAGING_USER`
- `SUM_SERVICE_MANAGER_MESSAGING_PASSWORD`
- `SUM_SERVICE_MANAGER_DATABASE_HOST`
- `SUM_SERVICE_MANAGER_DATABASE_PORT`
- `SUM_SERVICE_MANAGER_DATABASE_NAME`
- `SUM_SERVICE_MANAGER_DATABASE_USER`
- `SUM_SERVICE_MANAGER_DATABASE_PASSWORD`
- `SUM_SERVICE_MANAGER_CATALOG_ROLES`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `SUM_SERVICE_MANAGER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `SUM_SERVICE_MANAGER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `SUM_SERVICE_MANAGER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Obrigatória. Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `SUM_SERVICE_MANAGER_DATABASE_PORT` | `--database.port` | `int \| None` | — | Obrigatória. |
| `database.name` | `SUM_SERVICE_MANAGER_DATABASE_NAME` | `--database.name` | `str \| None` | — | Obrigatória. |
| `database.user` | `SUM_SERVICE_MANAGER_DATABASE_USER` | `--database.user` | `str \| None` | — | Obrigatória. Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `SUM_SERVICE_MANAGER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `SUM_SERVICE_MANAGER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `SUM_SERVICE_MANAGER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `SUM_SERVICE_MANAGER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `catalog.roles` | `SUM_SERVICE_MANAGER_CATALOG_ROLES` | `--catalog.roles` | `str \| None` | — | Obrigatória. Catálogo serviço → roles em JSON, por exemplo `{"ipm": ["ipm.organization.get"]}`. Sem default: o Manager não sobe sem um catálogo (decisão 0033). |
| `loop.failure_limit` | `SUM_SERVICE_MANAGER_LOOP_FAILURE_LIMIT` | `--loop.failure_limit` | `int` | `5` | Falhas por geração antes de `Failed` e da suspensão (`schemas/sum/service/desired`, `failureLimit`; decisão 0080). |
| `loop.progress_deadline_seconds` | `SUM_SERVICE_MANAGER_LOOP_PROGRESS_DEADLINE_SECONDS` | `--loop.progress_deadline_seconds` | `int` | `300` | Prazo para a geração convergir antes de `Failed` com `ProgressDeadlineExceeded` (`schemas/sum/service/desired`, `progressDeadline`; decisões 0078 e 0080). |
| `health.port` | `SUM_SERVICE_MANAGER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.sum.service.manager.database]
host = "database.smarkee.internal"
name = "smarkee"
port = 5432
user = "sum_service_manager_login"

[tool.sum.service.manager.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/sum/service`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d sum-service-manager
docker compose logs -f sum-service-manager

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env sum-service-manager \
    --health.port 8002 \
    --database.host localhost \
    --messaging.url nats://localhost:4222 \
    --loop.failure_limit 3

# Lista todas as flags aceitas pelo papel
uv run sum-service-manager --help
```

## 5. `sum-service-publisher`

Entrypoint do Publisher de `sum.service` (decisões 0015 e 0033).

- **Prefixo das variáveis:** `SUM_SERVICE_PUBLISHER_`
- **Tabela do `config.toml`:** `[tool.sum.service.publisher.<seção>]`
- **Comando:** `sum-service-publisher` (entrypoint `sum_service.publisher.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `SUM_SERVICE_PUBLISHER_MESSAGING_URL`
- `SUM_SERVICE_PUBLISHER_MESSAGING_USER`
- `SUM_SERVICE_PUBLISHER_MESSAGING_PASSWORD`
- `SUM_SERVICE_PUBLISHER_DATABASE_HOST`
- `SUM_SERVICE_PUBLISHER_DATABASE_PORT`
- `SUM_SERVICE_PUBLISHER_DATABASE_NAME`
- `SUM_SERVICE_PUBLISHER_DATABASE_USER`
- `SUM_SERVICE_PUBLISHER_DATABASE_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `SUM_SERVICE_PUBLISHER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `SUM_SERVICE_PUBLISHER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `SUM_SERVICE_PUBLISHER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Obrigatória. Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `SUM_SERVICE_PUBLISHER_DATABASE_PORT` | `--database.port` | `int \| None` | — | Obrigatória. |
| `database.name` | `SUM_SERVICE_PUBLISHER_DATABASE_NAME` | `--database.name` | `str \| None` | — | Obrigatória. |
| `database.user` | `SUM_SERVICE_PUBLISHER_DATABASE_USER` | `--database.user` | `str \| None` | — | Obrigatória. Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `SUM_SERVICE_PUBLISHER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `SUM_SERVICE_PUBLISHER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `SUM_SERVICE_PUBLISHER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `SUM_SERVICE_PUBLISHER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `health.port` | `SUM_SERVICE_PUBLISHER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.sum.service.publisher.database]
host = "database.smarkee.internal"
name = "smarkee"
port = 5432
user = "sum_service_publisher_login"

[tool.sum.service.publisher.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/sum/service`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d sum-service-publisher
docker compose logs -f sum-service-publisher

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env sum-service-publisher \
    --health.port 8003 \
    --database.host localhost \
    --messaging.url nats://localhost:4222

# Lista todas as flags aceitas pelo papel
uv run sum-service-publisher --help
```

## 6. `sum-service-reconciler`

Entrypoint do Reconciler de `sum.service` (`sum-service-reconciler`, decisões 0015 e 0033).

- **Prefixo das variáveis:** `SUM_SERVICE_RECONCILER_`
- **Tabela do `config.toml`:** `[tool.sum.service.reconciler.<seção>]`
- **Comando:** `sum-service-reconciler` (entrypoint `sum_service.reconciler.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `SUM_SERVICE_RECONCILER_MESSAGING_URL`
- `SUM_SERVICE_RECONCILER_MESSAGING_USER`
- `SUM_SERVICE_RECONCILER_MESSAGING_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `SUM_SERVICE_RECONCILER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `SUM_SERVICE_RECONCILER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `messaging.url` | `SUM_SERVICE_RECONCILER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `SUM_SERVICE_RECONCILER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `SUM_SERVICE_RECONCILER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.consumer_inactive_threshold_seconds` | `SUM_SERVICE_RECONCILER_MESSAGING_CONSUMER_INACTIVE_THRESHOLD_SECONDS` | `--messaging.consumer_inactive_threshold_seconds` | `int` | `300` | Tempo sem uso após o qual o servidor remove o consumer da instância. |
| `health.port` | `SUM_SERVICE_RECONCILER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |
| `loop.observation_interval_seconds` | `SUM_SERVICE_RECONCILER_LOOP_OBSERVATION_INTERVAL_SECONDS` | `--loop.observation_interval_seconds` | `int` | `300` |  |
| `loop.observation_validity_seconds` | `SUM_SERVICE_RECONCILER_LOOP_OBSERVATION_VALIDITY_SECONDS` | `--loop.observation_validity_seconds` | `int` | `600` |  |
| `loop.action_deadline_seconds` | `SUM_SERVICE_RECONCILER_LOOP_ACTION_DEADLINE_SECONDS` | `--loop.action_deadline_seconds` | `int` | `120` |  |
| `loop.failure_limit` | `SUM_SERVICE_RECONCILER_LOOP_FAILURE_LIMIT` | `--loop.failure_limit` | `int` | `5` |  |
| `loop.failure_backoff_seconds` | `SUM_SERVICE_RECONCILER_LOOP_FAILURE_BACKOFF_SECONDS` | `--loop.failure_backoff_seconds` | `int` | `30` |  |
| `loop.failure_backoff_maximum_seconds` | `SUM_SERVICE_RECONCILER_LOOP_FAILURE_BACKOFF_MAXIMUM_SECONDS` | `--loop.failure_backoff_maximum_seconds` | `int` | `600` |  |
| `loop.reevaluation_interval_seconds` | `SUM_SERVICE_RECONCILER_LOOP_REEVALUATION_INTERVAL_SECONDS` | `--loop.reevaluation_interval_seconds` | `int` | `15` | Período da reavaliação periódica de todos os recursos (com jitter). |
| `loop.reevaluation_jitter` | `SUM_SERVICE_RECONCILER_LOOP_REEVALUATION_JITTER` | `--loop.reevaluation_jitter` | `float` | `0.2` |  |

**Definido no `config.toml` de dev:**

```toml
[tool.sum.service.reconciler.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/sum/service`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d sum-service-reconciler
docker compose logs -f sum-service-reconciler

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env sum-service-reconciler \
    --health.port 8004 \
    --messaging.url nats://localhost:4222 \
    --loop.failure_limit 3

# Lista todas as flags aceitas pelo papel
uv run sum-service-reconciler --help
```

## 7. `sum-service-observer`

Entrypoint do Observer de `sum.service` (`sum-service-observer`, decisões 0015 e 0033).

- **Prefixo das variáveis:** `SUM_SERVICE_OBSERVER_`
- **Tabela do `config.toml`:** `[tool.sum.service.observer.<seção>]`
- **Comando:** `sum-service-observer` (entrypoint `sum_service.observer.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `SUM_SERVICE_OBSERVER_MESSAGING_URL`
- `SUM_SERVICE_OBSERVER_MESSAGING_USER`
- `SUM_SERVICE_OBSERVER_MESSAGING_PASSWORD`
- `SUM_SERVICE_OBSERVER_IDENTITY_REGISTER_ORGANIZATION_ID`
- `SUM_SERVICE_OBSERVER_IDENTITY_PROJECT_IDS`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `SUM_SERVICE_OBSERVER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `SUM_SERVICE_OBSERVER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `identity.base_url` | `SUM_SERVICE_OBSERVER_IDENTITY_BASE_URL` | `--identity.base_url` | `str` | `'http://localhost:8080'` | Endereço da API do Zitadel na rede interna (não passa pelo gateway público). |
| `identity.host_header` | `SUM_SERVICE_OBSERVER_IDENTITY_HOST_HEADER` | `--identity.host_header` | `str` | `'localhost:8080'` | `Host` enviado ao Zitadel: ele resolve a instância pelo domínio externo. |
| `identity.issuer` | `SUM_SERVICE_OBSERVER_IDENTITY_ISSUER` | `--identity.issuer` | `str` | `'http://localhost:8080'` | Audience da assertion JWT da conta de serviço. |
| `identity.key_file` | `SUM_SERVICE_OBSERVER_IDENTITY_KEY_FILE` | `--identity.key_file` | `str` | `'/run/secrets/zitadel-key.json'` | Chave JSON da conta de serviço do papel (montada só no contêiner dele). |
| `identity.timeout_seconds` | `SUM_SERVICE_OBSERVER_IDENTITY_TIMEOUT_SECONDS` | `--identity.timeout_seconds` | `float` | `5.0` |  |
| `identity.register_organization_id` | `SUM_SERVICE_OBSERVER_IDENTITY_REGISTER_ORGANIZATION_ID` | `--identity.register_organization_id` | `str \| None` | — | Obrigatória. |
| `identity.project_ids` | `SUM_SERVICE_OBSERVER_IDENTITY_PROJECT_IDS` | `--identity.project_ids` | `dict[str, str]` | `{}` | Obrigatória. Módulo → projeto de roles que o Observer lê (decisão 0032). |
| `messaging.url` | `SUM_SERVICE_OBSERVER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `SUM_SERVICE_OBSERVER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `SUM_SERVICE_OBSERVER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.consumer_inactive_threshold_seconds` | `SUM_SERVICE_OBSERVER_MESSAGING_CONSUMER_INACTIVE_THRESHOLD_SECONDS` | `--messaging.consumer_inactive_threshold_seconds` | `int` | `300` | Tempo sem uso após o qual o servidor remove o consumer da instância. |
| `health.port` | `SUM_SERVICE_OBSERVER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |
| `loop.observation_interval_seconds` | `SUM_SERVICE_OBSERVER_LOOP_OBSERVATION_INTERVAL_SECONDS` | `--loop.observation_interval_seconds` | `int` | `300` | Intervalo da observação periódica (`observationInterval` do `desired`). |
| `loop.observation_jitter` | `SUM_SERVICE_OBSERVER_LOOP_OBSERVATION_JITTER` | `--loop.observation_jitter` | `float` | `0.2` | Fração de variação do intervalo, para as instâncias não observarem todas ao mesmo tempo. |
| `partition.index` | `SUM_SERVICE_OBSERVER_PARTITION_INDEX` | `--partition.index` | `int` | `0` |  |
| `partition.count` | `SUM_SERVICE_OBSERVER_PARTITION_COUNT` | `--partition.count` | `int` | `1` | Partição por `resourceId`: a instância observa só `hash mod count == index`. |

**Definido no `config.toml` de dev:**

```toml
[tool.sum.service.observer.identity]
base_url = "http://identity.smarkee.internal:8080"
host_header = "ipm-dev.smarkee.com.br:8080"
issuer = "http://ipm-dev.smarkee.com.br:8080"

[tool.sum.service.observer.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/sum/service`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d sum-service-observer
docker compose logs -f sum-service-observer

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env sum-service-observer \
    --health.port 8005 \
    --messaging.url nats://localhost:4222 \
    --identity.base_url http://localhost:8080 \
    --loop.observation_interval_seconds 60

# Lista todas as flags aceitas pelo papel
uv run sum-service-observer --help
```

## 8. `sum-service-executor`

Entrypoint do Executor de `sum.service` (`sum-service-executor`, decisões 0015, 0032 e 0033).

- **Prefixo das variáveis:** `SUM_SERVICE_EXECUTOR_`
- **Tabela do `config.toml`:** `[tool.sum.service.executor.<seção>]`
- **Comando:** `sum-service-executor` (entrypoint `sum_service.executor.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `SUM_SERVICE_EXECUTOR_MESSAGING_URL`
- `SUM_SERVICE_EXECUTOR_MESSAGING_USER`
- `SUM_SERVICE_EXECUTOR_MESSAGING_PASSWORD`
- `SUM_SERVICE_EXECUTOR_IDENTITY_REGISTER_ORGANIZATION_ID`
- `SUM_SERVICE_EXECUTOR_IDENTITY_PROJECT_IDS`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `SUM_SERVICE_EXECUTOR_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `SUM_SERVICE_EXECUTOR_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `messaging.url` | `SUM_SERVICE_EXECUTOR_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `SUM_SERVICE_EXECUTOR_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `SUM_SERVICE_EXECUTOR_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `identity.base_url` | `SUM_SERVICE_EXECUTOR_IDENTITY_BASE_URL` | `--identity.base_url` | `str` | `'http://localhost:8080'` | Endereço da API do Zitadel na rede interna (não passa pelo gateway público). |
| `identity.host_header` | `SUM_SERVICE_EXECUTOR_IDENTITY_HOST_HEADER` | `--identity.host_header` | `str` | `'localhost:8080'` | `Host` enviado ao Zitadel: ele resolve a instância pelo domínio externo. |
| `identity.issuer` | `SUM_SERVICE_EXECUTOR_IDENTITY_ISSUER` | `--identity.issuer` | `str` | `'http://localhost:8080'` | Audience da assertion JWT da conta de serviço. |
| `identity.key_file` | `SUM_SERVICE_EXECUTOR_IDENTITY_KEY_FILE` | `--identity.key_file` | `str` | `'/run/secrets/zitadel-key.json'` | Chave JSON da conta de serviço do papel (montada só no contêiner dele). |
| `identity.timeout_seconds` | `SUM_SERVICE_EXECUTOR_IDENTITY_TIMEOUT_SECONDS` | `--identity.timeout_seconds` | `float` | `10.0` |  |
| `identity.register_organization_id` | `SUM_SERVICE_EXECUTOR_IDENTITY_REGISTER_ORGANIZATION_ID` | `--identity.register_organization_id` | `str \| None` | — | Obrigatória. |
| `identity.project_ids` | `SUM_SERVICE_EXECUTOR_IDENTITY_PROJECT_IDS` | `--identity.project_ids` | `dict[str, str]` | `{}` | Obrigatória. Módulo → projeto de roles que o Executor pode conceder (decisão 0032). Hoje só `ipm`. |
| `partition.count` | `SUM_SERVICE_EXECUTOR_PARTITION_COUNT` | `--partition.count` | `int` | `4` | Partições do Stream `ACTION` (bootstrap do messaging): um consumer e um laço por partição. |
| `health.port` | `SUM_SERVICE_EXECUTOR_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.sum.service.executor.identity]
base_url = "http://identity.smarkee.internal:8080"
host_header = "ipm-dev.smarkee.com.br:8080"
issuer = "http://ipm-dev.smarkee.com.br:8080"

[tool.sum.service.executor.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/sum/service`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d sum-service-executor
docker compose logs -f sum-service-executor

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env sum-service-executor \
    --health.port 8006 \
    --messaging.url nats://localhost:4222 \
    --identity.base_url http://localhost:8080 \
    --partition.count 4

# Lista todas as flags aceitas pelo papel
uv run sum-service-executor --help
```
