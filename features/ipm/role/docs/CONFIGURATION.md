<!-- Gerado por templates/feature/configuration_guide.py a partir dos settings.py dos papéis. Não edite: altere o código e regenere. -->
# Configuração de ipm.role: guia de parâmetros

Referência de **todas** as configurações dos papéis de `ipm.role` (`ipm-role-<papel>`), na ordem de precedência, e de como executar cada um. Decisões: [`0067`](../../../../.decisions/0067-configuracao-por-papel-com-config-toml-e-segredos-em-arquivo.md) (configuração), [`0069`](../../../../.decisions/0069-prefixo-smarkee-nas-variaveis-de-infraestrutura.md) (prefixo) e [`0070`](../../../../.decisions/0070-senhas-dos-servicos-como-arquivos-montados.md) (senhas como arquivos).

> Gerado dos `settings.py` de `src/ipm_role/<papel>/` e de `common/settings.py`. Para atualizar: `cd features/ipm/role && uv run python ../../../templates/feature/configuration_guide.py`.

## 1. Precedência

Cada campo é resolvido pela **primeira** fonte que o informa, da maior para a menor prioridade:

| # | Fonte | Como informar | Observações |
|---|---|---|---|
| 1 | **Linha de comando** | `--<seção>.<campo> <valor>` | Só no entrypoint do papel. **Segredo é recusado** (aparece em `ps`): qualquer argumento que cite `password` encerra o serviço. |
| 2 | **Variável de ambiente** | `IPM_ROLE_<PAPEL>_<SEÇÃO>_<CAMPO>` | Em dev vem do `.env` (`docker compose` ou `uv run --env-file .env`). |
| 3 | **`config.toml`** | tabela `[tool.ipm.role.<papel>.<seção>]` | Caminho em `SMARKEE_CONFIG_PATH` (padrão `config.toml`). Arquivo ou tabela ausente equivale a vazio. **Nunca tem segredo.** |
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
| Linha de comando | O `command` é só o nome do papel (`[ipm-role-receiver]`), sem argumentos. |
| Ambiente | `environment:` repassa do `.env` só o que não é senha (por exemplo, audiência e IDs do Zitadel). |
| `config.toml` | Montado em `/etc/smarkee/config.toml` (`SMARKEE_CONFIG_PATH`). Endereços usam os nomes da rede Docker (`database.smarkee.internal`, `messaging.smarkee.internal`). |
| Arquivo de segredo | Bloco `secrets:` com `environment: <VARIÁVEL>`: cada papel monta só as suas senhas. |

Fora do Docker, os nomes `*.smarkee.internal` não resolvem: use as portas publicadas em `127.0.0.1` (Postgres `5432`, NATS `4222`) por flag ou variável.

## 3. `ipm-role-receiver`

Entrypoint do Receiver de Role (`ipm-role-receiver`, decisões 0015 e 0083).

