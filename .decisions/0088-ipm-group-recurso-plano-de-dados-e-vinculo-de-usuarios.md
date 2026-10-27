# 0088 — `ipm.group`: recurso, plano de dados no banco `platform` e vínculo com usuários

- **Data:** 2026-10-25
- **Status:** Aceita. **Parcialmente revogada pela decisão `0099`:** o plano de dados no banco `platform` (e o Executor/Observer/Reconciler de grupo) deixou de existir; o restante (identificação, nome, `roles`, vínculo com usuários, cota, `bind`) permanece. Evolui e detalha as decisões `0085` (`ipm.group` e concessão exclusiva por `roles`) e `0086` (banco `platform` para planos de dados multi-tenant).
- **Origem:** Planejamento e especificação dos requisitos de grupos de usuários (`ipm.group`) na Organization e sua integração com `ipm.user` e o provedor de identidade (Zitadel).

## Contexto

A decisão `0085` estabeleceu que a concessão de acessos a usuários (`ipm.user`) passa a ser feita exclusivamente por `roles` (e futuramente por `groups`), e introduziu o recurso `ipm.group`. Como o Zitadel v4.20.0 não possui API nativa para grupos de usuários organizacionais (`/v2/groups` ou `GroupService v2` retornam `404`), a governança e o ciclo de vida dos grupos vivem na plataforma Smarkee.

A decisão `0086` criou o banco relacional multi-tenant `platform` para persistir o estado real de recursos da plataforma fora do SSOT, tendo `ipm.role` como primeira adoção e prevendo explicitamente `ipm.group`.

## Decisão

### 1. Identificação e Nomenclatura do Grupo
- **Identificador de recurso (`resourceId`):** UUID v7 opaco e imutável.
- **Escopo e Multi-tenancy:** todo grupo pertence estritamente a uma Organization (`organizationId`), imutável após a criação.
- **Nome do Grupo (`name`):** slug curto e semântico (ex.: `finops`, `devops`, `support-l2`), padronizado por `^[a-z][a-z0-9-]{1,61}[a-z0-9]$`.
  - Único por Organization: `UNIQUE (organization_id, name)`.
  - **Imutável após a criação:** não é permitido renomear o grupo via `PATCH` (apenas `description`, `roles`, `deletionProtection` e `reconciliation` são mutáveis). Para mudar o nome, exclui-se e cria-se outro grupo.
  - O sufixo de domínio do IdP não é gravado no recurso, garantindo portabilidade entre ambientes e independência de renomeação da Organization.

### 2. Plano de Dados no Banco `platform` (Decisão 0086)
- O SSOT (`ssot.ipm.group_resource` e `ssot.ipm.group_operation`) registra o ciclo de vida e intenção (`desired`).
- O plano de dados multi-tenant reside no banco **`platform`** sob o schema `ipm`:
  - `ipm.group`: `resource_id`, `organization_id`, `name`, `description`, `deletion_protection`, `created_at`, `updated_at`.
  - `ipm.group_role`: `group_id` (FK `ipm.group` `ON DELETE CASCADE`), `role_name`.
- O **Executor de `ipm/group`** grava exclusivamente no banco `platform` com o papel `ipm_group_executor`.
- O **Observer de `ipm/group`** lê exclusivamente do banco `platform` com o papel `ipm_group_observer`.
- Nenhum papel do SSOT conecta no banco `platform`, e o Executor/Observer não conectam no SSOT.

### 3. Concessão Exclusiva por `roles` no Grupo
- Um `ipm/group` recebe exclusivamente `roles` (lista ordenada sem duplicatas de `roleName` delegáveis à Organization).
- Grupos **não recebem permissões atômicas soltas**.
- A atribuição ou alteração de `roles` em um grupo exige a permissão `ipm.group.bind`.
- O Receiver e o Manager validam que todas as `roles` constam no catálogo de roles delegáveis àquela Organization (`outside_roles_catalog`).

### 4. Vínculo Usuário ↔ Grupos em `ipm.user`
- A associação pertence ao usuário: o recurso `ipm.user` ganha o campo opcional `groups` (lista de `groupName` da mesma Organization).
- Atribuir ou alterar `groups` em um usuário exige a permissão `ipm.user.bind` (pois concede indiretamente as roles dos grupos).
- **Projeção no IdP:** o Executor de `ipm/user` grava a lista de grupos no metadata do usuário no Zitadel (`/v2/users/{id}/metadata`), sob a chave `groups` em base64 (ex.: JSON `["devops", "finops"]`).
- O Observer de `ipm/user` lê a chave `groups` do metadata e preenche `observed.groups`.

### 5. Expansão Transitiva e Rollout Reativo
- O Manager de `ipm/user` calcula as permissões efetivas do usuário pela união das roles diretas e das roles de todos os grupos ativos do usuário na mesma Organization:
  $$\text{roles efetivas} = \text{user.roles} \cup \bigcup_{g \in \text{user.groups}} g.\text{roles}$$
- As roles efetivas são expandidas nas permissões atômicas delegáveis (`desired.permissions`), que o Executor de `ipm/user` projeta no `UserGrant` do Zitadel.
- **Rollout Reativo:** o Manager de `ipm/user` assina eventos `desired` de `ipm.group` (`manager.desired.ipm.group.*.changed`). Quando as roles de um grupo mudam, o Manager recalcula automaticamente as permissões de todos os usuários daquela Organization associados àquele grupo, disparando atualização no Zitadel sem intervenção manual.

### 6. Proteção de Exclusão Segura
- **Exclusão de grupo com usuários associados é recusada:** um grupo não pode ser excluído se houver usuários da Organization com ele atribuído em `groups`. O Receiver e o Manager de `ipm/group` rejeitam a operação com conflito (`409 Conflict`, `ResourcesAttached`).
- **Exclusão de Organization com grupos é recusada:** uma Organization não pode ser excluída enquanto contiver grupos (ou usuários) ativos.
- **`deletionProtection`:** nasce `false` por padrão no grupo (alinhado a `ipm.user`, decisão `0077`).

### 7. Cotas e Autorização (Standing)
- **Cota:** limite inicial de 10 grupos por Organization para não-operadores (`IPM_GROUP_RECEIVER_API_GROUP_QUOTA`), garantido sob advisory lock no SSOT.
- **Standing:** aceita o Operador (`ipm.group.admin`), o Root (dono da Organization confirmado via `ipm/organization`) ou um usuário membro da Organization com a permissão exigida (`ipm.group.get|list|create|update|delete|bind`), confirmado via consulta ao Receiver de `ipm/user`.
- **Permissões predefinidas:**
  - `ipm.groupViewer`: `["ipm.group.get", "ipm.group.list"]`
  - `ipm.groupAdmin`: `["ipm.group.bind", "ipm.group.create", "ipm.group.delete", "ipm.group.get", "ipm.group.list", "ipm.group.update"]`

## Consequências

- Implementação da feature `features/ipm/group` no padrão do template.
- Adição das tabelas `ipm.group` e `ipm.group_role` e papéis de banco em `platform`.
- Evolução de `schemas/ipm/user/` e da feature `features/ipm/user` para suportar `groups` e expansão transitiva.
- Adição dos comandos `sk ipm group` e opções `--group` / `--no-groups` em `sk ipm user`.
