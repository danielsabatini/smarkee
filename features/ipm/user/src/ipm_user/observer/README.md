# ipm-user-observer

Observer de `ipm.user` (`ipm-user-observer`), um dos seis papéis da imagem única `ipm-user` (decisão 0063), com processo e contêiner próprios. Veja o [README da feature](../../../README.md).

Lê o usuário no Zitadel com uma conta de serviço **somente leitura** (`ipm-user-observer`, `ORG_OWNER_VIEWER` em cada organização de cliente, dado pelo operador; decisão 0077), por três drivers espelhados dos do Executor (decisão 0073): o usuário (`GET /v2/users/{id}`: `userState`, `initial` até a senha ser definida, e `emailVerified`), a autorização (as `permissions` dele em `roles-ipm`) e o metadado `deletionProtection` (decisão 0074). Publica `observed` (`presence`: `present`, `absent` ou `unknown`), sem dados pessoais. Qualquer falha de leitura vira `unknown`, nunca `absent`: `absent` só com o `404` do usuário exato. Observa quando o `desired` é novo, depois de cada resultado de ação e periodicamente (5 min, com jitter), só os recursos da sua partição (`hash(resourceId) mod count`).

## Estrutura (decisão 0017)

```text
src/ipm_user/observer/
  domain/      mapeamento do Zitadel para o `observed` (observation.py) e tipos do provedor (identity.py)
  drivers/     leitura no Zitadel, um por sub-recurso (user.py, authorization.py e metadata.py; espelho do Executor, decisão 0073)
  provider/    conexão só de leitura com o Zitadel (HTTP, JWT da conta de serviço)
  engine/      estado em memória, partição, limite de leituras e publicação
  transport/   consumers de estado por instância e publicação no NATS
  main.py
```

`tests/common/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Configuração

Variáveis `IPM_USER_OBSERVER_<SEÇÃO>_<CAMPO>` e o `config.toml` da feature. Obrigatórias, sem default: `IPM_USER_OBSERVER_MESSAGING_PASSWORD` e `IPM_USER_OBSERVER_IDENTITY_PROJECT_ID` (o projeto `roles-ipm`). A chave da conta de serviço é um arquivo montado (`/run/secrets/zitadel-key.json`). Os demais valores e defaults estão em `src/ipm_user/observer/settings.py`.

## Desenvolvimento

```bash
# Na raiz da feature (features/ipm/user), que é o projeto único:
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/observer
```
