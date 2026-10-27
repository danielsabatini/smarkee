# ipm-organization-controller

Controller de `ipm.organization` (`ipm-organization-controller`), um dos quatro papéis da imagem única `ipm-organization` (decisões 0063 e 0096), com processo e contêiner próprios. Veja o [README da feature](../../../README.md) e o [fluxo de dados](../../../docs/IPM-ORGANIZATION-DATA-FLOW.md) (seção 4).

Observa, decide, age e reobserva a Organization (organização do Zitadel e o preparo dela para os usuários) **numa só transação**, e grava o estado convergido e o `updated` no outbox. Substitui os antigos Observer, Reconciler e Executor, no modelo de controlador do Kubernetes (Informer + Workqueue). Decisão [`0096`](../../../../../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md).

## Ciclo

1. **Informer:** consome `manager.desired.ipm.organization.>` (Stream `DESIRED`, consumer `ipm-organization-controller-desired-<instância>`) e enfileira o `resourceId` na Workqueue, só se ele pertencer à partição da instância (`hash(resourceId) mod count == index`).
2. **Reavaliação periódica:** enfileira todos os recursos `reconciliation = 'active'` da partição, com jitter, para detectar divergência externa.
3. **Workqueue:** deduplica por `resourceId` e repete com backoff exponencial quando o provedor falha de forma transitória ou o recurso ainda não convergiu.
4. **`reconcile(resourceId)`**, numa transação com a linha bloqueada (`FOR UPDATE`):
   - observa o Zitadel (organização, metadado `deletionProtection` e o preparo para os usuários, `userAccess`);
   - decide com a função pura `decide(desired, observed)` (`domain/decision.py`): `create`, `update`, `delete` ou nada;
   - executa a ação idempotente nos drivers, se houver divergência, e **reobserva**;
   - calcula fase e conditions (`domain/convergence.py`), grava `observed`, `phase`, `conditions`, as Operations e o `updated` no outbox; se a remoção convergiu, apaga o registro; se atingiu o limite de falhas, suspende a reconciliação e grava um `desired` suspenso no outbox.

A idempotência da ação vem das operações idempotentes dos drivers e do ciclo atômico; não há registro por `actionId` (a tabela `ipm.organization_action_result` foi removida pela migração `0008`).

## Regras do tipo

- Campos comparados: `lifecycle`, `name`, `platformAccess`, `deletionProtection` e `userAccess`.
- O ID da organização no Zitadel é o `resourceId`. `create` com `409` lê a organização pelo ID: nome igual é sucesso idempotente; senão, a ação falha com `Rejected`.
- `platformAccess` `granted` deixa a organização ativa; `revoked`, desativada. O preparo para os usuários (Project Grant de `roles-ipm` e papéis das contas `ipm/user` e `ipm/serviceaccount`) só é aplicado com `granted`, e só no que falta.
- `absent` só quando a consulta pelo ID teve sucesso e não trouxe resultado; qualquer falha de leitura é `unknown`, que nunca autoriza ação.
- Não cria usuários nem autoriza o dono.

## Estrutura

```text
src/ipm_organization/controller/
  domain/      decisão pura e convergência (fase, conditions, prazos)
  drivers/     Zitadel: conexão, organização, metadados e preparo para os usuários
  engine/      Informer, Workqueue, observação, ação e o ciclo atômico
  store/       único código com SQL do Controller (ControllerSsotStore)
  settings.py
  main.py
```

A dependência vai em um sentido só; `tests/common/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Privilégios

- **Banco:** papel `ipm_organization_controller` (migrações `0007` e `0008`): `SELECT`, `UPDATE` e `DELETE` em `ipm.organization`; `SELECT` e `UPDATE` em `ipm.organization_operation`; só `INSERT` no outbox. Não cria nem altera o `desired` de um pedido.
- **Zitadel:** conta `ipm-organization-controller`, com `IAM_ORG_MANAGER` de instância (exceção deliberada da decisão 0060; lacuna declarada em `docs/platform/IMPLEMENTATION-STATUS.md`).

## Saúde

`GET /health/live`, `/health/ready` e `/health/startup` na porta `8000`.

## Configuração

Variáveis de ambiente `IPM_ORGANIZATION_CONTROLLER_<SEÇÃO>_<CAMPO>` e o `config.toml` da feature. Obrigatórias, sem default: `MESSAGING_URL`, `MESSAGING_USER`, `MESSAGING_PASSWORD`, `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER`, `DATABASE_PASSWORD` e `IDENTITY_PROJECT_ID` (ID do projeto `roles-ipm`). Todos os campos estão em [`docs/CONFIGURATION.md`](../../../docs/CONFIGURATION.md).

## Desenvolvimento

```bash
# Na raiz da feature (features/ipm/organization), que é o projeto único:
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/controller  # os testes de integração exigem a stack de dev e são pulados sem ela
```

Imagem: o `Dockerfile` da feature (imagem única; este papel roda com `command: ipm-organization-controller`).
