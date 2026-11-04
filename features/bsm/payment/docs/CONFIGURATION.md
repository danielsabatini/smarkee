<!-- Gerado por templates/feature/configuration_guide.py a partir dos settings.py dos papéis. Não edite: altere o código e regenere. -->
# Configuração de bsm.payment: guia de parâmetros

Referência de **todas** as configurações dos papéis de `bsm.payment` (`bsm-payment-<papel>`), na ordem de precedência, e de como executar cada um. Decisões: [`0067`](../../../../.decisions/0067-configuracao-por-papel-com-config-toml-e-segredos-em-arquivo.md) (configuração), [`0069`](../../../../.decisions/0069-prefixo-smarkee-nas-variaveis-de-infraestrutura.md) (prefixo) e [`0070`](../../../../.decisions/0070-senhas-dos-servicos-como-arquivos-montados.md) (senhas como arquivos).

> Gerado dos `settings.py` de `src/bsm_payment/<papel>/` e de `common/settings.py`. Para atualizar: `cd features/bsm/payment && uv run python ../../../templates/feature/configuration_guide.py`.

## 1. Precedência

Cada campo é resolvido pela **primeira** fonte que o informa, da maior para a menor prioridade:

| # | Fonte | Como informar | Observações |
|---|---|---|---|
| 1 | **Linha de comando** | `--<seção>.<campo> <valor>` | Só no entrypoint do papel. **Segredo é recusado** (aparece em `ps`): qualquer argumento que cite `password` encerra o serviço. |
| 2 | **Variável de ambiente** | `BSM_PAYMENT_<PAPEL>_<SEÇÃO>_<CAMPO>` | Em dev vem do `.env` (`docker compose` ou `uv run --env-file .env`). |
| 3 | **`config.toml`** | tabela `[tool.bsm.payment.<papel>.<seção>]` | Caminho em `SMARKEE_CONFIG_PATH` (padrão `config.toml`). Arquivo ou tabela ausente equivale a vazio. **Nunca tem segredo.** |
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

| Fonte | Nos manifestos (`k8s/`) |
|---|---|
| Linha de comando | O `command` é só o nome do papel (`[bsm-payment-api]`), sem argumentos. |
| Ambiente | `env:` define só o que não é senha (por exemplo, audiência e IDs do Zitadel). |
| `config.toml` | Montado em `/etc/smarkee/config.toml` (`SMARKEE_CONFIG_PATH`). Endereços usam o DNS do Kubernetes (`database-rw.database.svc.cluster.local`, `messaging.messaging.svc.cluster.local`). |
| Arquivo de segredo | `ExternalSecret` sincronizado do OpenBao (`/svm`) e montado em `/run/secrets`: cada papel monta só as suas senhas. |

Fora do cluster Kubernetes, os nomes `*.svc.cluster.local` não resolvem: use as portas publicadas em `127.0.0.1` (Postgres `5432`, NATS `4222`) por flag ou variável.

## 3. `bsm-payment-api`

Entrypoint da API de Payment (`bsm-payment-api`, decisões 0015, 0098 e 0100).

