# 0014 — User no módulo `core` com auto-cadastro

- **Data:** 2026-10-10
- **Status:** Aceita
- **Papel do Executor:** o `ORG_USER_MANAGER` citado aqui foi substituído pela decisão 0032 (`ORG_USER_CREATOR` na `register` e `PROJECT_GRANT_OWNER` nos Grants dos módulos).
- **Rotas:** os caminhos citados aqui (`/v1/users`, `/v1/organizations`, `/v1/<tipos>`) foram substituídos pelo padrão da decisão 0030 (`/v1/<módulo>/<tipos>`).
- **Nomes das roles:** os nomes citados aqui (`organization.*`, `user.*`, `platform.admin`) foram substituídos pelo padrão da decisão 0028 (`ipm.organization.*`, `core.user.*`, `*.admin`).

## Contexto

A decisão 0013 desliga o cadastro público do Zitadel. O usuário precisa de um caminho para se cadastrar, e a Organization só pode ser criada por um usuário registrado e autenticado. Pela mesma decisão, o cadastro passa pelo Receiver e pelo Resource Control Loop.

Dois pontos limitam o desenho:

- o `desired` de um recurso fica no SSOT e no stream `DESIRED` por tempo indeterminado, e `docs/SCHEMA.md` §20.1 proíbe senha em schema e em mensagem;
- no cadastro não há solicitante autenticado, mas o `requested` exige `requestedBy`.

## Decisão

- **User é um recurso da plataforma, no módulo `core`** (decisão 0009, em que o User ficou em `core`; a Organization voltou ao `ipm` pela 0016): subjects `*.core.user.*`, serviços `core-user-*`, rotas `/v1/users`, comandos `sk register` (auto-cadastro) e `sk user get`.
- **`resourceId` do User é o ID do usuário no Zitadel**, informado na criação (`user_id`), pela mesma regra da Organization (decisão 0006).
- **Organização `core` no Zitadel.** É uma organização de sistema, separada da `smarkee` dos operadores. Nela vivem os usuários cadastrados e as service accounts dos Executors do módulo `core`. Não é uma Organization da plataforma: sem dono e sem cota. O nome `core` é reservado.
- **Sem senha na mensagem.** O `desired` do User não tem senha. O Executor cria o usuário no Zitadel sem senha, e o Zitadel envia o e-mail "Verificar e-mail"; em seguida o Executor pede o link de definição de senha (`password_reset` com `sendLink`), que o Zitadel envia no e-mail "Redefinir senha". A pessoa define a senha na página do Zitadel. A senha nunca passa por CLI, Receiver, SSOT nem NATS. Por isso o comando é `sk register --name --surname --email`, sem `--password`.
- **Solicitante anônimo no cadastro:** o `requestedBy` é o literal `anonymous`. Proteções obrigatórias do endpoint anônimo (`docs/RESOURCE-CONTROL-LOOP.md` §6.1.2):
  - limite de taxa por origem no gateway e no Receiver;
  - **resposta uniforme**: o mesmo `202` e o mesmo corpo, exista ou não o e-mail;
  - **sem consulta da Operation por anônimo**: o `operationId` devolvido não permite acompanhar o pedido, o que impede descobrir quais e-mails já estão cadastrados.
- **Autorização após o cadastro.** O projeto `smarkee` pertence à organização `core` (decisão 0010), a mesma do usuário. O Executor autoriza o User diretamente nesse projeto, com o conjunto de roles de ação (`organization.create`, `organization.get`, `organization.list`, `organization.update`, `organization.delete`, `user.get` e `user.delete`). Esse conjunto é o `platformAccess = granted` do User. (Desde a decisão 0025 o conjunto fica registrado no SSOT, em `desired.platformRoles`.) Com e-mail verificado e a role `organization.create`, ele pode criar uma Organization dentro da cota.
- **Service account `core-user-executor`**, na organização `core`, com o papel de **organização** `ORG_USER_MANAGER` (e não de instância), restrito aos usuários dessa organização. Verificado em dev: cria usuários sem senha, autoriza no projeto, lê e remove; não cria organização nem acessa outras organizações. Se for comprometida, o dano fica nos usuários cadastrados.
- **Dados pessoais:** `email`, `givenName` e `familyName` são `confidential` (`docs/SCHEMA.md` §20.2): não aparecem em log, mensagem de erro nem métrica.

## Justificativa

- Seguir o loop dá ao cadastro auditoria, idempotência, `Operation` e o mesmo padrão de todas as features. O Executor é o único componente com credencial de escrita no Zitadel.
- Sem senha na mensagem, o cadastro respeita o `SCHEMA.md` §20.1, e a senha fica sob a política e a proteção do Zitadel.
- A resposta uniforme e a ausência de consulta anônima evitam que o endpoint de cadastro sirva para enumerar e-mails.
- Alternativa descartada: o Receiver criar o usuário de forma síncrona com a senha. Daria ao Receiver anônimo uma credencial de escrita no Zitadel, e a senha trafegaria por componentes nossos.

## Consequências

- **Retenção de dados pessoais:** o `desired` do User, com e-mail e nome, fica retido no SSOT e em `DESIRED`. O `desired` com `lifecycle = absent` não carrega dados pessoais (a regra entra no contrato do User), e a limpeza do tombstone (`docs/NATS.md`) precisa cobrir esse caso.
- O cliente anônimo não acompanha a Operation: `sk register` não tem `--wait` e orienta a verificar o e-mail.
- **Verificado em dev (Zitadel v4.19.4, 2026-10-11):** `POST /v2/users/human` com `userId` informado cria o usuário ativo, sem senha e com o e-mail não verificado, e envia "Verificar e-mail"; `POST /v2/users/{id}/password_reset` com `sendLink` envia "Redefinir senha". O loop completo (criação, os dois e-mails no Mailpit, observação `userState = initial`, `Ready` e remoção) está coberto pelo teste e2e. **Ainda não verificado:** a pessoa seguindo os links, definindo a senha e fazendo `sk auth login` com o usuário novo.
- O módulo `ipm` fica com o que vier depois, como membros de uma Organization.
