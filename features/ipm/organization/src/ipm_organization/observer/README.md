# ipm-organization-observer

Observer de `ipm.organization` (`ipm-organization-observer`), um dos seis papéis da imagem única `ipm-organization` (decisão 0063), com processo e contêiner próprios. Veja o [README da feature](../../../README.md).

Lê a organização no Zitadel (API v2, `OrganizationService/ListOrganizations`, consulta pelo ID exato) com uma conta de serviço **somente leitura** (`ipm-organization-observer`, papel de instância `IAM_OWNER_VIEWER`) e publica `observed` (`presence`: `present`, `absent` ou `unknown`; `data`: `name`, `platformAccess` e `organizationState`). `platformAccess` é `granted` com a organização ativa e `revoked` com ela desativada. Qualquer falha de leitura vira `unknown`, nunca `absent`: `absent` só com uma consulta bem-sucedida, pelo ID exato, sem resultado. Um estado de organização que o contrato não conhece também é `unknown`. Observa quando o `desired` é novo, depois de cada resultado de ação e periodicamente (5 min, com jitter), só os recursos da sua partição (`hash(resourceId) mod count`).

## Estrutura (decisão 0017)

```text
src/ipm_organization/observer/
  domain/      mapeamento do Zitadel para o `observed` (observation.py) e tipos do provedor (identity.py)
  provider/    leitor do Zitadel (HTTP, JWT da conta de serviço)
  engine/      estado em memória, partição, limite de leituras e publicação
  transport/   consumers de estado por instância e publicação no NATS
  main.py
```

`tests/common/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Configuração

Variáveis `IPM_ORGANIZATION_OBSERVER_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatória, sem default: `IPM_ORGANIZATION_OBSERVER_MESSAGING_PASSWORD`. A chave da conta de serviço é um arquivo montado (`/run/secrets/zitadel-key.json`). Os demais valores e defaults estão em `src/ipm_organization/observer/settings.py`.

## Desenvolvimento

```bash
# Na raiz da feature (features/ipm/organization), que é o projeto único:
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/observer
```
