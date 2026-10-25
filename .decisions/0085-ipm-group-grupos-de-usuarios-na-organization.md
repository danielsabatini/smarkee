# 0085 — `ipm.group` (grupos de usuários da Organization) e concessão exclusiva por `roles`

- **Data:** 2026-10-25
- **Status:** Aceita. Evolui e complementa as decisões `0083` (`ipm.permission`, `ipm.role`) e `0084` (`operator` e `roles-operator`).
- **Origem:** Necessidade de suportar agrupamentos lógicos de usuários por Organization (`ipm.group`) e simplificação do modelo de concessão de acessos: usuários da plataforma passam a receber **exclusivamente `roles`** (e futuramente `groups`), eliminando a atribuição direta de permissões atômicas a usuários.

## Contexto

Na decisão `0083`, o modelo de autorização foi dividido em:
1. `ipm/permission`: permissão atômica (`<módulo>.<tipo>.<ação>`), reconciliada no Zitadel;
2. `ipm/role`: agrupador de permissões atômicas (`<módulo>.<tipo><Admin|Viewer>`), 100% no SSOT da Smarkee;
3. `ipm/user`: usuário da Organization, cujas permissões e roles eram expandidas em permissões atômicas gravadas no `UserGrant` do Zitadel.

Ao avaliar a adição de grupos de usuários e a governança de acesso em escala, foram identificados dois pontos fundamentais:
1. **Concessão direta de permissões atômicas a usuários gera fragmentação e descontrole:** permitir que um usuário receba permissões atômicas avulsas dispersa a política de segurança, dificulta auditorias de compliance e reintroduz concessões ad-hoc difíceis de rastrear. A boa prática de mercado (RBAC consolidado) preconiza que usuários recebam papéis (`roles`), nunca permissões atômicas soltas.
2. **Necessidade de grupos de usuários por Organization (`ipm/group`):** times de clientes (ex.: engenharia, finops, suporte) precisam ser agrupados logicamente para receber conjuntos de `roles` em bloco, sem exigir que cada novo membro seja configurado individualmente.

## Avaliação de alternativas no Zitadel

Uma proposta de utilizar APIs de grupos do Zitadel (`GroupService v2` ou endpoints `/v2/groups` com Actions JS) foi investigada e formalmente rejeitada:
- A API `/zitadel.group.v2.GroupService` e `/v2/groups` **não existe no Zitadel v4.20.0** (retorna `404 Not Found`).
- Actions v1 está deprecada no Zitadel v4 e não possui chamadas de API nativas para grupos.
- Expandir grupos via matriz hardcoded em código de aplicação reintroduziria a trava de *redeploy* (violando a decisão `0083`) e desarmaria o teto de isolamento dos Project Grants no IdP.

## Decisão

### 1. Hierarquia de Autorização da Smarkee

A plataforma estabelece quatro níveis claros e estritos de autorização:

```text
[ipm/permission]  (Permissão atômica: <módulo>.<tipo>.<ação>)
       ▲          Reconciliada no Zitadel (roles-<módulo> ou roles-operator)
       │
   (compõe)
       │
  [ipm/role]      (Grupo de permissões: <módulo>.<papel>)
       ▲          100% no SSOT da Smarkee (zero impacto no IdP)
       │
 (atribuída a)
   ┌───┴───────────────┐
   │                   │
[ipm/group]        [ipm/user]
(Grupo de usuários)  (Usuário da Organization)
```

1. **`ipm/permission` (Permissão atômica):**
   - Catálogo das ações autorizadas (`<módulo>.<tipo>.<ação>`).
   - Única entidade replicada no Zitadel como Project Role.

2. **`ipm/role` (Grupo de permissões / Papel):**
   - Agrupador de permissões atômicas predefinidas e customizadas.
   - Existe exclusivamente no SSOT da Smarkee.

3. **`ipm/group` (Grupo de usuários da Organization — Planejado):**
   - Recurso multitenant pertencente a uma Organization (`organizationId`).
   - Possui `name`, `description`, `roles` e associação de membros (`members`).
   - Existe exclusivamente no SSOT da Smarkee.

4. **`ipm/user` (Usuário da Organization):**
   - Recebe **exclusivamente `roles`** (e futuramente `groups`).
   - **Não recebe permissões atômicas diretas via API/CLI:** a atribuição direta de permissões a usuários é descontinuada em favor do uso exclusivo de `roles`.
   - O Manager de `ipm/user` expande as roles (e futuramente os grupos) nas permissões atômicas correspondentes e grava o resultado no `desired.permissions` do recurso, que o Executor projeta no `UserGrant` do Zitadel.

### 2. Ajuste na CLI `sk ipm user`

- Remoção das opções `--permission` e `--no-permissions` dos comandos `sk ipm user create` e `sk ipm user update`.
- A atribuição de acessos na CLI é feita exclusivamente via `--role` (repetível) e `--no-roles`.
- A visualização (`sk ipm user get` e `sk ipm user list`) continua exibindo as roles atribuídas (`roles`) e as permissões atômicas resultantes (`permissions`).

## Consequências

- **Governança limpa e auditável:** nenhuma concessão avulsa de permissões atômicas a usuários; todas as concessões passam por papéis nomeados (`ipm/role`).
- **Alinhamento para `ipm/group`:** quando o recurso `ipm/group` for implementado, o usuário poderá pertencer a grupos que por sua vez contêm roles, mantendo a expansão idempotente e transparente para o Zitadel.
- **Zero impacto nos nós periféricos:** os Receivers das APIs continuam validando apenas as permissões atômicas assinadas no JWT pelo Zitadel.
