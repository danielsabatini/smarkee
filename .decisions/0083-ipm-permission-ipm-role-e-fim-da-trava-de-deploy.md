# 0083 — `ipm.permission`, `ipm.role` e evolução de catálogos sem trava de redeploy

- **Data:** 2026-10-24
- **Status:** Aceita. Evolui e revisa as decisões `0077` (regra de `ipm.user.bind`), `0079` (catálogo do SUM) e `0081` (catálogo do Grant da Organization como enum estático em schema). Complementada pelas decisões `0084` (organização `operator` e projeto `roles-operator`) e `0104` (permissão `.operate` e separação semântica estrita entre Permissão e Role).
- **Origem:** Reavaliação arquitetural (§25.1 do `AGENTS.md`) solicitada pelo responsável do projeto para:
  1. Eliminar a trava operacional que exigia alterar código/schema e refazer *deploy* da aplicação para cadastrar uma nova permissão;
  2. Separar claramente o que é **permissão atômica** (`ipm/permission`), o que é **papel/conjunto de permissões** (`ipm/role`, no padrão predefinido do Google Cloud IAM `<módulo>.<tipo><Admin|Viewer>`) e como o **`ipm/user`** consome ambos mantendo no Zitadel exclusivamente permissões atômicas;
  3. Tornar `ipm.user.bind` requisito estrito para atribuir ou alterar permissões/roles de um usuário.

## Avaliação das decisões anteriores (§25.1)

| Decisão anterior | Limitação identificada com a evolução da plataforma | Evolução adotada |
|---|---|---|
| **0081** — Catálogo `grantablePermission` como enum estático em `schemas/ipm/definitions.v1.schema.json` | Criar ou aprovar uma nova permissão exigia alterar JSON Schema, regerar modelos e fazer *redeploy* de múltiplos componentes. | **`ipm/permission`** passa a ser um recurso operacional da plataforma no SSOT, gerenciado pelo operador na organização `core` e propagado de forma assíncrona via NATS. |
| **0077** — Sem `ipm.user.bind`, o solicitante ainda podia atribuir/retirar permissões que ele mesmo possuísse | Permitia delegação implícita de acessos por usuários que tinham apenas `ipm.user.create` ou `ipm.user.update`, sem terem recebido o poder explícito de gerenciar acessos (`bind`). | **`ipm.user.bind` passa a ser obrigatório** para qualquer atribuição ou alteração de permissões/roles em um usuário (exceto quando o usuário nasce sem permissões e nenhuma permissão/role é alterada). |

## Decisão

### 1. Separação estrita entre Zitadel e Smarkee

- **No Zitadel existem exclusivamente permissões atômicas** (`<módulo>.<tipo>.<ação>`, ex.: `ipm.user.create`, `bsm.account.get`), registradas como chaves de role dentro do projeto do respectivo módulo (`roles-core`, `roles-sum`, `roles-ipm`, `roles-bsm` — decisão `0032`).
- **Nunca são criadas roles compostas no Zitadel** (nem como projetos separados por role, nem como chaves compostas no projeto do módulo).
- **`ipm/role` existe 100% no SSOT da Smarkee** como agrupador de permissões atômicas.
- **`ipm/user` expande as `roles` em permissões atômicas:** quando um usuário recebe uma ou mais `ipm/role` (ex.: `ipm.userAdmin`), o Manager do `ipm/user` resolve o conjunto resultante de permissões atômicas no `desired`, e o Executor do `ipm/user` grava **somente as permissões atômicas** no `UserGrant` do Zitadel.

### 2. `ipm/permission` (Catálogo operacional com Loop no Zitadel)

- Recurso operado pelo operador da plataforma (`ipm.permission.create|get|list|update|delete|admin`). Usuários das organizações possuem leitura (`ipm.permission.get|list`).
- Possui o ciclo completo do Resource Control Loop (Receiver, Manager, Observer, Reconciler, Executor).
- O **Executor de `ipm/permission`** garante que a permissão atômica (`<módulo>.<tipo>.<ação>`) exista cadastrada no projeto `roles-<módulo>` do Zitadel.
- Quando uma permissão delegável às organizações é criada ou atualizada, a mudança é publicada no NATS e consumida de forma assíncrona e desacoplada por `ipm/organization` para atualizar os `ProjectGrants`.

### 3. `ipm/role` e Roles Predefinidas no padrão `<módulo>.<tipo><Admin|Viewer>`

- Recurso 100% interno à Smarkee (sem comunicação com o Zitadel), mantendo o contrato assíncrono no NATS.
- Nomenclatura das roles predefinidas segue o padrão `<módulo>.<tipo><Admin|Viewer>` (sem o prefixo `roles/`), contemplando todas as features da plataforma:
  - `core.accountViewer`, `core.accountAdmin`
  - `sum.serviceViewer`, `sum.serviceAdmin`
  - `ipm.organizationViewer`, `ipm.organizationAdmin`
  - `ipm.userViewer`, `ipm.userAdmin`
  - `ipm.permissionViewer`, `ipm.permissionAdmin`
  - `ipm.roleViewer`, `ipm.roleAdmin`
  - `bsm.accountViewer`, `bsm.accountAdmin`
- Alterações em uma `ipm/role` são publicadas no NATS; o Manager do `ipm/user` consome o evento de forma assíncrona e recalcula as permissões atômicas dos usuários que referenciam aquela role.

### 4. Regra estrita de `ipm.user.bind`

- Atribuir permissões/roles na criação de um usuário (`create`) ou alterar as permissões/roles de um usuário existente (`update`) exige que o solicitante tenha poder de `bind`:
  - O operador (`ipm.user.admin`) e o dono da Organization (`root`) possuem `bind` por definição;
  - Qualquer usuário da Organization (`Standing.MEMBER`) **precisa possuir explicitamente a permissão `ipm.user.bind`** para atribuir ou alterar qualquer permissão ou role. Sem `ipm.user.bind`, qualquer tentativa de atribuir permissões na criação ou alterar a lista de permissões na atualização é recusada com `403 Forbidden`.
