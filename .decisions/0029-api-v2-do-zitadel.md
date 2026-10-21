# 0029 — API v2 do Zitadel para autorizações e conferência

- **Data:** 2026-10-15
- **Status:** Aceita. Complementa a decisão 0027 (a autorização do usuário passa a usar a API v2) e segue AGENTS §24.2.

## Contexto

Os componentes já criavam, liam e removiam o usuário pela API v2 (`/v2/users`), mas a autorização do usuário no projeto `roles` (role assignment) ainda usava a API v1 de gestão (`/management/v1/users/.../grants`). A documentação do Zitadel trata a v1 como legada ("suportada, mas não evoluída") e manda usar a v2 em integrações novas.

## Decisão

- **Executor e Observer do User** usam o `AuthorizationService` v2 (Connect, `POST /zitadel.authorization.v2.AuthorizationService/<método>`, com `Connect-Protocol-Version: 1`): `CreateAuthorization`, `UpdateAuthorization` (a lista de roles **substitui** a anterior), `DeleteAuthorization` e `ListAuthorizations`. A organização vai no corpo (`organizationId` = `register`); o cabeçalho `x-zitadel-orgid` deixa de ser usado.
- **Project Grant continua sendo o teto das roles.** A v2 não recebe `projectGrantId`; o Zitadel aplica o Grant da organização `register`. Por isso `CORE_ZITADEL_PROJECT_GRANT_ID` / `CORE_USER_EXECUTOR_ZITADEL_PROJECT_GRANT_ID` foram removidas.
- **Idempotência:** criar uma autorização que já existe (`already_exists`, `V3-DKcYh`) é sucesso; apagar uma inexistente já é sucesso no Zitadel. O erro `not_found` do Connect (código textual) é tratado como ausência, além do código numérico `5` do REST.
- **Suíte `identity/conformance`:** usa só a v2: organizações, projetos, roles, Project Grants, aplicações, usuários, autorizações, administradores da instância e da organização (`InternalPermissionService.ListAdministrators`; o Zitadel os chamava de *members*) e política de login (`GET /v2/settings/login`; `allowRegister` ausente = desligado). Nenhuma chamada à API v1 de gestão ou de administração resta no repositório.
- A v2 devolve também os projetos delegados na listagem por organização; a suíte considera só os que a organização possui (`organizationId`). `projectRoleCheck` da v1 chama-se `authorizationRequired` na v2.

## Verificação (2026-10-15)

- Zitadel descartável (v4.19.4, papéis `ORG_USER_CREATOR` + `PROJECT_GRANT_OWNER`): a v2 concedeu a role dentro do Project Grant e **negou** role fora do Grant e de outro projeto; o Executor de outro serviço foi negado; duplicada = `409 already_exists`; atualizar/apagar funcionaram; atualização de role fora do teto negada.
- Dev: Executor e Observer reconstruídos; teste e2e do User passou (8 passed, 3 de resiliência pulados); `identity/conformance` passou (11 testes); testes de unidade, `ruff` e `pyright` limpos.
- **Não verificado:** caminhos de operador (`*.admin`); as chamadas de ativar/desativar autorização da v2; a rota REST `/v2/authorizations` (não existe na v4.19.4; usamos o Connect).
