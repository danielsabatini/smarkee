# 0069 — Prefixo `SMARKEE_` nas variáveis de infraestrutura

- **Data:** 2026-10-20
- **Status:** Aceita e implementada. Detalha a 0068 (a função continua sendo o nome); não contradiz o §2 nem o §15.1 do `AGENTS.md`.

## Contexto

A 0068 trocou o nome do produto pela função (`DATABASE_*`, `MESSAGING_*`...). Esses nomes são genéricos e ficam no mesmo ambiente de outras ferramentas do desenvolvedor, onde `DATABASE_URL`, `GATEWAY_*` ou `MAIL_*` podem existir por outros motivos. As variáveis de execução dos serviços já usavam `SMARKEE_` (`SMARKEE_ENVIRONMENT`, `SMARKEE_CONFIG_PATH`, `SMARKEE_SECRETS_DIR`).

Foi avaliado `SK_` para tudo. Foi descartado: a CLI `sk` usa `env_prefix="SK_"` com `extra="forbid"` e tem as seções `core`, `ipm` e `sum`, então `SK_CORE_ACCOUNT_RECEIVER_*` faria a CLI falhar com `ValidationError` (testado).

## Decisão

- **Infraestrutura:** `SMARKEE_<FUNÇÃO>_<O QUE CONTROLA>`. Por exemplo `SMARKEE_DATABASE_PASSWORD`, `SMARKEE_MESSAGING_CLIENT_PORT`, `SMARKEE_IDENTITY_MASTERKEY`, `SMARKEE_GATEWAY_AUTH_AUDIENCE_CORE_ACCOUNT`, `SMARKEE_MAIL_UI_PORT`, `SMARKEE_TELEMETRY_IMAGE_VERSION`, `SMARKEE_PLATFORM_TELEMETER_CPUS`. O mapeamento da 0068 vale com o prefixo acrescentado.
- **Aplicação (serviços):** inalterada, `<MÓDULO>_<TIPO>_<PAPEL>_<SEÇÃO>_<CAMPO>`. O prefixo `SK_` fica exclusivo da CLI.
- **Execução:** `SMARKEE_ENVIRONMENT`, `SMARKEE_CONFIG_PATH` e `SMARKEE_SECRETS_DIR`, como já eram.
- **Nome dentro do contêiner:** o `compose.yaml` continua mapeando para o nome que o produto lê (`POSTGRES_PASSWORD`, `NATS_PASSWORD`, `ZITADEL_*`, `APISIX_*`), por ser identificador externo (§15.1). Variáveis cujo nome o contêiner lê diretamente (`TELEMETRY_ROUTER_ENDPOINT` no agente de telemetria) foram renomeadas nos dois lados.
- **Não mudam:** `IDENTITY_REGISTER_ORGANIZATION_ID` e `IDENTITY_PROJECT_IDS` (são variáveis de aplicação, pendentes de padronização por papel), `MESSAGING_CONSUMER_INACTIVE_THRESHOLD_SECONDS` (campo de aplicação), as variáveis de teste (`CORE_TEST_*`, `CONFORMANCE_*`, `E2E_*`) e as constantes de código (`DATABASE_NAME`, `MAIL_QUERIES`).

## Consequências

- **Quebra de contrato em desenvolvimento (§10), sem compatibilidade:** quem tem `.env` local renomeia as chaves de `infrastructure/dev/*` acrescentando `SMARKEE_`. Os `.env` das features não têm variáveis de infraestrutura.
- Os `.env.example`, os `compose.yaml`, o `adc.yaml`, o `config.yaml` do agente de telemetria, os scripts de `scripts/dev` e a documentação foram atualizados juntos.
- Verificação: `docker compose config` limpo em todos os compose, plataforma e as 3 features recriadas e saudáveis, gateway respondendo 401 sem token, testes dos scripts passando.
