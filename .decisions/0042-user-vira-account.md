# 0042 — O recurso `core.user` passa a se chamar `core.account`

- **Data:** 2026-10-16
- **Status:** Aceita e implementada. Renomeia o tipo definido na decisão 0014 (e citado nas demais); as decisões antigas ficam como estão, com `user` onde o nome era esse.

## Contexto

O tipo do módulo `core` se chamava `user`, e o `ipm` ganharia um vínculo entre pessoas e Organizations (os administradores). Dois "user" na plataforma (e o "user" do Zitadel, uma terceira coisa) confundiam o que é cada um. `register` descreve a ação de se cadastrar, e não o recurso; os demais tipos são substantivos (`organization`, `service`).

## Decisão

- **O tipo é `account`** (a conta da pessoa na plataforma): `core.account`, `/v1/core/accounts`, `sk account get|delete`. O cadastro continua sendo `sk register`, uma ação de topo.
- **"User" fica só para o que é do Zitadel** (usuário, na organização `register`, que é a conta vista do provedor de identidade): `IdentityUser`, `create_user` e `delete_user` do Executor, `userinfo`.
- **O que mudou de nome**, em todo o repositório:
  - pasta e componentes: `features/core/user` → `features/core/account`; pacotes `core_account_*`; serviços, contêineres e imagens `core-account-*`; variáveis `CORE_ACCOUNT_*`;
  - contratos: `schemas/core/account`, `schemas/core.account.index.json`, os modelos (`Account*`), o campo `userState` → `accountState` e `ownerUserId` → `ownerAccountId` (e `owner_user_id` → `owner_account_id`) em `ipm.organization` e `sum.service`;
  - mensageria: Subjects `*.core.account.*` e consumers `core-account-*`;
  - SSOT: tabelas `core.account`, `core.account_operation`, `core.account_action_result` e `core.account_outbox`, views `core.account_v1` e `core.account_operation_v1`, papéis `core_account_*`;
  - Zitadel: roles `core.account.get|delete|admin` no `roles-core` (no lugar de `core.user.*`), no Project Grant da `register` e na autorização do operador; contas de serviço `core-account-executor` e `core-account-observer` (mesmos IDs e mesmas chaves; só os arquivos do volume mudaram de nome);
  - CLI: `sk account get|delete` (antes `sk register get|delete`); `sk register` volta a ser um comando simples;
  - ferramentas: o `smarkee-dev-cleanup` e a conformância de identidade.
- **Sem migração de dados:** o dev estava sem dados; os esquemas dos três módulos foram recriados com os nomes novos.

## Justificativa

- **Simplicidade:** um nome por conceito: `account` na plataforma, `administrator` para quem administra a Organization (a definir; antes "member", revisto pela decisão 0076) e `user` só no Zitadel.
- **Custo:** o projeto ainda não teve release, então renomear agora é barato; depois, cada nome vira contrato com consumidores.

## Consequências

- **Quebra de contrato** (rota, Subjects, roles, campos): sem consumidores externos, e o token de quem estava logado deixa de ter as roles `core.user.*` (entrar de novo).
- As decisões 0010 a 0040 continuam com o nome antigo no texto; para ler uma delas, `user` = `account`.
