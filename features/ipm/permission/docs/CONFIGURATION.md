<!-- Gerado por templates/feature/configuration_guide.py a partir dos settings.py dos papéis. Não edite: altere o código e regenere. -->
# Configuração de ipm.permission: guia de parâmetros

Referência de **todas** as configurações dos papéis de `ipm.permission` (`ipm-permission-<papel>`), na ordem de precedência, e de como executar cada um. Decisões: [`0067`](../../../../.decisions/0067-configuracao-por-papel-com-config-toml-e-segredos-em-arquivo.md) (configuração), [`0069`](../../../../.decisions/0069-prefixo-smarkee-nas-variaveis-de-infraestrutura.md) (prefixo) e [`0070`](../../../../.decisions/0070-senhas-dos-servicos-como-arquivos-montados.md) (senhas como arquivos).

> Gerado dos `settings.py` de `src/ipm_permission/<papel>/` e de `common/settings.py`. Para atualizar: `cd features/ipm/permission && uv run python ../../../templates/feature/configuration_guide.py`.

## 1. Precedência

Cada campo é resolvido pela **primeira** fonte que o informa, da maior para a menor prioridade:

| # | Fonte | Como informar | Observações |
|---|---|---|---|
| 1 | **Linha de comando** | `--<seção>.<campo> <valor>` | Só no entrypoint do papel. **Segredo é recusado** (aparece em `ps`): qualquer argumento que cite `password` encerra o serviço. |
| 2 | **Variável de ambiente** | `IPM_PERMISSION_<PAPEL>_<SEÇÃO>_<CAMPO>` | Em dev vem do `.env` (`docker compose` ou `uv run --env-file .env`). |
| 3 | **`config.toml`** | tabela `[tool.ipm.permission.<papel>.<seção>]` | Caminho em `SMARKEE_CONFIG_PATH` (padrão `config.toml`). Arquivo ou tabela ausente equivale a vazio. **Nunca tem segredo.** |
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
| Linha de comando | O `command` é só o nome do papel (`[ipm-permission-receiver]`), sem argumentos. |
| Ambiente | `environment:` repassa do `.env` só o que não é senha (por exemplo, audiência e IDs do Zitadel). |
| `config.toml` | Montado em `/etc/smarkee/config.toml` (`SMARKEE_CONFIG_PATH`). Endereços usam os nomes da rede Docker (`database.smarkee.internal`, `messaging.smarkee.internal`). |
| Arquivo de segredo | Bloco `secrets:` com `environment: <VARIÁVEL>`: cada papel monta só as suas senhas. |

Fora do Docker, os nomes `*.smarkee.internal` não resolvem: use as portas publicadas em `127.0.0.1` (Postgres `5432`, NATS `4222`) por flag ou variável.

## 3. `ipm-permission-receiver`

Entrypoint do Receiver de Permission (`ipm-permission-receiver`, decisões 0015 e 0083).

