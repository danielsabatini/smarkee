# ipm.role

A **Role** é o catálogo de papéis compostos da plataforma (`.decisions/0083-ipm-permission-ipm-role-e-fim-da-trava-de-deploy.md`): um recurso do módulo `ipm` que pode ser da plataforma (`predefined`, Organization `core`) ou de uma Organization (`custom`, decisão `0092`) e que agrupa permissões atômicas (`<módulo>.<tipo>.<ação>`) sob o padrão de nomenclatura pré-definido `<módulo>.<tipo><Admin|Viewer>` (ex.: `core.accountViewer`, `core.accountAdmin`, `bsm.accountViewer`, `bsm.accountAdmin`, `ipm.organizationViewer`, `ipm.organizationAdmin`, `ipm.userViewer`, `ipm.userAdmin`, `ipm.permissionViewer`, `ipm.permissionAdmin`, `ipm.roleViewer`, `ipm.roleAdmin`, `sum.serviceViewer`, `sum.serviceAdmin`).

Uma Role composta vive **exclusivamente no SSOT da Smarkee**: não cria objetos nem projetos no Zitadel. Quando atribuída a um usuário organizacional (`ipm.user`), ela é expandida em suas permissões atômicas, e alterações no catálogo de `ipm.role` propagam-se assincronamente via NATS para reconciliar os usuários afetados sem necessidade de *redeploy*.

# 1. Estado da implementação

Dois papéis implementados para execução no ambiente de dev (Compose), sobre a **API síncrona** (decisão `0098`). A Role é só dado do SSOT: nasce `Ready`, com `observedGeneration = generation`, e não tem Manager, Reconciler, Observer, Executor nem Controller. O banco `platform` não é mais usado por ela.

| Papel | Projeto | Estado |
|---|---|---|
| API | `api/` (`ipm-role-api`) | API `/v1/ipm/roles`: `POST` 201, `PATCH` 200 e `DELETE` 202, todos com o `Resource`; sem Operation. Leitura por `ipm.role.get`/`ipm.role.list`; escrita por operadores (`ipm.role.admin`), pelo root da Organization ou por membros com `ipm.role.create|update|delete|bind`, com teto de permissões delegáveis, cota de 10 `custom` por Organization e `409 ResourcesAttached` ao excluir role em uso (decisão `0092`). Admite a escrita numa transação (unicidade de `name`, cota, geração, recurso e `desired` no outbox; o `DELETE` remove a linha e publica o tombstone). Mantém o catálogo de Permissions (`manager.desired.ipm.permission.>`). Contrato em `openapi.json` |
| Publisher | `publisher/` (`ipm-role-publisher`) | Publica o outbox no NATS (`manager.desired.ipm.role.>`), com trava de sessão, envelope estrito e `Nats-Msg-Id` |

A migração `0001-role.sql` semeia as 16 Roles pré-definidas (`roleType = predefined`, `resourceId` UUIDv7 fixo, já `Ready`; decisão `0089`). O serviço `ipm-role-migrate` roda e sai.

# 2. Contratos e Configuração

Os contratos estão em `schemas/ipm/role/` com índice em `schemas/ipm.role.index.json`. A referência completa de configuração está em [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md).

> **Diagramas e fluxo de dados pendentes (decisões 0098 e S4):** os SVGs e os `.mmd` de `docs/flow/`, `docs/architecture/`, `docs/state/` e `docs/database/`, e o `docs/IPM-ROLE-DATA-FLOW.md`, ainda mostram o modelo anterior com Receiver, Manager, Operation e plano de dados no banco `platform`. O texto deste README é o vigente.

A CLI é o comando `sk ipm role create|get|list|update|delete` (`clients/cli`).
