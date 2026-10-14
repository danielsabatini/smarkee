# core-user-observer

Observer de `core.user` (`core-user-observer`), componente autocontido (`.decisions/0015-componentes-por-papel-autocontidos.md`).

Lê o usuário e as roles no Zitadel com uma conta de serviço **somente leitura** (`core-user-observer`, papel `ORG_OWNER_VIEWER`) e publica `observed` (`presence`: `present`, `absent` ou `unknown`). Qualquer falha de leitura vira `unknown`, nunca `absent`: `absent` só com `404` do Zitadel cujo corpo traz o código `5` e `details`. Observa quando o `desired` é novo, depois de cada resultado de ação e periodicamente (5 min, com jitter), só os recursos da sua partição (`hash(resourceId) mod count`).

## Estrutura (decisão 0017)

```text
src/core_user_observer/
  domain/      mapeamento do Zitadel para o `observed` (observation.py) e tipos do provedor (identity.py)
  provider/    leitor do Zitadel (HTTP, JWT da conta de serviço)
  engine/      estado em memória, partição, limite de leituras e publicação
  transport/   consumers de estado por instância e publicação no NATS
  http/        servidor de saúde (/health/live, /health/ready, /health/startup; decisão 0018)
  main.py
```

`tests/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Configuração

Variáveis `CORE_USER_OBSERVER_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatórias, sem default: `CORE_USER_OBSERVER_NATS_PASSWORD`, `CORE_USER_OBSERVER_ZITADEL_REGISTER_ORGANIZATION_ID` e `CORE_USER_OBSERVER_ZITADEL_PROJECT_ID`. A chave da conta de serviço é um arquivo montado (`/run/secrets/zitadel-key.json`). Os demais valores e defaults estão em `src/core_user_observer/settings.py`.

## Desenvolvimento

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest
```
