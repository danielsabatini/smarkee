# ipm.permission

A **Permission** é o catálogo operacional de permissões atômicas da plataforma (`.decisions/0083-ipm-permission-ipm-role-e-fim-da-trava-de-deploy.md`): um recurso global do módulo `ipm` sob o formato `<módulo>.<tipo>.<ação>` (ex.: `bsm.account.create`, `ipm.user.bind`, `ipm.permission.admin`) gerenciado pelo Resource Control Loop (`docs/loop/RESOURCE-CONTROL-LOOP.md`).

Cada Permission é reconciliada pelo `ipm-permission-controller` como uma role de projeto no projeto `roles-<módulo>` na organização `core` do Zitadel (`AddProjectRole`, `UpdateProjectRole` e `RemoveProjectRole`), eliminando travas de *redeploy* para criação e evolução de permissões na plataforma. Alterações em permissões com `grantable = true` propagam-se assincronamente via NATS para atualizar os Project Grants das Organizations (`ipm.organization`).

Decisões que definem esta feature: `0083` (o que é a Permission), `0096` (Controller unificado) e `0098` (API síncrona e fim da Operation).

# 1. Estado da implementação

Os três papéis estão implementados para execução no ambiente de dev (Compose), na **API síncrona** (decisão `0098`). A CLI é `sk ipm permission create|get|list|update|delete`.

| Papel | Projeto | Estado |
|---|---|---|
| API | `api/` (`ipm-permission-api`) | API `/v1/ipm/permissions`: leitura por `ipm.permission.get`/`ipm.permission.list` e escrita restrita a operadores (`ipm.permission.admin`). Admite a escrita numa transação (unicidade de `name` entre as Permissions ativas, `description` diferente de `name`, geração, recurso e `desired` no outbox); `POST` 201, `PATCH` 200 e `DELETE` 202, com o `Resource`. Contrato em `openapi.json` |
| Publisher | `publisher/` (`ipm-permission-publisher`) | Publica o outbox no NATS (`desired.ipm.permission.>` e `updated.ipm.permission.>`) |
| Controller | `controller/` (`ipm-permission-controller`) | Decisão 0096: lê a role em `roles-<módulo>` (ou `roles-operator`), decide, cria, atualiza ou remove, reobserva e grava estado e `updated` numa só transação. Substitui Reconciler, Observer e Executor |
| Testes e2e | `tests/e2e/` | Black-box: contrato, loop completo e caos (Publisher e Controller) |

A migração `0001-permission.sql` semeia as 31 Permissions pré-definidas; a `0004` leva o tipo à API síncrona.

# 2. Contratos e Configuração

Os contratos estão em `schemas/ipm/permission/` com índice em `schemas/ipm.permission.index.json`. A referência completa de configuração está em [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).
