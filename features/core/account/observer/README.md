# core-account-observer

Observer de `core.account` (`core-account-observer`), componente autocontido (`.decisions/0015-componentes-por-papel-autocontidos.md`).

Lê o usuário e as roles no Zitadel com uma conta de serviço **somente leitura** (`core-account-observer`, papel `ORG_OWNER_VIEWER`) e publica `observed` (`presence`: `present`, `absent` ou `unknown`). Qualquer falha de leitura vira `unknown`, nunca `absent`: `absent` só com `404` do Zitadel cujo corpo traz o código `5` e `details`. Observa quando o `desired` é novo, depois de cada resultado de ação e periodicamente (5 min, com jitter), só os recursos da sua partição (`hash(resourceId) mod count`).

## Estrutura (decisão 0017)

```text
src/core_account_observer/
  domain/      mapeamento do Zitadel para o `observed` (observation.py) e tipos do provedor (identity.py)
  provider/    leitor do Zitadel (HTTP, JWT da conta de serviço)
  engine/      estado em memória, partição, limite de leituras e publicação
  transport/   consumers de estado por instância e publicação no NATS
  http/        servidor de saúde (/health/live, /health/ready, /health/startup; decisão 0018)
  main.py
```

`tests/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Configuração

Variáveis `CORE_ACCOUNT_OBSERVER_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatórias, sem default: `CORE_ACCOUNT_OBSERVER_NATS_PASSWORD` e `CORE_ACCOUNT_OBSERVER_ZITADEL_REGISTER_ORGANIZATION_ID`. Ele lê as roles do usuário em todos os projetos de roles, pela organização `register`. A chave da conta de serviço é um arquivo montado (`/run/secrets/zitadel-key.json`). Os demais valores e defaults estão em `src/core_account_observer/settings.py`.

## Desenvolvimento

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest
```
