# 0013 — Ordem API → CLI → console web e Zitadel como backend protegido

- **Data:** 2026-10-10
- **Status:** Aceita

## Contexto

Ao analisar o ambiente de desenvolvimento, a página de login do Zitadel exibia o botão "registrar" e o formulário de cadastro, públicos. O auto-cadastro de organization (`/ui/login/register/org`) também estava aberto. Qualquer pessoa com acesso à URL podia criar usuários e organizações, fora do Resource Control Loop e sem limite.

Além disso, o CLI fala com o Zitadel só para autenticar (decisão 0007), mas não havia uma regra geral para o acesso às demais operações: qual superfície vem primeiro e quem é a porta de entrada.

## Decisão

- **Ordem de acesso e de desenvolvimento, igual para todas as features: API → CLI → console web.**
  - O **Receiver** é a única porta de entrada para operações sobre recursos (`docs/loop/RESOURCE-CONTROL-LOOP.md` §6.1). O CLI e o console web são clientes dela.
  - Cada feature entrega o Receiver primeiro, depois o CLI, depois o console web.
  - **Exceção:** o login OIDC. O cliente (CLI ou console) autentica no Zitadel, que emite o token; o Receiver só o valida (JWKS, `iss`, audience, roles).
- **O Zitadel é backend, e fica o mais protegido possível:**
  - o **registro de usuário do Zitadel é desligado** (política de login, "registro permitido"), o que remove o botão "registrar" e o auto-cadastro de organization. Usuários e organizações nascem só pelo Receiver, pelo loop;
  - o gateway expõe ao público somente o necessário ao OIDC e à página de login: `/ui/login/` (login, ativação e redefinição de senha), `/oauth/v2/`, `/oidc/v1/` e `/.well-known/`, mais os recursos estáticos do login. **Console, Management API, Admin API e gRPC só pela rede interna em stg e prd.** Em dev o console segue acessível. A separação é por caminho, e não por host, porque os links dos e-mails usam o domínio externo do Zitadel, o mesmo do login;
  - o Receiver não tem credencial de escrita no Zitadel (`docs/loop/RESOURCE-CONTROL-SECURITY.md` §9): quem escreve é o Executor, com uma conta própria de menor privilégio. O Receiver e os Executors acessam o Zitadel pela rede interna.
- **Dev: captura de e-mail.** O fluxo de ativação de usuário envia e-mail pelo Zitadel. Em dev, o servidor de e-mail é um contêiner de captura, só no ambiente de desenvolvimento, para testar o fluxo de ponta a ponta. A ferramenta de captura disponível é o **Mailpit** (`infrastructure/dev/mail`, imagem fixada): captura o SMTP e expõe uma interface web só no host, não envia nada para fora e dispensa credenciais. Justificativa (`AGENTS.md` §21): é um contêiner único, de uso só em dev, que torna testável a ativação sem senha com e-mails fictícios. O dev usa o Mailpit por padrão (ninguém recebe os e-mails); um provedor real (Brevo) pode ser ativado no console para testes de envio. Em stg e prd o SMTP é sempre o provedor real, com a credencial vinda da gestão de segredos.

## Justificativa

- Uma só porta de entrada concentra autenticação, autorização, validação, limites de taxa e auditoria no mesmo lugar, para qualquer cliente.
- Manter o Zitadel atrás do Receiver e do gateway reduz a superfície de ataque do componente que guarda as identidades.
- Desenvolver o Receiver primeiro obriga a modelar o contrato antes das interfaces, e o CLI e o console passam a ser clientes finos do mesmo contrato.
- Alternativa descartada: manter o cadastro nativo do Zitadel (`prompt=create`). Não exige código, mas deixa o cadastro e a criação de usuários fora do loop, sem a cota, a auditoria e os limites da plataforma.

## Consequências

- O console do Zitadel deixa de ser acessível publicamente em stg e prd. Operadores o acessam pela rede interna.
- Os caminhos exatos do login v1 (o v2 está desativado) e dos recursos estáticos são confirmados no spike da Fase C.
- **Aplicado no dev em 2026-10-10:** o registro foi desligado na política de login padrão da instância (`allowRegister = false`; as organizações herdam a política padrão), e a organização `tenant1`, criada pelo auto-cadastro antigo, foi removida. Em instância nova, o ajuste será por variável de ambiente (nome a confirmar).
- O console web da plataforma é uma feature futura, depois do Receiver e do CLI.
