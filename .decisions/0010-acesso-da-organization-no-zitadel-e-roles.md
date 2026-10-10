# 0010 — Acesso da Organization no Zitadel e roles da plataforma

- **Data:** 2026-10-09
- **Status:** Aceita. Revisada em 2026-10-10: o criador autenticado é o dono; o projeto fica na organização `core`; roles por ação.

## Contexto

Uma Organization só pode ser criada por um usuário registrado e autenticado (decisões 0013 e 0014). O criador passa a ser o dono dela e deve conseguir operar com o mesmo `sk auth login`. Duas formas de dar acesso foram avaliadas:

1. um projeto e uma aplicação `cli` dentro de cada organização do Zitadel;
2. um único projeto da plataforma, delegado a cada organização.

## Decisão

- **Projeto único `smarkee`, na organização `core`** (a organização de sistema da plataforma, decisão 0014), com todas as roles e uma aplicação nativa `cli` por ambiente (decisão 0007), usada por todas as Organizations. A organização `smarkee` do Zitadel fica **só com operadores e contas administrativas da instância**, separada de tudo que é da plataforma.
- **Configuração do projeto:** roles no token (`projectRoleAssertion`) e **verificação de role na autenticação** (`projectRoleCheck`): só autentica na aplicação quem tem ao menos uma role no projeto. A aplicação `cli` emite **access token JWT** (a API valida pelo JWKS) com as roles no token.
- **Roles por ação** (uma por operação), mais uma role de escopo para operadores:

  | Role | Uso |
  |---|---|
  | `organization.create`, `organization.get`, `organization.list`, `organization.update`, `organization.delete` | Capacidade sobre Organizations |
  | `user.get`, `user.delete` | Capacidade sobre o próprio User |
  | `platform.admin` | Operadores: agem em qualquer Organization e não têm cota |

  A role diz **o que** o usuário pode fazer; o **dono guardado na plataforma** (`ownerUserId`) diz **em quais** Organizations. O usuário cadastrado recebe, na criação, o conjunto de roles de ação (`platformAccess = granted` no User, decisão 0014). A API exige a role da ação em cada rota. Os operadores (usuários da organização `smarkee`) recebem `platform.admin` por **autorização externa** no projeto da organização `core`.
- **Quem pode criar uma Organization:** o usuário autenticado, com **e-mail verificado** e a role `organization.create`, dentro da **cota por dono** (padrão 1, configurável). `platform.admin` não tem cota.
  - A cota é aplicada **no Manager**, na mesma unidade atômica do pedido, com trava consultiva por dono. A pré-checagem da API é só conveniência e não garante o limite com criações concorrentes.
  - Cada Organization vira namespace no OpenBao e no Kubernetes; sem cota, qualquer conta criaria organizações sem limite.
- **Nomes reservados** (`core`, `smarkee` e uma lista da plataforma) são rejeitados como `validation`.
- **Dono:** o contrato da Organization tem `ownerUserId`, o `resourceId` do User autenticado que criou (`writer = server`, imutável, vindo do `sub` do token). Não há dados pessoais no contrato da Organization.
- Na criação de uma Organization, o Executor aplica no Zitadel, nesta ordem e cada passo de forma idempotente:
  1. a organização, com `organization_id = resourceId` (decisão 0006);
  2. o **Project Grant** do projeto `smarkee` para a organização, com as roles delegáveis. Inicialmente `organization.get` e `organization.list`, até existirem membros de uma Organization (módulo `ipm`).

  O Executor da Organization **não cria usuários nem autoriza o dono**: o dono já existe (cadastro) e já tem as roles de ação.
- O `sk organization create --wait` devolve `organizationId`, nome e fase. O dono entra com o mesmo `sk auth login`, na mesma aplicação `cli`.

## Verificado no Zitadel v4.19.4 (dev, 2026-10-10)

- O token da aplicação `cli` é JWT, com `aud = [<ID do projeto>]` e o claim `urn:zitadel:iam:org:project:<ID do projeto>:roles = {"<role>": {"<ID da organização dona do projeto>": "<domínio>"}}`. Numa autorização externa, o ID dentro do claim é o da **organização dona do projeto** (`core`), e não o da organização do usuário. **O token não identifica a Organization da plataforma nem o pertencimento a ela:** quem decide isso é o `ownerUserId` guardado na plataforma.
- A autorização externa de um usuário da organização `smarkee` num projeto da organização `core` funciona.

## Justificativa

- Um projeto por organização inverteria a delegação: cada organização seria dona das próprias roles, as roles seriam duplicadas e as APIs teriam de aceitar a audience de N projetos.
- O projeto na organização `core` (e não na `smarkee`) mantém a organização dos operadores livre de recursos da plataforma e dispensa um Project Grant só para o Executor de User: o `core-user-executor` autoriza os usuários no projeto da própria organização, sem privilégio entre organizações.
- Roles por ação permitem à API exigir a capacidade exata de cada rota; a role de escopo `platform.admin` evita misturar "o que" com "em quê".
- Criar a Organization por um usuário já autenticado dispensa dados pessoais nas mensagens da Organization e tira do Executor a criação de usuários.

## Consequências

- O Executor da Organization é a service account `core-organization-executor`, na organização `core`, com o papel de **instância** `IAM_ORG_MANAGER` (verificado: cria organização com ID informado e Project Grant). Esse papel também lê usuários de outras organizações; estreitar com um papel customizado antes de prd (decisão 0011).
- O ID do projeto `smarkee` e as chaves das roles são configuração do serviço `core`.
- A remoção de uma Organization remove a organização no Zitadel, e com ela o Project Grant. Os usuários (dono e futuros membros) vivem na organização `core` e permanecem.