- **Prefixo das variáveis:** `IPM_PERMISSION_RECEIVER_`
- **Tabela do `config.toml`:** `[tool.ipm.permission.receiver.<seção>]`
- **Comando:** `ipm-permission-receiver` (entrypoint `ipm_permission.receiver.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_PERMISSION_RECEIVER_DATABASE_PASSWORD`
- `IPM_PERMISSION_RECEIVER_MESSAGING_URL`
- `IPM_PERMISSION_RECEIVER_MESSAGING_USER`
- `IPM_PERMISSION_RECEIVER_MESSAGING_PASSWORD`
- `IPM_PERMISSION_RECEIVER_AUTH_AUDIENCE`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_PERMISSION_RECEIVER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_PERMISSION_RECEIVER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `IPM_PERMISSION_RECEIVER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `IPM_PERMISSION_RECEIVER_DATABASE_PORT` | `--database.port` | `int \| None` | — |  |
| `database.name` | `IPM_PERMISSION_RECEIVER_DATABASE_NAME` | `--database.name` | `str \| None` | — |  |
| `database.user` | `IPM_PERMISSION_RECEIVER_DATABASE_USER` | `--database.user` | `str \| None` | — | Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `IPM_PERMISSION_RECEIVER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `IPM_PERMISSION_RECEIVER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_PERMISSION_RECEIVER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_PERMISSION_RECEIVER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `auth.issuer` | `IPM_PERMISSION_RECEIVER_AUTH_ISSUER` | `--auth.issuer` | `str` | `'http://localhost:8080'` | Valor esperado de `iss`: o endereço público do provedor de identidade. |
| `auth.jwks_url` | `IPM_PERMISSION_RECEIVER_AUTH_JWKS_URL` | `--auth.jwks_url` | `str` | `'http://localhost:8000/oauth/v2/keys'` | Endereço (da rede interna) em que as chaves públicas são buscadas. |
| `auth.host_header` | `IPM_PERMISSION_RECEIVER_AUTH_HOST_HEADER` | `--auth.host_header` | `str` | `'localhost:8080'` | `Host` enviado ao provedor nas chamadas internas: ele resolve a instância por esse valor. |
| `auth.audience` | `IPM_PERMISSION_RECEIVER_AUTH_AUDIENCE` | `--auth.audience` | `str \| None` | — | Obrigatória. ID do projeto `roles-ipm` (organização `core` do Zitadel): obrigatório, sem default. |
| `auth.jwks_cache_seconds` | `IPM_PERMISSION_RECEIVER_AUTH_JWKS_CACHE_SECONDS` | `--auth.jwks_cache_seconds` | `int` | `300` |  |
| `api.host` | `IPM_PERMISSION_RECEIVER_API_HOST` | `--api.host` | `str` | `'0.0.0.0'` |  |
| `api.port` | `IPM_PERMISSION_RECEIVER_API_PORT` | `--api.port` | `int` | `8000` |  |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.permission.receiver.auth]
host_header = "ipm-dev.smarkee.com.br:8080"
issuer = "http://ipm-dev.smarkee.com.br:8080"
jwks_url = "http://gateway.smarkee.internal:8000/oauth/v2/keys"

[tool.ipm.permission.receiver.database]
host = "database.smarkee.internal"
name = "ssot"
port = 5432
user = "ipm_permission_receiver_login"

[tool.ipm.permission.receiver.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/ipm/permission`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-permission-receiver
docker compose logs -f ipm-permission-receiver

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-permission-receiver \
    --api.port 8001 \
    --database.host localhost \
    --messaging.url nats://localhost:4222

# Lista todas as flags aceitas pelo papel
uv run ipm-permission-receiver --help
```

## 4. `ipm-permission-manager`

Entrypoint do Manager de Permission (`ipm-permission-manager`, decisões 0015, 0019, 0063 e 0083).

- **Prefixo das variáveis:** `IPM_PERMISSION_MANAGER_`
- **Tabela do `config.toml`:** `[tool.ipm.permission.manager.<seção>]`
- **Comando:** `ipm-permission-manager` (entrypoint `ipm_permission.manager.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_PERMISSION_MANAGER_DATABASE_PASSWORD`
- `IPM_PERMISSION_MANAGER_MESSAGING_URL`
- `IPM_PERMISSION_MANAGER_MESSAGING_USER`
- `IPM_PERMISSION_MANAGER_MESSAGING_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_PERMISSION_MANAGER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_PERMISSION_MANAGER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `IPM_PERMISSION_MANAGER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `IPM_PERMISSION_MANAGER_DATABASE_PORT` | `--database.port` | `int \| None` | — |  |
| `database.name` | `IPM_PERMISSION_MANAGER_DATABASE_NAME` | `--database.name` | `str \| None` | — |  |
| `database.user` | `IPM_PERMISSION_MANAGER_DATABASE_USER` | `--database.user` | `str \| None` | — | Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `IPM_PERMISSION_MANAGER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `IPM_PERMISSION_MANAGER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_PERMISSION_MANAGER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_PERMISSION_MANAGER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `loop.failure_limit` | `IPM_PERMISSION_MANAGER_LOOP_FAILURE_LIMIT` | `--loop.failure_limit` | `int` | `5` | Falhas por geração antes de `Failed` (`schemas/ipm/permission/desired`, `failureLimit`). |
| `loop.progress_deadline_seconds` | `IPM_PERMISSION_MANAGER_LOOP_PROGRESS_DEADLINE_SECONDS` | `--loop.progress_deadline_seconds` | `int` | `300` | Prazo para a geração convergir antes de `Failed` com `ProgressDeadlineExceeded` (`schemas/ipm/permission/desired`, `progressDeadline`; decisão 0078). |
| `health.port` | `IPM_PERMISSION_MANAGER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.permission.manager.database]
host = "database.smarkee.internal"
name = "ssot"
port = 5432
user = "ipm_permission_manager_login"