- **Prefixo das variáveis:** `BSM_PAYMENT_API_`
- **Tabela do `config.toml`:** `[tool.bsm.payment.api.<seção>]`
- **Comando:** `bsm-payment-api` (entrypoint `bsm_payment.api.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `BSM_PAYMENT_API_MESSAGING_URL`
- `BSM_PAYMENT_API_MESSAGING_USER`
- `BSM_PAYMENT_API_MESSAGING_PASSWORD`
- `BSM_PAYMENT_API_DATABASE_HOST`
- `BSM_PAYMENT_API_DATABASE_PORT`
- `BSM_PAYMENT_API_DATABASE_NAME`
- `BSM_PAYMENT_API_DATABASE_USER`
- `BSM_PAYMENT_API_DATABASE_PASSWORD`
- `BSM_PAYMENT_API_AUTH_AUDIENCE`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `BSM_PAYMENT_API_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `BSM_PAYMENT_API_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `BSM_PAYMENT_API_DATABASE_HOST` | `--database.host` | `str \| None` | — | Obrigatória. Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `BSM_PAYMENT_API_DATABASE_PORT` | `--database.port` | `int \| None` | — | Obrigatória. |
| `database.name` | `BSM_PAYMENT_API_DATABASE_NAME` | `--database.name` | `str \| None` | — | Obrigatória. |
| `database.user` | `BSM_PAYMENT_API_DATABASE_USER` | `--database.user` | `str \| None` | — | Obrigatória. Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `BSM_PAYMENT_API_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `BSM_PAYMENT_API_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `BSM_PAYMENT_API_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `BSM_PAYMENT_API_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `auth.issuer` | `BSM_PAYMENT_API_AUTH_ISSUER` | `--auth.issuer` | `str` | `'http://localhost:8080'` | Valor esperado de `iss`: o endereço público do provedor de identidade. |
| `auth.jwks_url` | `BSM_PAYMENT_API_AUTH_JWKS_URL` | `--auth.jwks_url` | `str` | `'http://localhost:8000/oauth/v2/keys'` | Endereço (da rede interna) em que as chaves públicas são buscadas. |
| `auth.userinfo_url` | `BSM_PAYMENT_API_AUTH_USERINFO_URL` | `--auth.userinfo_url` | `str` | `'http://localhost:8000/oidc/v1/userinfo'` |  |
| `auth.host_header` | `BSM_PAYMENT_API_AUTH_HOST_HEADER` | `--auth.host_header` | `str` | `'localhost:8080'` | `Host` enviado ao provedor nas chamadas internas: ele resolve a instância por esse valor. |
| `auth.audience` | `BSM_PAYMENT_API_AUTH_AUDIENCE` | `--auth.audience` | `str \| None` | — | Obrigatória. ID do projeto de roles do módulo (`roles-bsm`), exigido no `aud` do token. |
| `auth.jwks_cache_seconds` | `BSM_PAYMENT_API_AUTH_JWKS_CACHE_SECONDS` | `--auth.jwks_cache_seconds` | `int` | `300` |  |
| `auth.userinfo_cache_seconds` | `BSM_PAYMENT_API_AUTH_USERINFO_CACHE_SECONDS` | `--auth.userinfo_cache_seconds` | `int` | `60` |  |
| `auth.http_timeout_seconds` | `BSM_PAYMENT_API_AUTH_HTTP_TIMEOUT_SECONDS` | `--auth.http_timeout_seconds` | `float` | `5.0` |  |
| `api.host` | `BSM_PAYMENT_API_API_HOST` | `--api.host` | `str` | `'0.0.0.0'` |  |
| `api.port` | `BSM_PAYMENT_API_API_PORT` | `--api.port` | `int` | `8000` |  |
| `api.payment_quota` | `BSM_PAYMENT_API_API_PAYMENT_QUOTA` | `--api.payment_quota` | `int \| None` | `10` | Limite de métodos de pagamento ativos por Customer Account (`None` desliga). |

**Definido no `config.toml` de dev:**

```toml
[tool.bsm.payment.api.auth]
host_header = "ipm-dev.smarkee.com.br:8080"
issuer = "http://ipm-dev.smarkee.com.br:8080"
jwks_url = "http://gateway.gateway.svc.cluster.local:8000/oauth/v2/keys"

[tool.bsm.payment.api.database]
host = "database-rw.database.svc.cluster.local"
name = "ssot"
port = 5432
user = "bsm_payment_api_login"

[tool.bsm.payment.api.messaging]
url = "nats://messaging.messaging.svc.cluster.local:4222"
user = "smarkee"
```

**Executar** (de `features/bsm/payment`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d bsm-payment-api
docker compose logs -f bsm-payment-api

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env bsm-payment-api \
    --api.port 8001 \
    --database.host localhost \
    --messaging.url nats://localhost:4222

# Lista todas as flags aceitas pelo papel
uv run bsm-payment-api --help
```

## 4. `bsm-payment-publisher`

Entrypoint do Publisher de `bsm.payment` (decisões 0015 e 0033).

- **Prefixo das variáveis:** `BSM_PAYMENT_PUBLISHER_`
- **Tabela do `config.toml`:** `[tool.bsm.payment.publisher.<seção>]`
- **Comando:** `bsm-payment-publisher` (entrypoint `bsm_payment.publisher.main:main`)

**Obrigatórias** (sem default; o serviço não sobe sem elas):

- `BSM_PAYMENT_PUBLISHER_MESSAGING_URL`
- `BSM_PAYMENT_PUBLISHER_MESSAGING_USER`
- `BSM_PAYMENT_PUBLISHER_MESSAGING_PASSWORD`
- `BSM_PAYMENT_PUBLISHER_DATABASE_HOST`
- `BSM_PAYMENT_PUBLISHER_DATABASE_PORT`
- `BSM_PAYMENT_PUBLISHER_DATABASE_NAME`
- `BSM_PAYMENT_PUBLISHER_DATABASE_USER`
- `BSM_PAYMENT_PUBLISHER_DATABASE_PASSWORD`

| Campo | Variável | Flag | Tipo | Default | Descrição |
|---|---|---|---|---|---|
| `log.level` | `BSM_PAYMENT_PUBLISHER_LOG_LEVEL` | `--log.level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'INFO'` | Nível dos logs do próprio código do papel. |
| `log.dependencies_level` | `BSM_PAYMENT_PUBLISHER_LOG_DEPENDENCIES_LEVEL` | `--log.dependencies_level` | `Literal['DEBUG', 'INFO', 'WARNING', 'ERROR']` | `'WARNING'` | Nível dos logs das bibliotecas (cliente HTTP, servidor HTTP, NATS, banco): por padrão só avisos e erros, para não repetirem a cada chamada o que o próprio papel já registra. |
| `database.host` | `BSM_PAYMENT_PUBLISHER_DATABASE_HOST` | `--database.host` | `str \| None` | — | Obrigatória. Endereço do banco. Sem default: vem do ambiente ou do `config.toml`. |
| `database.port` | `BSM_PAYMENT_PUBLISHER_DATABASE_PORT` | `--database.port` | `int \| None` | — | Obrigatória. |
| `database.name` | `BSM_PAYMENT_PUBLISHER_DATABASE_NAME` | `--database.name` | `str \| None` | — | Obrigatória. |
| `database.user` | `BSM_PAYMENT_PUBLISHER_DATABASE_USER` | `--database.user` | `str \| None` | — | Obrigatória. Papel de login do banco, um por papel. Sem default: vem do ambiente ou do `config.toml`. |
| `database.password` | `BSM_PAYMENT_PUBLISHER_DATABASE_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `messaging.url` | `BSM_PAYMENT_PUBLISHER_MESSAGING_URL` | `--messaging.url` | `str \| None` | — | Obrigatória. Endereço do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.user` | `BSM_PAYMENT_PUBLISHER_MESSAGING_USER` | `--messaging.user` | `str \| None` | — | Obrigatória. Usuário do NATS. Sem default: vem do ambiente ou do `config.toml`. |
| `messaging.password` | `BSM_PAYMENT_PUBLISHER_MESSAGING_PASSWORD` | _recusada_ | `SecretStr \| None` | — | Obrigatória. Só por ambiente ou arquivo de segredo. |
| `health.port` | `BSM_PAYMENT_PUBLISHER_HEALTH_PORT` | `--health.port` | `int` | `8000` | Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018). |

**Definido no `config.toml` de dev:**

```toml
[tool.bsm.payment.publisher.database]
host = "database-rw.database.svc.cluster.local"
name = "ssot"
port = 5432
user = "bsm_payment_publisher_login"

[tool.bsm.payment.publisher.messaging]
url = "nats://messaging.messaging.svc.cluster.local:4222"
user = "smarkee"
```

**Executar** (de `features/bsm/payment`):

```bash
# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets
docker compose up -d bsm-payment-publisher
docker compose logs -f bsm-payment-publisher

# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)
uv run --env-file .env bsm-payment-publisher \
    --health.port 8003 \
    --database.host localhost \
    --messaging.url nats://localhost:4222

# Lista todas as flags aceitas pelo papel
uv run bsm-payment-publisher --help
```
