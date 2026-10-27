<!-- Gerado por templates/feature/configuration_guide.py a partir dos settings.py dos papéis. Não edite: altere o código e regenere. -->
# Configuração de ipm.serviceaccount: guia de parâmetros

Referência de **todas** as configurações dos papéis de `ipm.serviceaccount` (`ipm-serviceaccount-<papel>`), na ordem de precedência, e de como executar cada um. Decisões: [`0067`](../../../../.decisions/0067-configuracao-por-papel-com-config-toml-e-segredos-em-arquivo.md) (configuração), [`0069`](../../../../.decisions/0069-prefixo-smarkee-nas-variaveis-de-infraestrutura.md) (prefixo) e [`0070`](../../../../.decisions/0070-senhas-dos-servicos-como-arquivos-montados.md) (senhas como arquivos).

> Gerado dos `settings.py` de `src/ipm_serviceaccount/<papel>/` e de `common/settings.py`. Para atualizar: `cd features/ipm/serviceaccount && uv run python ../../../templates/feature/configuration_guide.py`.

## 1. Precedência

Cada campo é resolvido pela **primeira** fonte que o informa, da maior para a menor prioridade:

| # | Fonte | Como informar | Observações |
|---|---|---|---|
| 1 | **Linha de comando** | `--<seção>.<campo> <valor>` | Só no entrypoint do papel. **Segredo é recusado** (aparece em `ps`): qualquer argumento que cite `password` encerra o serviço. |
| 2 | **Variável de ambiente** | `IPM_SERVICEACCOUNT_<PAPEL>_<SEÇÃO>_<CAMPO>` | Em dev vem do `.env` (`docker compose` ou `uv run --env-file .env`). |
| 3 | **`config.toml`** | tabela `[tool.ipm.serviceaccount.<papel>.<seção>]` | Caminho em `SMARKEE_CONFIG_PATH` (padrão `config.toml`). Arquivo ou tabela ausente equivale a vazio. **Nunca tem segredo.** |
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
| Linha de comando | O `command` é só o nome do papel (`[ipm-serviceaccount-receiver]`), sem argumentos. |
| Ambiente | `environment:` repassa do `.env` só o que não é senha (por exemplo, audiência e IDs do Zitadel). |
| `config.toml` | Montado em `/etc/smarkee/config.toml` (`SMARKEE_CONFIG_PATH`). Endereços usam os nomes da rede Docker (`database.smarkee.internal`, `messaging.smarkee.internal`). |
| Arquivo de segredo | Bloco `secrets:` com `environment: <VARIÁVEL>`: cada papel monta só as suas senhas. |

Fora do Docker, os nomes `*.smarkee.internal` não resolvem: use as portas publicadas em `127.0.0.1` (Postgres `5432`, NATS `4222`) por flag ou variável.

## 3. `ipm-serviceaccount-api`

Entrypoint da API de Service Account (`ipm-serviceaccount-api`, decisões 0015 e 0098).