- **Prefixo das variáveis:** `IPM_ROLE_RECEIVER_`
- **Tabela do `config.toml`:** `[tool.ipm.role.receiver.<seção>]`
- **Comando:** `ipm-role-receiver` (entrypoint `ipm_role.receiver.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_ROLE_RECEIVER_DATABASE_PASSWORD`
- `IPM_ROLE_RECEIVER_MESSAGING_URL`
- `IPM_ROLE_RECEIVER_MESSAGING_USER`
- `IPM_ROLE_RECEIVER_MESSAGING_PASSWORD`
- `IPM_ROLE_RECEIVER_AUTH_AUDIENCE`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_ROLE_RECEIVER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_ROLE_RECEIVER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `IPM_ROLE_RECEIVER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `IPM_ROLE_RECEIVER_DATABASE_PORT` | `--database.port` | `int \| None` | — |  |
| `database.name` | `IPM_ROLE_RECEIVER_DATABASE_NAME` | `--database.name` | `str \| None` | — |  |
| `database.user` | `IPM_ROLE_RECEIVER_DATABASE_USER` | `--database.user` | `str \| None` | — | Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `IPM_ROLE_RECEIVER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `IPM_ROLE_RECEIVER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_ROLE_RECEIVER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_ROLE_RECEIVER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `auth.issuer` | `IPM_ROLE_RECEIVER_AUTH_ISSUER` | `--auth.issuer` | `str` | `'http://localhost:8080'` | Valor esperado de `iss`: o endereço público do provedor de identidade. |
| `auth.jwks_url` | `IPM_ROLE_RECEIVER_AUTH_JWKS_URL` | `--auth.jwks_url` | `str` | `'http://localhost:8000/oauth/v2/keys'` | Endereço (da rede interna) em que as chaves públicas são buscadas. |
| `auth.host_header` | `IPM_ROLE_RECEIVER_AUTH_HOST_HEADER` | `--auth.host_header` | `str` | `'localhost:8080'` | `Host` enviado ao provedor nas chamadas internas: ele resolve a instância por esse valor. |
| `auth.audience` | `IPM_ROLE_RECEIVER_AUTH_AUDIENCE` | `--auth.audience` | `str \| None` | — | Obrigatória. ID do projeto `roles-ipm` (organização `core` do Zitadel): obrigatório, sem default. |
| `auth.jwks_cache_seconds` | `IPM_ROLE_RECEIVER_AUTH_JWKS_CACHE_SECONDS` | `--auth.jwks_cache_seconds` | `int` | `300` |  |
| `api.host` | `IPM_ROLE_RECEIVER_API_HOST` | `--api.host` | `str` | `'0.0.0.0'` |  |
| `api.port` | `IPM_ROLE_RECEIVER_API_PORT` | `--api.port` | `int` | `8000` |  |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.role.receiver.auth]
host_header = "ipm-dev.smarkee.com.br:8080"
issuer = "http://ipm-dev.smarkee.com.br:8080"
jwks_url = "http://gateway.smarkee.internal:8000/oauth/v2/keys"

[tool.ipm.role.receiver.database]
host = "database.smarkee.internal"
name = "smarkee"
port = 5432
user = "ipm_role_receiver_login"

[tool.ipm.role.receiver.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/ipm/role`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-role-receiver
docker compose logs -f ipm-role-receiver

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-role-receiver \
    --api.port 8001 \
    --database.host localhost \
    --messaging.url nats://localhost:4222

# Lista todas as flags aceitas pelo papel
uv run ipm-role-receiver --help
```

## 4. `ipm-role-manager`

Entrypoint do Manager de Role (`ipm-role-manager`, decisões 0015, 0019, 0063 e 0083).

- **Prefixo das variáveis:** `IPM_ROLE_MANAGER_`
- **Tabela do `config.toml`:** `[tool.ipm.role.manager.<seção>]`
- **Comando:** `ipm-role-manager` (entrypoint `ipm_role.manager.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_ROLE_MANAGER_DATABASE_PASSWORD`
- `IPM_ROLE_MANAGER_MESSAGING_URL`
- `IPM_ROLE_MANAGER_MESSAGING_USER`
- `IPM_ROLE_MANAGER_MESSAGING_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_ROLE_MANAGER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_ROLE_MANAGER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `IPM_ROLE_MANAGER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `IPM_ROLE_MANAGER_DATABASE_PORT` | `--database.port` | `int \| None` | — |  |
| `database.name` | `IPM_ROLE_MANAGER_DATABASE_NAME` | `--database.name` | `str \| None` | — |  |
| `database.user` | `IPM_ROLE_MANAGER_DATABASE_USER` | `--database.user` | `str \| None` | — | Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `IPM_ROLE_MANAGER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `IPM_ROLE_MANAGER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_ROLE_MANAGER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_ROLE_MANAGER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `loop.failure_limit` | `IPM_ROLE_MANAGER_LOOP_FAILURE_LIMIT` | `--loop.failure_limit` | `int` | `5` | Falhas por geração antes de `Failed` (`schemas/ipm/role/desired`, `failureLimit`). |
| `loop.progress_deadline_seconds` | `IPM_ROLE_MANAGER_LOOP_PROGRESS_DEADLINE_SECONDS` | `--loop.progress_deadline_seconds` | `int` | `300` | Prazo para a geração convergir antes de `Failed` com `ProgressDeadlineExceeded` (`schemas/ipm/role/desired`, `progressDeadline`; decisão 0078). |
| `health.port` | `IPM_ROLE_MANAGER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.role.manager.database]
host = "database.smarkee.internal"
name = "smarkee"
port = 5432
user = "ipm_role_manager_login"

