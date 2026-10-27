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

## 3. `core-account-api`

Entrypoint da API de Account (`core-account-api`, decisões 0015, 0098 e 0100).

- **Prefixo das variáveis:** `CORE_ACCOUNT_API_`
- **Tabela do `config.toml`:** `[tool.core.account.api.<seção>]`
- **Comando:** `core-account-api` (entrypoint `core_account.api.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `CORE_ACCOUNT_API_AUTH_AUDIENCE`
- `CORE_ACCOUNT_API_MESSAGING_URL`
- `CORE_ACCOUNT_API_MESSAGING_USER`
- `CORE_ACCOUNT_API_MESSAGING_PASSWORD`
- `CORE_ACCOUNT_API_DATABASE_HOST`
- `CORE_ACCOUNT_API_DATABASE_PORT`
- `CORE_ACCOUNT_API_DATABASE_NAME`
- `CORE_ACCOUNT_API_DATABASE_USER`
- `CORE_ACCOUNT_API_DATABASE_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `CORE_ACCOUNT_API_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `CORE_ACCOUNT_API_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `CORE_ACCOUNT_API_DATABASE_HOST` | `--database.host` | `str \| None` | — | Obrigatória. Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `CORE_ACCOUNT_API_DATABASE_PORT` | `--database.port` | `int \| None` | — | Obrigatória. |
| `database.name` | `CORE_ACCOUNT_API_DATABASE_NAME` | `--database.name` | `str \| None` | — | Obrigatória. |
| `database.user` | `CORE_ACCOUNT_API_DATABASE_USER` | `--database.user` | `str \| None` | — | Obrigatória. Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `CORE_ACCOUNT_API_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `CORE_ACCOUNT_API_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `CORE_ACCOUNT_API_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `CORE_ACCOUNT_API_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `auth.issuer` | `CORE_ACCOUNT_API_AUTH_ISSUER` | `--auth.issuer` | `str` | `'http://localhost:8080'` | Valor esperado de `iss`: o endereço público do provedor de identidade. |
| `auth.jwks_url` | `CORE_ACCOUNT_API_AUTH_JWKS_URL` | `--auth.jwks_url` | `str` | `'http://localhost:8000/oauth/v2/keys'` | Endereço (da rede interna) em que as chaves públicas são buscadas. |
| `auth.host_header` | `CORE_ACCOUNT_API_AUTH_HOST_HEADER` | `--auth.host_header` | `str` | `'localhost:8080'` | `Host` enviado ao provedor nas chamadas internas: ele resolve a instância por esse valor. |
| `auth.audience` | `CORE_ACCOUNT_API_AUTH_AUDIENCE` | `--auth.audience` | `str \| None` | — | Obrigatória. ID do projeto da plataforma (audience dos access tokens). Sem default. |
| `auth.jwks_cache_seconds` | `CORE_ACCOUNT_API_AUTH_JWKS_CACHE_SECONDS` | `--auth.jwks_cache_seconds` | `int` | `300` |  |
| `api.host` | `CORE_ACCOUNT_API_API_HOST` | `--api.host` | `str` | `'0.0.0.0'` |  |
| `api.port` | `CORE_ACCOUNT_API_API_PORT` | `--api.port` | `int` | `8000` |  |
| `api.anonymous_rate_limit` | `CORE_ACCOUNT_API_API_ANONYMOUS_RATE_LIMIT` | `--api.anonymous_rate_limit` | `int` | `5` |  |
| `api.anonymous_rate_window_seconds` | `CORE_ACCOUNT_API_API_ANONYMOUS_RATE_WINDOW_SECONDS` | `--api.anonymous_rate_window_seconds` | `int` | `60` |  |
| `api.client_address_header` | `CORE_ACCOUNT_API_API_CLIENT_ADDRESS_HEADER` | `--api.client_address_header` | `str \| None` | `'x-forwarded-for'` | Cabeçalho com o endereço do cliente, definido pelo gateway (único acesso ao serviço). |
| `platform.permissions` | `CORE_ACCOUNT_API_PLATFORM_PERMISSIONS` | `--platform.permissions` | `tuple[str, ...]` | `('bsm.account.create', 'bsm.account.delete', 'bsm.account.get', 'bsm.account.list', 'bsm.account.update', 'core.account.delete', 'core.account.get', 'sum.ipm.disable', 'sum.ipm.enable', 'sum.ipm.get')` | Permissões gravadas no `desired` do usuário cadastrado (decisão 0025). Lista em JSON. |

**Definido no `config.toml` de dev:**

```toml
[tool.core.account.api.auth]
host_header = "ipm-dev.smarkee.com.br:8080"
issuer = "http://ipm-dev.smarkee.com.br:8080"
jwks_url = "http://gateway.smarkee.internal:8000/oauth/v2/keys"

[tool.core.account.api.database]
host = "database.smarkee.internal"
name = "ssot"
port = 5432
user = "core_account_api_login"

[tool.core.account.api.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/core/account`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d core-account-api
docker compose logs -f core-account-api

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env core-account-api \
    --api.port 8001 \
    --database.host localhost \
    --messaging.url nats://localhost:4222

# Lista todas as flags aceitas pelo papel
uv run core-account-api --help
```

## 4. `core-account-publisher`

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
name = "ssot"
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
