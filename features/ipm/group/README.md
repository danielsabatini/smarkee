# ipm.group

O **Grupo** (`ipm.group`, decisão `.decisions/0088-ipm-group-grupos-de-usuarios-por-organizacao.md`) é o agrupador de papéis compostos (`ipm.role`) escopado por Organization (`ipm.organization`): permite definir conjuntos de `roles` por equipe ou função dentro de uma Organization e atribuí-los aos seus usuários (`ipm.user`).

Um Grupo vive **exclusivamente no SSOT da Smarkee** (tabela `ipm.group`): não cria objetos no Zitadel nem usa o banco `platform`. Quando um usuário organizacional (`ipm.user`) referencia um grupo em `groups`, o Manager e o Reconciler de `ipm/user` expandem as `roles` do grupo em permissões atômicas, e alterações no `desired` de `ipm.group` propagam-se assincronamente via NATS para reconciliar os usuários afetados no Zitadel.

# 1. Estado da implementação

Dois papéis implementados para execução no ambiente de dev (Compose), sobre a **API síncrona** (decisão `0098`). O Grupo é só dado do SSOT: nasce `Ready`, com `observedGeneration = generation`, e não tem Manager, Reconciler, Observer, Executor nem Controller. O banco `platform` não é mais usado por ele.

| Papel | Projeto | Estado |
|---|---|---|
| API | `api/` (`ipm-group-api`) | API `/v1/ipm/groups`: `POST` 201, `PATCH` 200 e `DELETE` 202, todos com o `Resource`; sem Operation. Escopo por `organizationId` (operador, dono da Organization ou membro), exigência de `ipm.group.bind` para atribuir/alterar `roles` (dentro do catálogo de Roles), cota por Organization e `409 ResourcesAttached` ao excluir grupo com usuários associados. Admite a escrita numa transação (unicidade de `name` por Organization, cota, geração, recurso e `desired` no outbox; o `DELETE` remove a linha e publica o tombstone). Mantém o catálogo de Roles (`manager.desired.ipm.role.>`). Contrato em `openapi.json` |
| Publisher | `publisher/` (`ipm-group-publisher`) | Publica o outbox no NATS (`manager.desired.ipm.group.>`), com trava de sessão, envelope estrito e `Nats-Msg-Id` |

# 2. Contratos e Configuração

Os contratos estão em `schemas/ipm/group/` com índice em `schemas/ipm.group.index.json`. A referência completa de configuração está em [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md). O fluxo de dados completo e os diagramas de arquitetura, banco de dados e estados estão em [`docs/IPM-GROUP-DATA-FLOW.md`](docs/IPM-GROUP-DATA-FLOW.md).

A CLI é o comando `sk ipm group create|get|list|update|delete` (`clients/cli`).