- **Prefixo das variáveis:** `IPM_SERVICEACCOUNT_API_`
- **Tabela do `config.toml`:** `[tool.ipm.serviceaccount.api.<seção>]`
- **Comando:** `ipm-serviceaccount-api` (entrypoint `ipm_serviceaccount.api.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_SERVICEACCOUNT_API_AUTH_AUDIENCE`
- `IPM_SERVICEACCOUNT_API_MESSAGING_URL`
- `IPM_SERVICEACCOUNT_API_MESSAGING_USER`
- `IPM_SERVICEACCOUNT_API_MESSAGING_PASSWORD`
- `IPM_SERVICEACCOUNT_API_DATABASE_HOST`
- `IPM_SERVICEACCOUNT_API_DATABASE_PORT`
- `IPM_SERVICEACCOUNT_API_DATABASE_NAME`
- `IPM_SERVICEACCOUNT_API_DATABASE_USER`
- `IPM_SERVICEACCOUNT_API_DATABASE_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_SERVICEACCOUNT_API_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_SERVICEACCOUNT_API_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `IPM_SERVICEACCOUNT_API_DATABASE_HOST` | `--database.host` | `str \| None` | — | Obrigatória. Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `IPM_SERVICEACCOUNT_API_DATABASE_PORT` | `--database.port` | `int \| None` | — | Obrigatória. |
| `database.name` | `IPM_SERVICEACCOUNT_API_DATABASE_NAME` | `--database.name` | `str \| None` | — | Obrigatória. |
| `database.user` | `IPM_SERVICEACCOUNT_API_DATABASE_USER` | `--database.user` | `str \| None` | — | Obrigatória. Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `IPM_SERVICEACCOUNT_API_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `IPM_SERVICEACCOUNT_API_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_SERVICEACCOUNT_API_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_SERVICEACCOUNT_API_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `auth.issuer` | `IPM_SERVICEACCOUNT_API_AUTH_ISSUER` | `--auth.issuer` | `str` | `'http://localhost:8080'` | Valor esperado de `iss`: o endereço público do provedor de identidade. |
| `auth.jwks_url` | `IPM_SERVICEACCOUNT_API_AUTH_JWKS_URL` | `--auth.jwks_url` | `str` | `'http://localhost:8000/oauth/v2/keys'` | Endereço (da rede interna) em que as chaves públicas são buscadas. |
| `auth.host_header` | `IPM_SERVICEACCOUNT_API_AUTH_HOST_HEADER` | `--auth.host_header` | `str` | `'localhost:8080'` | `Host` enviado ao provedor nas chamadas internas: ele resolve a instância por esse valor. |
| `auth.audience` | `IPM_SERVICEACCOUNT_API_AUTH_AUDIENCE` | `--auth.audience` | `str \| None` | — | Obrigatória. ID do projeto `roles-ipm` (audience dos access tokens). Sem default. |
| `auth.jwks_cache_seconds` | `IPM_SERVICEACCOUNT_API_AUTH_JWKS_CACHE_SECONDS` | `--auth.jwks_cache_seconds` | `int` | `300` |  |
| `api.host` | `IPM_SERVICEACCOUNT_API_API_HOST` | `--api.host` | `str` | `'0.0.0.0'` |  |
| `api.port` | `IPM_SERVICEACCOUNT_API_API_PORT` | `--api.port` | `int` | `8000` |  |
| `api.serviceaccount_quota` | `IPM_SERVICEACCOUNT_API_API_SERVICEACCOUNT_QUOTA` | `--api.serviceaccount_quota` | `int` | `5` | Service accounts por Organization para quem não é operador (decisão 0094; provisório). |
| `peers.organizations_url` | `IPM_SERVICEACCOUNT_API_PEERS_ORGANIZATIONS_URL` | `--peers.organizations_url` | `str` | `'http://localhost:8000'` |  |
| `peers.users_url` | `IPM_SERVICEACCOUNT_API_PEERS_USERS_URL` | `--peers.users_url` | `str` | `'http://localhost:8000'` | Receiver de User: reconhece o usuário humano da Organization (decisão 0094). |
| `peers.timeout_seconds` | `IPM_SERVICEACCOUNT_API_PEERS_TIMEOUT_SECONDS` | `--peers.timeout_seconds` | `float` | `5.0` |  |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.serviceaccount.api.auth]
host_header = "ipm-dev.smarkee.com.br:8080"
issuer = "http://ipm-dev.smarkee.com.br:8080"
jwks_url = "http://gateway.smarkee.internal:8000/oauth/v2/keys"

[tool.ipm.serviceaccount.api.database]
host = "database.smarkee.internal"
name = "ssot"
port = 5432
user = "ipm_serviceaccount_api_login"

[tool.ipm.serviceaccount.api.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"

[tool.ipm.serviceaccount.api.peers]
organizations_url = "http://ipm-organization-receiver.smarkee.internal:8000"
users_url = "http://ipm-user-api.smarkee.internal:8000"
```

**Executar** (de `features/ipm/serviceaccount`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-serviceaccount-api
docker compose logs -f ipm-serviceaccount-api

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-serviceaccount-api \
    --api.port 8001 \
    --database.host localhost \
    --messaging.url nats://localhost:4222

# Lista todas as flags aceitas pelo papel
uv run ipm-serviceaccount-api --help
```

## 4. `ipm-serviceaccount-publisher`

Entrypoint do Publisher de `ipm.serviceaccount` (decisões 0015 e 0033).

- **Prefixo das variáveis:** `IPM_SERVICEACCOUNT_PUBLISHER_`
- **Tabela do `config.toml`:** `[tool.ipm.serviceaccount.publisher.<seção>]`
- **Comando:** `ipm-serviceaccount-publisher` (entrypoint `ipm_serviceaccount.publisher.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `IPM_SERVICEACCOUNT_PUBLISHER_MESSAGING_URL`
- `IPM_SERVICEACCOUNT_PUBLISHER_MESSAGING_USER`
- `IPM_SERVICEACCOUNT_PUBLISHER_MESSAGING_PASSWORD`
- `IPM_SERVICEACCOUNT_PUBLISHER_DATABASE_HOST`
- `IPM_SERVICEACCOUNT_PUBLISHER_DATABASE_PORT`
- `IPM_SERVICEACCOUNT_PUBLISHER_DATABASE_NAME`
- `IPM_SERVICEACCOUNT_PUBLISHER_DATABASE_USER`
- `IPM_SERVICEACCOUNT_PUBLISHER_DATABASE_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `IPM_SERVICEACCOUNT_PUBLISHER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `IPM_SERVICEACCOUNT_PUBLISHER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `IPM_SERVICEACCOUNT_PUBLISHER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Obrigatória. Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `IPM_SERVICEACCOUNT_PUBLISHER_DATABASE_PORT` | `--database.port` | `int \| None` | — | Obrigatória. |
| `database.name` | `IPM_SERVICEACCOUNT_PUBLISHER_DATABASE_NAME` | `--database.name` | `str \| None` | — | Obrigatória. |
| `database.user` | `IPM_SERVICEACCOUNT_PUBLISHER_DATABASE_USER` | `--database.user` | `str \| None` | — | Obrigatória. Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `IPM_SERVICEACCOUNT_PUBLISHER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `IPM_SERVICEACCOUNT_PUBLISHER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `IPM_SERVICEACCOUNT_PUBLISHER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `IPM_SERVICEACCOUNT_PUBLISHER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `health.port` | `IPM_SERVICEACCOUNT_PUBLISHER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.ipm.serviceaccount.publisher.database]
host = "database.smarkee.internal"
name = "ssot"
port = 5432
user = "ipm_serviceaccount_publisher_login"

[tool.ipm.serviceaccount.publisher.messaging]
url = "nats://messaging.smarkee.internal:4222"
user = "smarkee"
```

**Executar** (de `features/ipm/serviceaccount`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d ipm-serviceaccount-publisher
docker compose logs -f ipm-serviceaccount-publisher

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env ipm-serviceaccount-publisher \
    --health.port 8003 \
    --database.host localhost \
    --messaging.url nats://localhost:4222

# Lista todas as flags aceitas pelo papel
uv run ipm-serviceaccount-publisher --help
```
