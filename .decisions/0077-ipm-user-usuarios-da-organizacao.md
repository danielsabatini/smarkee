# 0077 — `ipm.user`: usuários próprios da Organization, com roles da plataforma

- **Data:** 2026-10-20
- **Status:** Aceita (itens em aberto fechados em 2026-10-21) e implementada em dev em 2026-10-21 (seção "Implementação"). Fecha a decisão 0039 §5 e revisa as decisões 0028 (vocabulário de ações), 0038 (Project Grant), 0042 (nome `user`) e, para este tipo, 0043 (proteção nasce desligada).
- **Origem:** direção do responsável pelo projeto, no modelo das clouds: uma conta (root) é a dona da Organization, e todas as outras pessoas são usuários criados dentro da própria Organization.

## Contexto

A 0039 §5 previa um "membro" (depois "administrador", decisão 0076) como vínculo de uma conta com uma Organization. Na avaliação de 2026-10-20 o responsável escolheu o modelo das clouds, como o *root user* e os usuários do IAM na AWS: o root é a conta da `register` que criou a Organization (`ownerAccountId`), e o dia a dia é feito por **usuários da Organization**, criados dentro dela no Zitadel.

## Evidência (Zitadel de dev, v4.19.4, 2026-10-20)

Sonda descartável (`.workspace/`), com organização, Grant, conta de serviço e usuários temporários removidos ao final:

- uma conta de serviço da `core` recebeu `ORG_USER_CREATOR` numa organização de cliente e `PROJECT_GRANT_OWNER` no Project Grant dela (papéis entre organizações funcionam; `resource` = `{"organizationId"}` e `{"projectGrant": {"projectId", "organizationId"}}`);
- com só esses papéis, ela criou um usuário dentro da organização do cliente, e foi **recusada** ao criar na `core` (`403 AUTH-5mWD2`);
- criou a autorização com uma role do Grant, e foi **recusada** com uma role fora dele (`failed_precondition`): o Grant é o teto;
- o token de um usuário da organização traz `urn:zitadel:iam:user:resourceowner:id` igual à organização e a role ligada a ela (escopos `urn:zitadel:iam:user:resourceowner`, `urn:zitadel:iam:org:project:id:<projeto>:aud` e `urn:zitadel:iam:org:projects:roles`);
- `AddKey` exige `expirationDate`, e `keyContent` é o JSON da chave em base64.

## Decisão

- **Tipo `ipm.user`:** um usuário do Zitadel criado **dentro** da organização do cliente. Não é uma conta da plataforma (`core.account`). Revisa a 0042: lá, "user" ficava só para o Zitadel; o `ipm.user` é justamente o usuário do Zitadel numa Organization, e o recurso da plataforma que o gerencia leva o mesmo nome.
- **Root:** a conta dona da Organization (`ownerAccountId`, da `register`). Não há administrador de negócio separado: a feature `ipm/administrator` não será criada.
- **CLI:** `sk ipm user create --name <nome> --surname <sobrenome> --email <e-mail> --role ... [--organization-id X]`, como o `sk account create`, com a organização ativa (`[ipm] organizationId`) quando a opção não é informada, como nos demais comandos do `ipm`.
- **Roles da plataforma, não papéis nativos do Zitadel:** o usuário recebe só roles nossas, por autorização no Project Grant da organização. Papéis nativos (`ORG_OWNER`, `ORG_USER_CREATOR`, *impersonators*...) não são dados a usuários: permitiriam agir pelo console do Zitadel, fora do loop.
- **Roles do tipo** (padrão da 0028): `ipm.user.create`, `ipm.user.get`, `ipm.user.list`, `ipm.user.update`, `ipm.user.delete` e **`ipm.user.bind`**. O vocabulário fechado de ações da 0028 ganha `bind`, com a semântica do RBAC do Kubernetes (referência de mercado, decisão 0071):
  - `ipm.user.bind` permite atribuir ou retirar qualquer role do Grant da organização a um usuário, na criação ou depois;
  - sem `bind`, quem cria um usuário só atribui roles que ele mesmo tem (ou nenhuma);
  - o root tem tudo na Organization de que é dono;
  - `bind` é poder de administração da Organization (quem o tem pode dá-lo a outro): é dado com cuidado.
- **Escopo por organização:** o Receiver aceita o operador, o root (dono) ou um usuário **da própria organização** com a role exigida. Um usuário nunca age em outra organização. O reconhecimento é positivo, e não pelo claim `resourceowner` do token (que a CLI não pede e que também valeria para a `register`): o usuário é reconhecido pelo **próprio registro** no SSOT do tipo (`resourceId` igual ao `sub`, `lifecycle present`), e o root pelo **Receiver da Organization**, consultado com o token de quem pede (decisão 0040). Todo usuário lê o próprio registro sem role (como o `SelfSubjectReview` do Kubernetes), e é por ele que o Receiver da Organization reconhece os usuários dela.
- **Roles e Project Grant são atividade do operador nesta etapa:** o operador define as roles nos projetos de roles e cria, para cada organização de cliente, o Project Grant com as roles liberadas; o `ipm.user` só consome o que existe. Lacuna declarada em `docs/IMPLEMENTATION-STATUS.md`, com a condição que a fecha: automatizar o Grant na `ipm/organization` (caminho aditivo, §2.6; revisa a 0038 quando acontecer).
- **Credencial do Executor (menor privilégio):** conta de serviço própria, `ipm-user-executor`, na `core`, sem papel de instância. Junto com o Grant de cada organização, o operador lhe dá `ORG_USER_CREATOR` na organização e `PROJECT_GRANT_OWNER` no Grant. O Observer (`ipm-user-observer`) lê com papel só de leitura na organização (`ORG_OWNER_VIEWER`), dado da mesma forma.
- **Recusa explícita:** o Receiver confere as roles pedidas contra o catálogo do Grant da organização e recusa as que o operador ainda não liberou, antes do loop; o Zitadel continua sendo a última barreira.

