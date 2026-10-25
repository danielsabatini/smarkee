# ipm.role

A **Role** é o catálogo de papéis compostos da plataforma (`.decisions/0083-ipm-permission-ipm-role-e-fim-da-trava-de-deploy.md`): um recurso global do módulo `ipm` que agrupa permissões atômicas (`<módulo>.<tipo>.<ação>`) sob o padrão de nomenclatura pré-definido `<módulo>.<tipo><Admin|Viewer>` (ex.: `core.accountViewer`, `core.accountAdmin`, `bsm.accountViewer`, `bsm.accountAdmin`, `ipm.organizationViewer`, `ipm.organizationAdmin`, `ipm.userViewer`, `ipm.userAdmin`, `ipm.permissionViewer`, `ipm.permissionAdmin`, `ipm.roleViewer`, `ipm.roleAdmin`, `sum.serviceViewer`, `sum.serviceAdmin`).

Uma Role composta vive **exclusivamente no SSOT da Smarkee**: não cria objetos nem projetos no Zitadel. Quando atribuída a um usuário organizacional (`ipm.user`), ela é expandida em suas permissões atômicas, e alterações no catálogo de `ipm.role` propagam-se assincronamente via NATS para reconciliar os usuários afetados sem necessidade de *redeploy*.

# 1. Estado da implementação

Os seis componentes do loop estão implementados para execução no ambiente de dev (Compose).

| Papel | Projeto | Estado |
|---|---|---|
| Receiver | `receiver/` (`ipm-role-receiver`) | API `/v1/ipm/roles`: leitura por `ipm.role.get`/`ipm.role.list` e escrita restrita a operadores (`ipm.role.admin`). Contrato em `openapi.json` |
| Manager | `manager/` (`ipm-role-manager`) | Consome `requested`, `observed` e `completed`/`failed`; unicidade de `name` em Roles ativas; migração `0001-role.sql` semeia as 14 Roles pré-definidas |
| Publisher | `publisher/` (`ipm-role-publisher`) | Publica o outbox no NATS (`manager.desired.ipm.role.>` e `manager.updated.ipm.role.>`) |
| Reconciler | `reconciler/` (`ipm-role-reconciler`) | Compara `name`, `description` e `permissions` e decide `create`, `update` ou `delete` |
| Observer | `observer/` (`ipm-role-observer`) | Lê o estado local em disco (`/var/tmp/ipm-role`, somente leitura) e publica `observed` |
| Executor | `executor/` (`ipm-role-executor`) | Grava atomicamente ou remove o estado local da Role em `/var/tmp/ipm-role`; revalida cada ação |

# 2. Contratos e Configuração

Os contratos estão em `schemas/ipm/role/` com índice em `schemas/ipm.role.index.json`. A referência completa de configuração está em [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).
