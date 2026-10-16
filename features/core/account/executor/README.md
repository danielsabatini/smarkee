# core-account-executor

Executor de `core.account` (`core-account-executor`), componente autocontido (`.decisions/0015-componentes-por-papel-autocontidos.md`).

Única identidade com escrita no Zitadel (conta `core-account-executor`, papéis `ORG_USER_CREATOR` na `register` e `PROJECT_GRANT_OWNER` nos Grants de `core` e `sum`). Consome a `action` do Reconciler, **revalida** contra o `desired` vigente (geração, coerência da operação, reconciliação ativa), confere o desfecho já registrado do `actionId` por Direct Get (idempotência) e executa:

- `create`: cria o usuário **sem senha**, envia o link para definir a senha (`password_reset`) e concede, em cada projeto de roles (uma autorização por módulo), as roles de `desired.platformRoles` (não há lista de roles na configuração do Executor); a senha nunca passa por CLI, Receiver, SSOT nem NATS;
- `update`: ajusta ou revoga as roles (`platformAccess`);
- `delete`: remove o usuário (ausente é sucesso).

Publica `completed` ou `failed {reason, retryable}`; o retry é do Reconciler.

## Partições (decisão 0018)

O Stream `ACTION` é particionado por `resourceId` (4 partições). O Executor roda um laço e um consumer por partição (`core-account-executor-action-p<N>`, `max_ack_pending=1`): uma `action` por vez em cada recurso, até 4 recursos em paralelo. `CORE_ACCOUNT_EXECUTOR_PARTITION_COUNT` deve ser igual ao do bootstrap do broker. Os manifestos estão em `consumers/`.

## Estrutura (decisão 0017)

```text
src/core_account_executor/
  domain/      revalidação da action, erros e tipos do provedor
  actions/     execução de cada operação sobre o provedor (idempotente)
  provider/    escritor do Zitadel (HTTP, JWT da conta de serviço)
  engine/      fluxo de cada action e publicação do resultado
  transport/   consumers por partição, Direct Get e publicação no NATS
  http/        servidor de saúde (/health/live, /health/ready, /health/startup)
  main.py
```

`tests/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Configuração

Variáveis `CORE_ACCOUNT_EXECUTOR_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatórias, sem default: `CORE_ACCOUNT_EXECUTOR_NATS_PASSWORD`, `CORE_ACCOUNT_EXECUTOR_ZITADEL_REGISTER_ORGANIZATION_ID` e `CORE_ACCOUNT_EXECUTOR_ZITADEL_PROJECT_IDS` (JSON módulo → ID do projeto de roles, por exemplo `{"core":"…","sum":"…"}`). A chave da conta de serviço é um arquivo montado (`/run/secrets/zitadel-key.json`), só desta conta.

## Desenvolvimento

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest
```
