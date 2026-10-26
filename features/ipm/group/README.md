# ipm.group

O **Grupo** (`ipm.group`, decisão `.decisions/0088-ipm-group-grupos-de-usuarios-por-organizacao.md`) é o agrupador de papéis compostos (`ipm.role`) escopado por Organization (`ipm.organization`): permite definir conjuntos de `roles` por equipe ou função dentro de uma Organization e atribuí-los aos seus usuários (`ipm.user`).

Um Grupo vive **no SSOT da Smarkee** (intenção, operações e estado observado em `ipm.group`) e no **banco de plano de dados `platform`** (tabelas `ipm.group` e `ipm.group_role`, decisão `0086`): não cria objetos no Zitadel. Quando um usuário organizacional (`ipm.user`) referencia um grupo em `groups`, o Manager e o Reconciler de `ipm/user` expandem as `roles` do grupo em permissões atômicas, e alterações no `desired` de `ipm.group` propagam-se assincronamente via NATS para reconciliar os usuários afetados no Zitadel.

# 1. Estado da implementação

Os seis componentes do loop estão implementados para execução no ambiente de dev (Compose).

| Papel | Projeto | Estado |
|---|---|---|
| Receiver | `receiver/` (`ipm-group-receiver`) | API `/v1/ipm/groups`: escopo por `organizationId` (operador, dono da Organization ou membro), exigência de `ipm.group.bind` para atribuir/alterar `roles`, cota por Organization e bloqueio de `DELETE` com `409 ResourcesAttached` se houver usuários associados. Contrato em `openapi.json` |
| Manager | `manager/` (`ipm-group-manager`) | Consome `requested`, `observed` e `completed`/`failed`; unicidade de `name` por `organizationId` e cota sob trava consultiva no SSOT |
| Publisher | `publisher/` (`ipm-group-publisher`) | Publica o outbox no NATS (`manager.desired.ipm.group.>` e `manager.updated.ipm.group.>`) |
| Reconciler | `reconciler/` (`ipm-group-reconciler`) | Compara `name`, `description`, `roles` e `deletionProtection` e decide `create`, `update` ou `delete` |
| Observer | `observer/` (`ipm-group-observer`) | Lê o estado do Grupo no banco `platform` (`ipm.group` e `ipm.group_role`, papel somente `SELECT`) e publica `observed` |
| Executor | `executor/` (`ipm-group-executor`) | Grava ou remove, em transação, o estado do Grupo no banco `platform` (único com escrita); revalida cada ação |

# 2. Contratos e Configuração

Os contratos estão em `schemas/ipm/group/` com índice em `schemas/ipm.group.index.json`. A referência completa de configuração está em [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) e o fluxo de dados em [`docs/IPM-GROUP-DATA-FLOW.md`](docs/IPM-GROUP-DATA-FLOW.md).
