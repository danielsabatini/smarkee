# 0032 — Um projeto de roles por módulo e o papel `ORG_USER_CREATOR`

- **Data:** 2026-10-15
- **Status:** Aceita. Substitui, no que toca ao Executor do User e ao projeto único de roles, as decisões 0014 (`ORG_USER_MANAGER`) e 0027 (um Project Grant único) e resolve o risco registrado na 0028 (roles `ipm.*` ao alcance do Executor do User). Evoluída pela decisão `0084` (organização `operator` e projeto `roles-operator`).

## Contexto

O Project Grant é **por organização**, não por conta de serviço, e o papel de organização `ORG_USER_MANAGER` concede roles de **qualquer** Grant da `register`. Com o SUM (o usuário liga o serviço `ipm`), a role `ipm.*` só pode ser concedida pelo SUM; mas um Executor do User com `ORG_USER_MANAGER`, se comprometido (chave, execução de código no contêiner, dependência), concederia `ipm.*` a qualquer usuário e burlaria o SUM. Testado no Zitadel de dev: o teto de roles é só o Grant, e nenhum papel predefinido cria usuário sem também conceder roles.

## Alternativas (segurança → simplicidade → robustez → disponibilidade)

1. **Aceitar o risco e detectar** (convergência estrita: o Reconciler revogaria roles fora do `desired`). Só detecta, não impede.
2. **Projetos por módulo com Grants e um papel de organização que cria usuários sem conceder roles** (adotada). O Zitadel impede a concessão.
3. Projetos por módulo sem Project Grant (`PROJECT_OWNER`): isola, mas remove o Grant, que é a forma recomendada pelo Zitadel de delegar projeto a outra organização (usuários numa organização, projetos noutra).

## Decisão

- **Um projeto de roles por módulo**, na organização `core`: `roles-core`, `roles-ipm`, `roles-sum` (a aplicação `cli` saiu do `roles-core` para o projeto `clients`, decisão 0034). Cada um é delegado à `register` por **Project Grant** só com as roles de ação. As `*.admin` ficam no projeto do módulo, fora do Grant (não há projeto de administração separado).
- **Papel `ORG_USER_CREATOR`**: papel de organização customizado, com as permissões do `ORG_USER_MANAGER` **sem** `user.grant.read|write|delete`. Entra pelo arquivo `infrastructure/dev/identity/role-permissions.yaml`, que o `identity` carrega com `--config` (cópia integral do `InternalAuthz.RolePermissionMappings` do Zitadel v4.19.4, que o configurado substitui por inteiro, mais esse papel). Em Kubernetes, o mesmo conteúdo vai em `zitadel.configmapConfig` do chart. A cada atualização do Zitadel, o arquivo é comparado com o `defaults.yaml` da nova versão.
- **Papéis dos executores:**

  | Conta | Papéis |
  |---|---|
  | `core-user-executor` | `ORG_USER_CREATOR` na `register`; `PROJECT_GRANT_OWNER` nos Grants de `roles-core` e `roles-sum` |
  | futuro `sum-service-executor` | `PROJECT_GRANT_OWNER` só no Grant de `roles-ipm` |
  | `core-user-observer` | `ORG_OWNER_VIEWER` na `register` |

  `PROJECT_GRANT_OWNER` é limitado pelo Zitadel ao Grant do projeto; sem `user.write`, o do SUM não cria usuário.
- **Código:** o Executor do User recebe `CORE_USER_EXECUTOR_ZITADEL_PROJECT_IDS` (JSON módulo → projeto) e envia cada role ao projeto do seu módulo (primeiro segmento), uma autorização por projeto; módulo fora da lista é rejeitado antes de chamar o Zitadel. O Observer lê as autorizações do usuário em todos os projetos, pela organização `register`. Cada Receiver valida a audience do próprio projeto (`CORE_USER_RECEIVER_AUTH_AUDIENCE` = `roles-core`, `IPM_ORGANIZATION_RECEIVER_AUTH_AUDIENCE` = `roles-ipm`).
- **Cadastro:** o conjunto padrão de roles do usuário cadastrado passa a ser só `core.user.delete` e `core.user.get`. As roles `ipm.organization.*` deixam de ser concedidas no cadastro e chegam pelo SUM, quando o usuário ligar o serviço. Migração `0004-user-platform-roles-core-only.sql`.
- **Operador:** a autorização dele existe em cada projeto que administra (decisão 0031): `roles-core` e `roles-ipm`.

## Consequências

- **Isolamento comprovado:** a credencial do Executor do User não concede role de `ipm`, nem `*.admin`; a do SUM não cria usuário nem concede role de `core`. O estrago de um vazamento fica no que cada executor faz.
- **Regressão temporária:** até o SUM existir, usuários cadastrados não têm `ipm.organization.*` e, portanto, não criam Organizations; só operadores. Verificação no dev: o `Receiver` da Organization passou a exigir a audience de `roles-ipm`.
- **A CLI** precisa pedir a audience de cada projeto no login (`urn:zitadel:iam:org:project:id:<ID>:aud` por projeto); isso entra com os comandos do SUM.
- **Custos assumidos:** manter a cópia do mapeamento de papéis a cada atualização do Zitadel; mais IDs de configuração; recriação dos usuários de teste (o `desired` publicado no NATS tinha as roles antigas, e a migração só ajusta o SSOT).
- **Não resolve** o vazamento em si (proteção e rotação das chaves; o OpenBao, produto futuro da plataforma, trata disso) nem impede que a chave do Executor do User crie e apague usuários, que é a função dele.

## Verificação (Zitadel de dev e descartável, 2026-10-15)

- Descartável (v4.19.4, papel carregado de `--config` YAML): o Executor do User criou usuário e concedeu roles de `core` e `sum`; foi negado em `ipm`; o do SUM concedeu `ipm` e foi negado em `core` e na criação de usuário; token de um usuário com autorização em dois projetos trouxe as duas audiences e os dois claims `urn:zitadel:iam:org:project:<ID>:roles`.
- Dev: com uma conta temporária com os papéis do Executor, `core.user.get` e `sum.ipm.get` foram concedidos; `core.user.admin` e `ipm.organization.admin` (fora do Grant: `400`) e `ipm.organization.get` (outro módulo: `403`) foram negados. Cadastro de três usuários de ponta a ponta com a estrutura nova. `identity/conformance` (13 testes), e2e do User (8 passed, 3 de resiliência pulados), suítes de unidade dos componentes alterados.
- **Não verificado:** o Executor com a chave real tentando conceder `ipm` (a conta temporária reproduz os papéis, não a chave); login do navegador do `sk` com a nova audience; Kubernetes (stg/prd).
