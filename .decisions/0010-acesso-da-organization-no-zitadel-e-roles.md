# 0010 — Acesso da Organization no Zitadel e roles da plataforma

- **Data:** 2026-10-09
- **Status:** Aceita. Revisada em 2026-10-10: o criador autenticado é o dono; o Executor da Organization não cria usuários.

## Contexto

Uma Organization só pode ser criada por um usuário registrado e autenticado (decisões 0013 e 0014). O criador passa a ser o dono dela e deve conseguir operar sem passos manuais, com o mesmo `sk auth login`. Duas formas de dar acesso foram avaliadas:

1. um projeto e uma aplicação `cli` dentro de cada organização do Zitadel;
2. um único projeto da plataforma, delegado a cada organização.

## Decisão

- **Projeto único `smarkee`** na organização `smarkee` (a dos operadores), com:
  - todas as roles da plataforma;
  - uma aplicação nativa `cli` por ambiente (decisão 0007), usada por todas as Organizations.
- **Quem pode criar uma Organization:** o usuário autenticado, com **e-mail verificado** e a role `platform.user`, dentro da **cota por dono** (padrão 1, configurável). `platform.admin` não tem cota.
  - A cota é aplicada **no Manager**, na mesma unidade atômica do pedido, com trava consultiva por dono. A pré-checagem da API é só conveniência e não garante o limite com criações concorrentes.
  - Cada Organization vira namespace no OpenBao e no Kubernetes; sem cota, qualquer conta criaria organizações sem limite.
- **Nomes reservados** (`core`, `smarkee` e uma lista da plataforma) são rejeitados como `validation`.
- **Dono:** o contrato da Organization tem `ownerUserId`, o `resourceId` do User autenticado que criou (`writer = server`, imutável, vindo do `sub` do token). Não há mais `firstAdministrator` nem dados pessoais no contrato da Organization.
- Na criação de uma Organization, o Executor aplica no Zitadel, nesta ordem e cada passo de forma idempotente:
  1. a organização, com `organization_id = resourceId` (decisão 0006);
  2. o **Project Grant** do projeto `smarkee` para a organização, com as roles delegáveis;
  3. a **autorização do dono** com a role `organization.admin`.

  O Executor da Organization **não cria usuários**. O dono vive na organização `core` do Zitadel (decisão 0014), e não na organização que acaba de ser criada; por isso a forma da autorização e o conteúdo do token dependem do spike da Fase C, e a API decide o pertencimento pelo `ownerUserId` guardado na plataforma, e não só pelas roles do token.
- **Roles iniciais:**

  | Role | Delegável | Uso |
  |---|---|---|
  | `platform.admin` | Não | Operadores da plataforma (org `smarkee`): criam e gerenciam Organizations, sem cota |
  | `platform.user` | Não | Usuário cadastrado (org `core`): cria Organizations dentro da cota |
  | `organization.admin` | Sim | Administrador de uma Organization (o dono) |
  | `organization.viewer` | Sim | Leitura dentro de uma Organization |

- O `sk organization create --wait` devolve `organizationId`, nome e fase. O dono entra com o mesmo `sk auth login`, na mesma aplicação `cli`.

## Justificativa

- Um projeto por organização inverteria a delegação: cada organização seria dona das próprias roles, as roles seriam duplicadas e as APIs teriam de aceitar a audience de N projetos.
- O projeto único com Project Grant é o modelo de delegação B2B do Zitadel. As APIs validam uma audience fixa e um conjunto único de roles.
- Criar a Organization por um usuário já autenticado dispensa dados pessoais nas mensagens da Organization e tira do Executor a criação de usuários, o que reduz o privilégio dele.

## Consequências

- O Executor da Organization é a service account `core-organization-executor`, na organização `core`, com papel de **instância** (`IAM_ORG_MANAGER`, a confirmar), porque criar organização é uma operação de instância. Estreitar com um papel customizado antes de prd (decisão 0011).
- O ID do projeto `smarkee` e as chaves das roles são configuração do serviço `core`.
- A remoção de uma Organization remove a organização no Zitadel, e com ela o grant. Os usuários dono e membros vivem fora dela e permanecem.