## Itens fechados em 2026-10-21

1. **Campos e ativação, como na Account:** `givenName`, `familyName` e `email` (obrigatórios; o e-mail é normalizado e também é o nome de login do usuário na organização). O usuário é criado **sem senha** e define a senha pelo e-mail de verificação do Zitadel. A senha nunca passa por CLI, Receiver, SSOT nem NATS. O e-mail é dado pessoal: fica fora de logs e mensagens de erro, como na Account, e sai do `desired` na remoção.
2. **Proteção contra exclusão, desligada por padrão:** o usuário tem `deletionProtection` (campo gerenciado, metadado no usuário, decisão 0074), mas nasce com `false`. É uma **exceção explícita à 0043** (que manda nascer protegido): escolha do responsável, para que criar e remover usuários seja leve no dia a dia. O risco (um usuário removido no Zitadel não volta) é mitigado por três pontos: a remoção exige `ipm.user.delete`, vale só dentro da própria organização, e a proteção pode ser ligada por usuário (`sk ipm user protect`), com a mesma regra do `delete` recusado da 0043.
3. **Cota: 5 usuários por Organization** para começar, configurável no Receiver (como a cota de Organizations por dono, `IPM_ORGANIZATION_RECEIVER_API_ORGANIZATION_QUOTA`) e conferida de novo pelo Manager, sob trava por organização. O operador (`ipm.user.admin`) não tem cota. O valor é provisório, para testar o mecanismo.
4. **Entrar pela CLI:** verificação, e não decisão. O e2e do tipo confirma que um usuário humano da organização entra pela aplicação `cli` e recebe as roles e a organização no token.
5. **Organization só vazia:** apagar uma Organization exige que ela não tenha usuários. O Receiver da `ipm/organization` recusa (`409`) perguntando ao `ipm/user`, no padrão da 0040 (o Receiver de um tipo consulta o outro com o token de quem pede). Com isso, a remoção da Organization nunca apaga usuários sem aviso (o `DeleteOrganization` do Zitadel os apagaria junto).

## Consequências

- Nova feature `features/ipm/user`, pelo roteiro `docs/FEATURE-BOOTSTRAP.md`.
- `ipm/organization`: o Receiver passa a aceitar usuários da própria organização com role (além do dono) e a recusar o `delete` enquanto houver usuários (item 5).
- Operação manual nova por organização: Grant, papéis do Executor e do Observer do `ipm.user`, documentada no `infrastructure/dev/README.md` quando a feature for criada.

## Implementação (2026-10-21)

- **Feature `features/ipm/user`**, criada pelo roteiro `docs/FEATURE-BOOTSTRAP.md` com os quatro perfis do template (decisão 0075). O Manager confere o e-mail único **na Organization** (trava consultiva por Organization e e-mail), as roles do módulo `ipm` e a cota por Organization (`organizationQuotaLimit`, campo novo do `requested-create`). O Executor deixa no Zitadel **exatamente** as roles do `desired` (cria, atualiza ou remove a autorização) e grava o metadado da proteção.
- **Receiver:** o catálogo do Grant é a lista `IPM_USER_RECEIVER_API_GRANTABLE_ROLES` (igual para todas as Organizations, mantida igual ao Grant que o operador cria; vazia, recusa tudo). Sem `bind`, a regra vale para o que entra **e** para o que sai (quem não tem a role não a dá nem a tira).
- **`ipm/organization`:** o Receiver aceita os usuários da Organization (pelo Receiver do User) e recusa o `delete` enquanto ela tiver usuários (`409 ResourcesAttached`; na dúvida, `503` ou `409 ResourcesNotVerifiable`).
- **SUM:** o catálogo do serviço `ipm` ganha as roles `ipm.user.*` (sem o `admin`), e o Grant de `roles-ipm` para a `register` também: o root as recebe ao habilitar o `ipm`.
- **Operador (dev):** roles `ipm.user.*` e `ipm.user.admin` no `roles-ipm`, contas `ipm-user-executor` e `ipm-user-observer` na `core` sem nenhum papel, e o passo a passo por organização no `infrastructure/dev/README.md`. A suíte de conformidade de identidade confere as contas, as roles, o Grant da `register` e a configuração do `.env`.
- **Verificado contra o Zitadel real:** o loop completo (criar sem senha, trocar as roles, proteger e remover), a recusa do Zitadel para uma role fora do Grant e o **item 4**: um usuário humano da Organization entrou pela aplicação `cli` (login v2 com PKCE), o token trouxe a audience de `roles-ipm` e as roles dele ligadas à organização dele, e pelo gateway ele leu o próprio registro, listou os usuários e, com `ipm.organization.get`, leu a Organization. **Não verificado ponta a ponta:** o caminho do root (Receiver do User consultando o da Organization) e a recusa do `delete` de uma Organization com usuários, ambos cobertos por testes unitários, porque exigem o token de um root real.

