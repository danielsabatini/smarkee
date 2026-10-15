# 0027 — Usuários cadastrados na organização `register`, com roles por Project Grant

- **Data:** 2026-10-14
- **Status:** Aceita. Revisa as decisões 0010 e 0014 no que diz respeito à organização dos usuários e à autorização deles.
- **Estrutura de projetos e papéis:** a decisão 0032 substitui o projeto único de roles por um por módulo (`roles-core`, `roles-ipm`, `roles-sum`) e o papel `ORG_USER_MANAGER` do Executor por `ORG_USER_CREATOR` mais `PROJECT_GRANT_OWNER` por Grant.
- **API e configuração:** a decisão 0029 trocou a API v1 de autorizações pela v2; o Executor deixou de usar `projectGrantId` e `CORE_ZITADEL_PROJECT_GRANT_ID` foi removida (o Project Grant continua sendo o teto das roles, no Zitadel).
- **Nomes das roles:** os nomes citados aqui (`organization.*`, `user.*`, `platform.admin`) foram substituídos pelo padrão da decisão 0028 (`ipm.organization.*`, `core.user.*`, `*.admin`).

## Contexto

A organização `core` reunia o projeto das roles e os usuários cadastrados. A decisão 0026 criou a organização `register` e deixou a separação para esta decisão. Uma primeira versão concedia as roles pelo contexto da `core`, o que exigia que o Executor tivesse permissão de gerenciar autorizações na `core` e, portanto, pudesse conceder qualquer role do projeto, inclusive `platform.admin`.

## Decisão

- **Usuários cadastrados vivem na organização `register`.** O Executor do User cria o usuário nela (`organization.orgId` no `POST /v2/users/human`); o `resourceId` continua sendo o ID do usuário.
- **A organização `core` fica só com o projeto `roles`** (roles, aplicação `cli`) e com o Project Grant abaixo. Não tem usuários cadastrados nem contas de serviço.
- **Project Grant `roles` → `register`:** o projeto `roles` é delegado à organização `register` com **somente as roles de ação do usuário cadastrado** (`organization.create|get|list|update|delete`, `user.get|delete`). `platform.admin` **não** é delegável: ele continua sendo concedido pela `core` aos operadores, por autorização externa (decisão 0010).
- **Autorização do usuário:** o Executor cria a autorização **no contexto da `register`**, com `projectId` e `projectGrantId`. O Zitadel recusa qualquer role fora do Project Grant. O token traz `aud` do projeto e o claim `urn:zitadel:iam:org:project:<ID>:roles`, com a `register` como organização do valor; o Receiver lê só as chaves das roles.
- **Contas de serviço com papel só na `register`** (menor privilégio). Continuam cadastradas na `core`, mas sem nenhum papel nela:

  | Conta | Papel na `register` |
  |---|---|
  | `core-user-executor` | `ORG_USER_MANAGER` (criar e remover usuários e gerir as autorizações) |
  | `core-user-observer` | `ORG_OWNER_VIEWER` (leitura) |

- **Configuração:** Executor: `register_organization_id` e `project_grant_id`; Observer: `register_organization_id`. Na feature: `CORE_ZITADEL_REGISTER_ORGANIZATION_ID` e `CORE_ZITADEL_PROJECT_GRANT_ID` (além de `CORE_ZITADEL_PROJECT_ID`). O ID da organização `core` deixa de ser configuração dos componentes.
- **Autorizações na `core`:** no projeto `roles`, a organização `core` só tem a autorização `platform.admin` dos operadores. Usuários cadastrados não têm autorização no contexto da `core`; as autorizações que a primeira versão desta decisão criou lá foram removidas.
- **Projeto `users` removido:** o projeto da decisão 0026 não tinha função e foi removido. A organização `register` fica sem projeto próprio.

## Justificativa

- **Teto de privilégio:** mesmo comprometido, o Executor só consegue conceder roles do Project Grant; `platform.admin` fica fora por construção.
- **Menor privilégio:** Executor e Observer não têm papel algum na `core`; o dano de uma chave vazada fica nos usuários cadastrados.
- Nada muda para a CLI, o Receiver nem o Manager: audience, `resourceId` e chaves de role são os mesmos.
- É o mecanismo que a decisão 0010 já previa para a Organization (Project Grant com roles delegáveis).

## Verificação (Zitadel de dev, 2026-10-14)

- Com as chaves reais das contas de serviço e só os papéis acima: o Executor criou o usuário na `register`, pediu o link de senha, criou a autorização pelo Project Grant e removeu o usuário; `platform.admin` foi recusado (`Project.Role.NotFound`); o Executor foi negado na `core` (`membership not found`); o Observer leu o usuário e as autorizações.
- Usuário de máquina da `register` com autorização pelo Project Grant: o token trouxe `aud = [<ID do projeto roles>]` e o claim de roles.
- O teste e2e do User passou com essa topologia (8 testes; os 3 de resiliência não foram executados).
- **Não verificado:** o login no navegador (`sk auth login`) de um usuário humano da `register`. O nome de login terá o sufixo da organização (`@register.<domínio>`), e é preciso confirmar o fluxo com a verificação de role.

## Consequências

- **Usuários existentes em dev** (criados na `core`) não migram: o ID é único na instância. Eles foram removidos da `core`. Os cadastrados antes da decisão 0025 não são recriados pelo loop: o `desired` deles no stream não tem `platformRoles`, e o Executor rejeita a ação (`Rejected`, sem retentativa). Em dev, precisam ser removidos do SSOT e se cadastrar de novo (`sk register`).
- Roles novas para o usuário cadastrado exigem atualizar o Project Grant (`core`) além de `CORE_USER_MANAGER_PLATFORM_ROLES`.
- Em stg e prd, a `register` e o Project Grant devem nascer assim.
