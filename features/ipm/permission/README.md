# ipm.permission

A **Permission** é o catálogo operacional de permissões atômicas da plataforma (`.decisions/0083-ipm-permission-ipm-role-e-fim-da-trava-de-deploy.md`): um recurso global do módulo `ipm` sob o formato `<módulo>.<tipo>.<ação>` (ex.: `bsm.account.create`, `ipm.user.bind`, `ipm.permission.admin`) gerenciado pelo Resource Control Loop (`docs/RESOURCE-CONTROL-LOOP.md`).

Cada Permission é reconciliada pelo `ipm-permission-executor` como uma role de projeto no projeto `roles-<módulo>` na organização `core` do Zitadel (`AddProjectRole`, `UpdateProjectRole` e `RemoveProjectRole`), eliminando travas de *redeploy* para criação e evolução de permissões na plataforma. Alterações em permissões com `grantable = true` propagam-se assincronamente via NATS para atualizar os Project Grants das Organizations (`ipm.organization`).

# 1. Estado da implementação

Os seis componentes do loop estão implementados para execução no ambiente de dev (Compose).

| Papel | Projeto | Estado |
|---|---|---|
| Receiver | `receiver/` (`ipm-permission-receiver`) | API `/v1/ipm/permissions`: leitura por `ipm.permission.get`/`ipm.permission.list` e escrita restrita a operadores (`ipm.permission.admin`). Contrato em `openapi.json` |
| Manager | `manager/` (`ipm-permission-manager`) | Consome `requested`, `observed` e `completed`/`failed`; unicidade de `name` em Permissions ativas; migração `0001-permission.sql` semeia as 31 Permissions pré-definidas |
| Publisher | `publisher/` (`ipm-permission-publisher`) | Publica o outbox no NATS (`manager.desired.ipm.permission.>` e `manager.updated.ipm.permission.>`) |
| Reconciler | `reconciler/` (`ipm-permission-reconciler`) | Compara `name`, `description` e `group` (`<módulo>`) e decide `create`, `update` ou `delete` |
| Observer | `observer/` (`ipm-permission-observer`) | Lê as roles de projeto em `roles-<módulo>` no Zitadel (`PROJECT_OWNER_VIEWER`) e publica `observed` |
| Executor | `executor/` (`ipm-permission-executor`) | Cria, atualiza ou remove a role de projeto em `roles-<módulo>` no Zitadel (`PROJECT_OWNER`); revalida cada ação |

# 2. Contratos e Configuração

Os contratos estão em `schemas/ipm/permission/` com índice em `schemas/ipm.permission.index.json`. A referência completa de configuração está em [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).