[tool.ipm.role.manager.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/ipm/role`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-role-manager
docker compose logs -f ipm-role-manager

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-role-manager \
    --health.port 8002 \
    --database.host localhost \
    --messaging.url nats://localhost:4222 \
    --loop.failure_limit 3

# Lista todas as flags aceitas pelo papel
uv run ipm-role-manager --help
```

## 5. `ipm-role-publisher`

Entrypoint do Publisher de `ipm.role` (decisões 0015 e 0033).

- **Prefixo das variáveis:** `IPM_ROLE_PUBLISHER_`
- **Tabela do `config.toml`:** `[tool.ipm.role.publisher.<seção>]`
- **Comando:** `ipm-role-publisher` (entrypoint `ipm_role.publisher.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_ROLE_PUBLISHER_MESSAGING_URL`
- `IPM_ROLE_PUBLISHER_MESSAGING_USER`
- `IPM_ROLE_PUBLISHER_MESSAGING_PASSWORD`
- `IPM_ROLE_PUBLISHER_DATABASE_HOST`
- `IPM_ROLE_PUBLISHER_DATABASE_PORT`
- `IPM_ROLE_PUBLISHER_DATABASE_NAME`
- `IPM_ROLE_PUBLISHER_DATABASE_USER`
- `IPM_ROLE_PUBLISHER_DATABASE_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_ROLE_PUBLISHER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_ROLE_PUBLISHER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `IPM_ROLE_PUBLISHER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Obrigatória. Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `IPM_ROLE_PUBLISHER_DATABASE_PORT` | `--database.port` | `int \| None` | — | Obrigatória. |
| `database.name` | `IPM_ROLE_PUBLISHER_DATABASE_NAME` | `--database.name` | `str \| None` | — | Obrigatória. |
| `database.user` | `IPM_ROLE_PUBLISHER_DATABASE_USER` | `--database.user` | `str \| None` | — | Obrigatória. Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `IPM_ROLE_PUBLISHER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `IPM_ROLE_PUBLISHER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_ROLE_PUBLISHER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_ROLE_PUBLISHER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `health.port` | `IPM_ROLE_PUBLISHER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.role.publisher.database]
host = "database.smarkee.internal"
name = "smarkee"
port = 5432
user = "ipm_role_publisher_login"

[tool.ipm.role.publisher.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/ipm/role`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-role-publisher
docker compose logs -f ipm-role-publisher

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-role-publisher \
    --health.port 8003 \
    --database.host localhost \
    --messaging.url nats://localhost:4222

# Lista todas as flags aceitas pelo papel
uv run ipm-role-publisher --help
```

## 6. `ipm-role-reconciler`

Entrypoint do Reconciler de Role (`ipm-role-reconciler`, decisões 0015, 0063 e 0083).

- **Prefixo das variáveis:** `IPM_ROLE_RECONCILER_`
- **Tabela do `config.toml`:** `[tool.ipm.role.reconciler.<seção>]`
- **Comando:** `ipm-role-reconciler` (entrypoint `ipm_role.reconciler.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_ROLE_RECONCILER_MESSAGING_URL`
- `IPM_ROLE_RECONCILER_MESSAGING_USER`
- `IPM_ROLE_RECONCILER_MESSAGING_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_ROLE_RECONCILER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_ROLE_RECONCILER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `messaging.url` | `IPM_ROLE_RECONCILER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_ROLE_RECONCILER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_ROLE_RECONCILER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.consumer_inactive_threshold_seconds` | `IPM_ROLE_RECONCILER_MESSAGING_CONSUMER_INACTIVE_THRESHOLD_SECONDS` | `--messaging.consumer_inactive_threshold_seconds` | `int` | `300` | Tempo sem uso após o qual o servidor remove o consumer da instância. |
| `loop.observation_validity_seconds` | `IPM_ROLE_RECONCILER_LOOP_OBSERVATION_VALIDITY_SECONDS` | `--loop.observation_validity_seconds` | `int` | `600` | `observationValidity` (PT10M): idade máxima de um `observed` para decidir. |
| `loop.action_deadline_seconds` | `IPM_ROLE_RECONCILER_LOOP_ACTION_DEADLINE_SECONDS` | `--loop.action_deadline_seconds` | `int` | `120` | `actionDeadline` (PT2M): prazo da `action` pendente e da espera pela observação causada. |
| `loop.reevaluation_interval_seconds` | `IPM_ROLE_RECONCILER_LOOP_REEVALUATION_INTERVAL_SECONDS` | `--loop.reevaluation_interval_seconds` | `int` | `30` | Período da reavaliação periódica de todos os recursos (com jitter). |
| `loop.reevaluation_jitter` | `IPM_ROLE_RECONCILER_LOOP_REEVALUATION_JITTER` | `--loop.reevaluation_jitter` | `float` | `0.2` |  |
| `loop.failure_backoff_seconds` | `IPM_ROLE_RECONCILER_LOOP_FAILURE_BACKOFF_SECONDS` | `--loop.failure_backoff_seconds` | `int` | `5` | Atraso após o primeiro `failed`; dobra a cada falha seguida, até o máximo. |
| `loop.failure_backoff_maximum_seconds` | `IPM_ROLE_RECONCILER_LOOP_FAILURE_BACKOFF_MAXIMUM_SECONDS` | `--loop.failure_backoff_maximum_seconds` | `int` | `300` |  |
| `health.port` | `IPM_ROLE_RECONCILER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.role.reconciler.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/ipm/role`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-role-reconciler
docker compose logs -f ipm-role-reconciler

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-role-reconciler \
    --health.port 8004 \
    --messaging.url nats://localhost:4222 \
    --loop.reevaluation_interval_seconds 10

# Lista todas as flags aceitas pelo papel
uv run ipm-role-reconciler --help
```

## 7. `ipm-role-observer`

Entrypoint do Observer de Role (`ipm-role-observer`, decisões 0015, 0063 e 0083).

- **Prefixo das variáveis:** `IPM_ROLE_OBSERVER_`
- **Tabela do `config.toml`:** `[tool.ipm.role.observer.<seção>]`
- **Comando:** `ipm-role-observer` (entrypoint `ipm_role.observer.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_ROLE_OBSERVER_MESSAGING_URL`
- `IPM_ROLE_OBSERVER_MESSAGING_USER`
- `IPM_ROLE_OBSERVER_MESSAGING_PASSWORD`
- `IPM_ROLE_OBSERVER_STORAGE_DIRECTORY`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_ROLE_OBSERVER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_ROLE_OBSERVER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `messaging.url` | `IPM_ROLE_OBSERVER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_ROLE_OBSERVER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_ROLE_OBSERVER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.consumer_inactive_threshold_seconds` | `IPM_ROLE_OBSERVER_MESSAGING_CONSUMER_INACTIVE_THRESHOLD_SECONDS` | `--messaging.consumer_inactive_threshold_seconds` | `int` | `300` | Tempo sem uso após o qual o servidor remove o consumer da instância. |
| `storage.directory` | `IPM_ROLE_OBSERVER_STORAGE_DIRECTORY` | `--storage.directory` | `str \| None` | — | Obrigatória. Diretório dos arquivos de estado da Role (somente leitura no Observer). |
| `partition.index` | `IPM_ROLE_OBSERVER_PARTITION_INDEX` | `--partition.index` | `int` | `0` |  |
| `partition.count` | `IPM_ROLE_OBSERVER_PARTITION_COUNT` | `--partition.count` | `int` | `1` | Partição por `resourceId`: a instância observa só `hash mod count == index`. |
| `health.port` | `IPM_ROLE_OBSERVER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |
| `loop.observation_interval_seconds` | `IPM_ROLE_OBSERVER_LOOP_OBSERVATION_INTERVAL_SECONDS` | `--loop.observation_interval_seconds` | `int` | `300` | `observationInterval` (PT5M) de `schemas/ipm/role/desired`. |
| `loop.observation_jitter` | `IPM_ROLE_OBSERVER_LOOP_OBSERVATION_JITTER` | `--loop.observation_jitter` | `float` | `0.2` |  |
| `loop.maximum_concurrent_reads` | `IPM_ROLE_OBSERVER_LOOP_MAXIMUM_CONCURRENT_READS` | `--loop.maximum_concurrent_reads` | `int` | `4` | Leituras simultâneas no armazenamento de estado. |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.role.observer.storage]
directory = "/var/tmp/ipm-role"

[tool.ipm.role.observer.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/ipm/role`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-role-observer
docker compose logs -f ipm-role-observer

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-role-observer \
    --health.port 8005 \
    --messaging.url nats://localhost:4222 \
    --loop.observation_interval_seconds 60

# Lista todas as flags aceitas pelo papel
uv run ipm-role-observer --help
```

## 8. `ipm-role-executor`

Entrypoint do Executor de Role (`ipm-role-executor`, decisões 0015, 0063 e 0083).

- **Prefixo das variáveis:** `IPM_ROLE_EXECUTOR_`
- **Tabela do `config.toml`:** `[tool.ipm.role.executor.<seção>]`
- **Comando:** `ipm-role-executor` (entrypoint `ipm_role.executor.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_ROLE_EXECUTOR_MESSAGING_URL`
- `IPM_ROLE_EXECUTOR_MESSAGING_USER`
- `IPM_ROLE_EXECUTOR_MESSAGING_PASSWORD`
- `IPM_ROLE_EXECUTOR_STORAGE_DIRECTORY`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_ROLE_EXECUTOR_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_ROLE_EXECUTOR_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `messaging.url` | `IPM_ROLE_EXECUTOR_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_ROLE_EXECUTOR_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_ROLE_EXECUTOR_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `storage.directory` | `IPM_ROLE_EXECUTOR_STORAGE_DIRECTORY` | `--storage.directory` | `str \| None` | — | Obrigatória. Diretório dos arquivos de estado da Role. |
| `partition.count` | `IPM_ROLE_EXECUTOR_PARTITION_COUNT` | `--partition.count` | `int` | `4` | Partições do Stream `ACTION` (bootstrap do messaging): um consumer e um laço por partição. |
| `health.port` | `IPM_ROLE_EXECUTOR_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.role.executor.storage]
directory = "/var/tmp/ipm-role"

[tool.ipm.role.executor.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/ipm/role`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-role-executor
docker compose logs -f ipm-role-executor

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-role-executor \
    --health.port 8006 \
    --messaging.url nats://localhost:4222 \
    --partition.count 4

# Lista todas as flags aceitas pelo papel
uv run ipm-role-executor --help
```
