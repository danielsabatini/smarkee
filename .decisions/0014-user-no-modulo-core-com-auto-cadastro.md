# 0014 — User no módulo `core` com auto-cadastro

- **Data:** 2026-10-10
- **Status:** Aceita

## Contexto

A decisão 0013 desliga o cadastro público do Zitadel. O usuário precisa de um caminho para se cadastrar, e a Organization só pode ser criada por um usuário registrado e autenticado. Pela mesma decisão, o cadastro passa pela API e pelo Resource Control Loop.

Dois pontos limitam o desenho:

- o `desired` de um recurso fica no SSOT e no stream `DESIRED` por tempo indeterminado, e `docs/SCHEMA.md` §20.1 proíbe senha em schema e em mensagem;
- no cadastro não há solicitante autenticado, mas o `requested` exige `requestedBy`.

## Decisão

- **User é um recurso da plataforma, no módulo `core`** (decisão 0009): subjects `*.core.user.*`, serviços `srv-core-user-*`, rotas `/v1/users`, comandos `sk register` (auto-cadastro) e `sk user get`.
- **`resourceId` do User é o ID do usuário no Zitadel**, informado na criação (`user_id`), pela mesma regra da Organization (decisão 0006).
- **Organização `core` no Zitadel.** É uma organização de sistema, separada da `smarkee` dos operadores. Nela vivem os usuários cadastrados e as service accounts dos Executors do módulo `core`. Não é uma Organization da plataforma: sem dono e sem cota. O nome `core` é reservado.
- **Sem senha na mensagem.** O `desired` do User não tem senha. O Executor cria o usuário no Zitadel sem senha, e o Zitadel envia o e-mail de ativação (o texto em pt já está configurado). A pessoa define a senha na página do Zitadel. A senha nunca passa por CLI, API, SSOT nem NATS. Por isso o comando é `sk register --name --surname --email`, sem `--password`.
- **Solicitante anônimo no cadastro:** o `requestedBy` é o literal `anonymous`. Proteções obrigatórias do endpoint anônimo (`docs/RESOURCE-CONTROL-LOOP.md` §6.1.2):
  - limite de taxa por origem no gateway e na API;
  - **resposta uniforme**: o mesmo `202` e o mesmo corpo, exista ou não o e-mail;
  - **sem consulta da Operation por anônimo**: o `operationId` devolvido não permite acompanhar o pedido, o que impede descobrir quais e-mails já estão cadastrados.
- **Autorização após o cadastro.** O projeto `smarkee` pertence à organização `core` (decisão 0010), a mesma do usuário. O Executor autoriza o User diretamente nesse projeto, com o conjunto de roles de ação (`organization.create`, `organization.get`, `organization.list`, `organization.update`, `organization.delete`, `user.get` e `user.delete`). Esse conjunto é o `platformAccess = granted` do User. Com e-mail verificado e a role `organization.create`, ele pode criar uma Organization dentro da cota.
- **Service account `core-user-executor`**, na organização `core`, com o papel de **organização** `ORG_USER_MANAGER` (e não de instância), restrito aos usuários dessa organização. Verificado em dev: cria usuários sem senha, autoriza no projeto, lê e remove; não cria organização nem acessa outras organizações. Se for comprometida, o dano fica nos usuários cadastrados.
- **Dados pessoais:** `email`, `givenName` e `familyName` são `confidential` (`docs/SCHEMA.md` §20.2): não aparecem em log, mensagem de erro nem métrica.

## Justificativa

- Seguir o loop dá ao cadastro auditoria, idempotência, `Operation` e o mesmo padrão de todas as features. O Executor é o único componente com credencial de escrita no Zitadel.
- Sem senha na mensagem, o cadastro respeita o `SCHEMA.md` §20.1, e a senha fica sob a política e a proteção do Zitadel.
- A resposta uniforme e a ausência de consulta anônima evitam que o endpoint de cadastro sirva para enumerar e-mails.
- Alternativa descartada: a API criar o usuário de forma síncrona com a senha. Daria à API anônima uma credencial de escrita no Zitadel, e a senha trafegaria por componentes nossos.

## Consequências

- **Retenção de dados pessoais:** o `desired` do User, com e-mail e nome, fica retido no SSOT e em `DESIRED`. O `desired` com `lifecycle = absent` não carrega dados pessoais (a regra entra no contrato do User), e a limpeza do tombstone (`docs/NATS.md`) precisa cobrir esse caso.
- O cliente anônimo não acompanha a Operation: `sk register` não tem `--wait` e orienta a verificar o e-mail.
- O fluxo exato de ativação sem senha (e-mail de inicialização ou link de redefinição, e se ele já verifica o e-mail) ainda **não foi verificado**: a criação sem senha com `returnCode` funciona, mas a página de ativação do Zitadel só pode ser exercitada com e-mail entregue (precisa de servidor de e-mail em dev, decisão 0013). Isso será confirmado antes de implementar o Executor do User.
- O módulo `ipm` fica com o que vier depois, como membros de uma Organization.