[tool.ipm.permission.manager.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/ipm/permission`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-permission-manager
docker compose logs -f ipm-permission-manager

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-permission-manager \
    --health.port 8002 \
    --database.host localhost \
    --messaging.url nats://localhost:4222 \
    --loop.failure_limit 3

# Lista todas as flags aceitas pelo papel
uv run ipm-permission-manager --help
```

## 5. `ipm-permission-publisher`

Entrypoint do Publisher de `ipm.permission` (decisões 0015 e 0033).

- **Prefixo das variáveis:** `IPM_PERMISSION_PUBLISHER_`
- **Tabela do `config.toml`:** `[tool.ipm.permission.publisher.<seção>]`
- **Comando:** `ipm-permission-publisher` (entrypoint `ipm_permission.publisher.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_PERMISSION_PUBLISHER_MESSAGING_URL`
- `IPM_PERMISSION_PUBLISHER_MESSAGING_USER`
- `IPM_PERMISSION_PUBLISHER_MESSAGING_PASSWORD`
- `IPM_PERMISSION_PUBLISHER_DATABASE_HOST`
- `IPM_PERMISSION_PUBLISHER_DATABASE_PORT`
- `IPM_PERMISSION_PUBLISHER_DATABASE_NAME`
- `IPM_PERMISSION_PUBLISHER_DATABASE_USER`
- `IPM_PERMISSION_PUBLISHER_DATABASE_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_PERMISSION_PUBLISHER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_PERMISSION_PUBLISHER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `IPM_PERMISSION_PUBLISHER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Obrigatória. Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `IPM_PERMISSION_PUBLISHER_DATABASE_PORT` | `--database.port` | `int \| None` | — | Obrigatória. |
| `database.name` | `IPM_PERMISSION_PUBLISHER_DATABASE_NAME` | `--database.name` | `str \| None` | — | Obrigatória. |
| `database.user` | `IPM_PERMISSION_PUBLISHER_DATABASE_USER` | `--database.user` | `str \| None` | — | Obrigatória. Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `IPM_PERMISSION_PUBLISHER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `IPM_PERMISSION_PUBLISHER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_PERMISSION_PUBLISHER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_PERMISSION_PUBLISHER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `health.port` | `IPM_PERMISSION_PUBLISHER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.permission.publisher.database]
host = "database.smarkee.internal"
name = "ssot"
port = 5432
user = "ipm_permission_publisher_login"

[tool.ipm.permission.publisher.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/ipm/permission`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-permission-publisher
docker compose logs -f ipm-permission-publisher

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-permission-publisher \
    --health.port 8003 \
    --database.host localhost \
    --messaging.url nats://localhost:4222

# Lista todas as flags aceitas pelo papel
uv run ipm-permission-publisher --help
```

## 6. `ipm-permission-reconciler`

Entrypoint do Reconciler de Permission (`ipm-permission-reconciler`, decisões 0015, 0063 e 0083).

- **Prefixo das variáveis:** `IPM_PERMISSION_RECONCILER_`
- **Tabela do `config.toml`:** `[tool.ipm.permission.reconciler.<seção>]`
- **Comando:** `ipm-permission-reconciler` (entrypoint `ipm_permission.reconciler.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_PERMISSION_RECONCILER_MESSAGING_URL`
- `IPM_PERMISSION_RECONCILER_MESSAGING_USER`
- `IPM_PERMISSION_RECONCILER_MESSAGING_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_PERMISSION_RECONCILER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_PERMISSION_RECONCILER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `messaging.url` | `IPM_PERMISSION_RECONCILER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_PERMISSION_RECONCILER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_PERMISSION_RECONCILER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.consumer_inactive_threshold_seconds` | `IPM_PERMISSION_RECONCILER_MESSAGING_CONSUMER_INACTIVE_THRESHOLD_SECONDS` | `--messaging.consumer_inactive_threshold_seconds` | `int` | `300` | Tempo sem uso após o qual o servidor remove o consumer da instância. |
| `loop.observation_validity_seconds` | `IPM_PERMISSION_RECONCILER_LOOP_OBSERVATION_VALIDITY_SECONDS` | `--loop.observation_validity_seconds` | `int` | `600` | `observationValidity` (PT10M): idade máxima de um `observed` para decidir. |
| `loop.action_deadline_seconds` | `IPM_PERMISSION_RECONCILER_LOOP_ACTION_DEADLINE_SECONDS` | `--loop.action_deadline_seconds` | `int` | `120` | `actionDeadline` (PT2M): prazo da `action` pendente e da espera pela observação causada. |
| `loop.reevaluation_interval_seconds` | `IPM_PERMISSION_RECONCILER_LOOP_REEVALUATION_INTERVAL_SECONDS` | `--loop.reevaluation_interval_seconds` | `int` | `30` | Período da reavaliação periódica de todos os recursos (com jitter). |
| `loop.reevaluation_jitter` | `IPM_PERMISSION_RECONCILER_LOOP_REEVALUATION_JITTER` | `--loop.reevaluation_jitter` | `float` | `0.2` | Fração de jitter (±20%) aplicada ao período de reavaliação (`LOOP.md` §25). |
| `loop.failure_backoff_seconds` | `IPM_PERMISSION_RECONCILER_LOOP_FAILURE_BACKOFF_SECONDS` | `--loop.failure_backoff_seconds` | `int` | `5` | `failureBackoff` (PT5S): espera inicial após uma `failed` antes de emitir nova `action`. |
| `loop.failure_backoff_maximum_seconds` | `IPM_PERMISSION_RECONCILER_LOOP_FAILURE_BACKOFF_MAXIMUM_SECONDS` | `--loop.failure_backoff_maximum_seconds` | `int` | `300` | `failureBackoffMaximum` (PT5M): teto do backoff exponencial entre `failed` seguidas. |
| `health.port` | `IPM_PERMISSION_RECONCILER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.permission.reconciler.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/ipm/permission`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-permission-reconciler
docker compose logs -f ipm-permission-reconciler

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-permission-reconciler \
    --health.port 8004 \
    --messaging.url nats://localhost:4222 \
    --loop.reevaluation_interval_seconds 10

# Lista todas as flags aceitas pelo papel
uv run ipm-permission-reconciler --help
```

## 7. `ipm-permission-observer`

Entrypoint do Observer de Permission (`ipm-permission-observer`, decisões 0015, 0063 e 0083).

- **Prefixo das variáveis:** `IPM_PERMISSION_OBSERVER_`
- **Tabela do `config.toml`:** `[tool.ipm.permission.observer.<seção>]`
- **Comando:** `ipm-permission-observer` (entrypoint `ipm_permission.observer.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_PERMISSION_OBSERVER_MESSAGING_URL`
- `IPM_PERMISSION_OBSERVER_MESSAGING_USER`
- `IPM_PERMISSION_OBSERVER_MESSAGING_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_PERMISSION_OBSERVER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_PERMISSION_OBSERVER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `messaging.url` | `IPM_PERMISSION_OBSERVER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_PERMISSION_OBSERVER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_PERMISSION_OBSERVER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.consumer_inactive_threshold_seconds` | `IPM_PERMISSION_OBSERVER_MESSAGING_CONSUMER_INACTIVE_THRESHOLD_SECONDS` | `--messaging.consumer_inactive_threshold_seconds` | `int` | `300` | Tempo sem uso após o qual o servidor remove o consumer da instância. |
| `identity.base_url` | `IPM_PERMISSION_OBSERVER_IDENTITY_BASE_URL` | `--identity.base_url` | `str` | `'http://localhost:8080'` | Endereço da API do Zitadel na rede interna (não passa pelo gateway público). |
| `identity.host_header` | `IPM_PERMISSION_OBSERVER_IDENTITY_HOST_HEADER` | `--identity.host_header` | `str` | `'localhost:8080'` | `Host` enviado ao Zitadel: ele resolve a instância pelo domínio externo. |
| `identity.issuer` | `IPM_PERMISSION_OBSERVER_IDENTITY_ISSUER` | `--identity.issuer` | `str` | `'http://localhost:8080'` | Audience da assertion JWT da conta de serviço. |
| `identity.key_file` | `IPM_PERMISSION_OBSERVER_IDENTITY_KEY_FILE` | `--identity.key_file` | `str` | `'/run/secrets/zitadel-key.json'` | Chave JSON da conta de serviço do papel (montada só no contêiner dele). |
| `identity.timeout_seconds` | `IPM_PERMISSION_OBSERVER_IDENTITY_TIMEOUT_SECONDS` | `--identity.timeout_seconds` | `float` | `5.0` |  |
| `partition.index` | `IPM_PERMISSION_OBSERVER_PARTITION_INDEX` | `--partition.index` | `int` | `0` |  |
| `partition.count` | `IPM_PERMISSION_OBSERVER_PARTITION_COUNT` | `--partition.count` | `int` | `1` | Partição por `resourceId`: a instância observa `hash(resourceId) mod count == index`. |
| `health.port` | `IPM_PERMISSION_OBSERVER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |
| `loop.observation_interval_seconds` | `IPM_PERMISSION_OBSERVER_LOOP_OBSERVATION_INTERVAL_SECONDS` | `--loop.observation_interval_seconds` | `int` | `300` | `observationInterval` de `schemas/ipm/permission/desired.v1.schema.json` (PT5M = 300 s). |
| `loop.observation_jitter` | `IPM_PERMISSION_OBSERVER_LOOP_OBSERVATION_JITTER` | `--loop.observation_jitter` | `float` | `0.2` | Fração de jitter (±20%) aplicada ao intervalo periódico (`docs/RESOURCE-CONTROL-LOOP.md`). |
| `loop.maximum_concurrent_reads` | `IPM_PERMISSION_OBSERVER_LOOP_MAXIMUM_CONCURRENT_READS` | `--loop.maximum_concurrent_reads` | `int` | `10` | Limite de leituras simultâneas ao Zitadel por instância, na observação periódica. |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.permission.observer.identity]
base_url = "http://identity.smarkee.internal:8080"
host_header = "ipm-dev.smarkee.com.br:8080"
issuer = "http://ipm-dev.smarkee.com.br:8080"

[tool.ipm.permission.observer.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/ipm/permission`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-permission-observer
docker compose logs -f ipm-permission-observer

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-permission-observer \
    --health.port 8005 \
    --messaging.url nats://localhost:4222 \
    --identity.base_url http://localhost:8080 \
    --loop.observation_interval_seconds 60

# Lista todas as flags aceitas pelo papel
uv run ipm-permission-observer --help
```

## 8. `ipm-permission-executor`

Entrypoint do Executor de Permission (`ipm-permission-executor`, decisões 0015, 0063 e 0083).

- **Prefixo das variáveis:** `IPM_PERMISSION_EXECUTOR_`
- **Tabela do `config.toml`:** `[tool.ipm.permission.executor.<seção>]`
- **Comando:** `ipm-permission-executor` (entrypoint `ipm_permission.executor.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_PERMISSION_EXECUTOR_MESSAGING_URL`
- `IPM_PERMISSION_EXECUTOR_MESSAGING_USER`
- `IPM_PERMISSION_EXECUTOR_MESSAGING_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_PERMISSION_EXECUTOR_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_PERMISSION_EXECUTOR_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `messaging.url` | `IPM_PERMISSION_EXECUTOR_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_PERMISSION_EXECUTOR_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_PERMISSION_EXECUTOR_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `identity.base_url` | `IPM_PERMISSION_EXECUTOR_IDENTITY_BASE_URL` | `--identity.base_url` | `str` | `'http://localhost:8080'` | Endereço da API do Zitadel na rede interna (não passa pelo gateway público). |
| `identity.host_header` | `IPM_PERMISSION_EXECUTOR_IDENTITY_HOST_HEADER` | `--identity.host_header` | `str` | `'localhost:8080'` | `Host` enviado ao Zitadel: ele resolve a instância pelo domínio externo. |
| `identity.issuer` | `IPM_PERMISSION_EXECUTOR_IDENTITY_ISSUER` | `--identity.issuer` | `str` | `'http://localhost:8080'` | Audience da assertion JWT da conta de serviço. |
| `identity.key_file` | `IPM_PERMISSION_EXECUTOR_IDENTITY_KEY_FILE` | `--identity.key_file` | `str` | `'/run/secrets/zitadel-key.json'` | Chave JSON da conta de serviço do papel (montada só no contêiner dele). |
| `identity.timeout_seconds` | `IPM_PERMISSION_EXECUTOR_IDENTITY_TIMEOUT_SECONDS` | `--identity.timeout_seconds` | `float` | `5.0` |  |
| `partition.count` | `IPM_PERMISSION_EXECUTOR_PARTITION_COUNT` | `--partition.count` | `int` | `4` | Partições do Stream `ACTION` (`bootstrap/action.json`, decisão 0018). |
| `health.port` | `IPM_PERMISSION_EXECUTOR_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.permission.executor.identity]
base_url = "http://identity.smarkee.internal:8080"
host_header = "ipm-dev.smarkee.com.br:8080"
issuer = "http://ipm-dev.smarkee.com.br:8080"

[tool.ipm.permission.executor.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/ipm/permission`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-permission-executor
docker compose logs -f ipm-permission-executor

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-permission-executor \
    --health.port 8006 \
    --messaging.url nats://localhost:4222 \
    --identity.base_url http://localhost:8080 \
    --partition.count 4

# Lista todas as flags aceitas pelo papel
uv run ipm-permission-executor --help
```
