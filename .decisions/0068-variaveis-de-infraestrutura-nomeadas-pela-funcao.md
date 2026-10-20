# 0068 — Variáveis de infraestrutura nomeadas pela função, não pelo produto

- **Data:** 2026-10-20
- **Status:** Aceita e implementada. Aplica o §15.1 do `AGENTS.md` às variáveis de `infrastructure/`. Estende a 0016 e a 0067 (que cobrem as variáveis de aplicação). Não contradiz o §2. O prefixo `SMARKEE_` foi acrescentado pela 0069.

## Contexto

As variáveis de aplicação seguem `<MÓDULO>_<TIPO>_<PAPEL>_<SEÇÃO>_<CAMPO>` (0016, 0065, 0067). As de infraestrutura levavam o nome do produto (`POSTGRES_IMAGE_VERSION`, `APISIX_PROXY_HTTP_PORT`, `OTELCOL_IMAGE_VERSION`), o que obrigava a renomear tudo ao trocar o produto.

## Decisão

- **Aplicação:** continua `<FEATURE>_<PAPEL>_...`.
- **Infraestrutura:** o prefixo é a **função** (`DATABASE_`, `MESSAGING_`, `IDENTITY_`, `GATEWAY_`, `MAIL_`, `TELEMETRY_`), seguido do que a variável controla (`IMAGE_VERSION`, `PORT`, ...).
- **Mudam as chaves do `.env` e do lado direito do `${...}` no compose.** O `compose.yaml` faz o mapeamento para o nome que o produto lê dentro do contêiner, que mantém o nome do produto por ser identificador externo (§15.1): `POSTGRES_USER|PASSWORD|DB`, `NATS_USER|PASSWORD` (lidos pelo `nats.conf` e pela CLI do NATS), `ZITADEL_*` e `APISIX_ADMIN_KEY`. Exemplo: `POSTGRES_PASSWORD: ${DATABASE_PASSWORD}`.
- **Coletor OpenTelemetry:** uma só variável de função, `TELEMETRY_IMAGE_VERSION`, usada pela infraestrutura e pelo telemeter de cada feature.

## Mapeamento (contrato incompatível, §10)

| Antes | Depois |
|---|---|
| `POSTGRES_IMAGE_VERSION`, `POSTGRES_CLIENT_IMAGE`, `POSTGRES_PORT` | `DATABASE_IMAGE_VERSION`, `DATABASE_CLIENT_IMAGE`, `DATABASE_PORT` |
| `NATS_IMAGE_VERSION`, `NATS_CLIENT_IMAGE`, `NATS_CLIENT_PORT`, `NATS_MONITOR_PORT` | `MESSAGING_IMAGE_VERSION`, `MESSAGING_CLIENT_IMAGE`, `MESSAGING_CLIENT_PORT`, `MESSAGING_MONITOR_PORT` |
| `ZITADEL_IMAGE_VERSION`, `ZITADEL_LOGIN_IMAGE_VERSION` | `IDENTITY_IMAGE_VERSION`, `IDENTITY_LOGIN_IMAGE_VERSION` |
| `APISIX_IMAGE_VERSION`, `ETCD_IMAGE_VERSION`, `ADC_IMAGE_VERSION` | `GATEWAY_IMAGE_VERSION`, `GATEWAY_ETCD_IMAGE_VERSION`, `GATEWAY_ADC_IMAGE_VERSION` |
| `APISIX_PROXY_HTTP_PORT`, `APISIX_ADMIN_PORT`, `APISIX_TRUSTED_PROXIES` | `GATEWAY_PROXY_HTTP_PORT`, `GATEWAY_ADMIN_PORT`, `GATEWAY_TRUSTED_PROXIES` |
| `APISIX_OTEL_COLLECTOR_ADDRESS`, `APISIX_AUTH_AUDIENCE_<MÓDULO>_<TIPO>` | `GATEWAY_TELEMETRY_ADDRESS`, `GATEWAY_AUTH_AUDIENCE_<MÓDULO>_<TIPO>` |
| `APISIX_ADMIN_KEY` (no `.env` e no compose do gateway) | `GATEWAY_ADMIN_KEY` (o contêiner do APISIX segue lendo `APISIX_ADMIN_KEY`) |
| `MAILPIT_IMAGE_VERSION`, `MAILPIT_UI_PORT` | `MAIL_IMAGE_VERSION`, `MAIL_UI_PORT` |
| `OTELCOL_IMAGE_VERSION` | `TELEMETRY_IMAGE_VERSION` |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | `DATABASE_USER`, `DATABASE_PASSWORD`, `DATABASE_NAME` |
| `NATS_USER`, `NATS_PASSWORD` | `MESSAGING_USER`, `MESSAGING_PASSWORD` |
| `ZITADEL_MASTERKEY`, `ZITADEL_SESSION_COOKIE_SECRET` | `IDENTITY_MASTERKEY`, `IDENTITY_SESSION_COOKIE_SECRET` |
| `ZITADEL_DATABASE_POSTGRES_{HOST,PORT,DATABASE,USER_USERNAME,USER_PASSWORD}` | `IDENTITY_DATABASE_{HOST,PORT,NAME,USER,PASSWORD}` |
| `ZITADEL_FIRSTINSTANCE_{INSTANCENAME,ORG_NAME}` | `IDENTITY_INSTANCE_NAME`, `IDENTITY_ORG_NAME` |
| `ZITADEL_FIRSTINSTANCE_ORG_HUMAN_{USERNAME,PASSWORD,EMAIL}` | `IDENTITY_ADMIN_{USERNAME,PASSWORD,EMAIL}` |
| `ZITADEL_EXTERNALDOMAIN`, `ZITADEL_EXTERNALPORT` | `IDENTITY_EXTERNAL_DOMAIN`, `IDENTITY_EXTERNAL_PORT` |
| `ZITADEL_SMTP_{HOST,FROM,FROMNAME}` | `IDENTITY_SMTP_{HOST,FROM,FROMNAME}` |

Consumidores afetados: `.env` e `.env.example` de `infrastructure/dev/*` e das features, os `compose.yaml` (infraestrutura, features e semente), o `adc.yaml` do gateway e a documentação. Quem tem um `.env` local precisa renomear as chaves pelo mapeamento acima; não há compatibilidade com os nomes antigos.

## Fora desta decisão

- Variáveis internas do Zitadel que o compose fixa e que não vêm do `.env` (`ZITADEL_FIRSTINSTANCE_*` de máquina, `ZITADEL_DEFAULTINSTANCE_*`, `ZITADEL_TLS_ENABLED`...) ficam como estão.
- `CORE_IDENTITY_*` segue fora do padrão (pendência da 0067).
- Scripts de `scripts/dev` que leem o `.env` (`cleanup` lê `MESSAGING_PASSWORD`; `backup` compara `.env` inteiros) foram ajustados à chave nova.
