# 0013 — Ordem API → CLI → console web e Zitadel como backend protegido

- **Data:** 2026-10-10
- **Status:** Aceita

## Contexto

Ao analisar o ambiente de desenvolvimento, a página de login do Zitadel exibia o botão "registrar" e o formulário de cadastro, públicos. O auto-cadastro de organization (`/ui/login/register/org`) também estava aberto. Qualquer pessoa com acesso à URL podia criar usuários e organizações, fora do Resource Control Loop e sem limite.

Além disso, o CLI fala com o Zitadel só para autenticar (decisão 0007), mas não havia uma regra geral para o acesso às demais operações: qual superfície vem primeiro e quem é a porta de entrada.

## Decisão

- **Ordem de acesso e de desenvolvimento, igual para todas as features: API → CLI → console web.**
  - A **API** é a única porta de entrada para operações sobre recursos (`docs/RESOURCE-CONTROL-LOOP.md` §6.1). O CLI e o console web são clientes dela.
  - Cada feature entrega a API primeiro, depois o CLI, depois o console web.
  - **Exceção:** o login OIDC. O cliente (CLI ou console) autentica no Zitadel, que emite o token; a API só o valida (JWKS, `iss`, audience, roles).
- **O Zitadel é backend, e fica o mais protegido possível:**
  - o **registro de usuário do Zitadel é desligado** (política de login, "registro permitido"), o que remove o botão "registrar" e o auto-cadastro de organization. Usuários e organizações nascem só pela API, pelo loop;
  - o gateway expõe ao público somente o necessário ao OIDC e à página de login: `/ui/login/` (login, ativação e redefinição de senha), `/oauth/v2/`, `/oidc/v1/` e `/.well-known/`, mais os recursos estáticos do login. **Console, Management API, Admin API e gRPC só pela rede interna em stg e prd.** Em dev o console segue acessível. A separação é por caminho, e não por host, porque os links dos e-mails usam o domínio externo do Zitadel, o mesmo do login;
  - a API não tem credencial de escrita no Zitadel (`docs/RESOURCE-CONTROL-SECURITY.md` §9): quem escreve é o Executor, com uma conta própria de menor privilégio. A API e os Executors acessam o Zitadel pela rede interna.
- **Dev: captura de e-mail.** O fluxo de ativação de usuário envia e-mail pelo Zitadel. Em dev, o servidor de e-mail é um contêiner de captura, só no ambiente de desenvolvimento, para testar o fluxo de ponta a ponta. A ferramenta escolhida é registrada na Fase C (`AGENTS.md` §21).

## Justificativa

- Uma só porta de entrada concentra autenticação, autorização, validação, limites de taxa e auditoria no mesmo lugar, para qualquer cliente.
- Manter o Zitadel atrás da API e do gateway reduz a superfície de ataque do componente que guarda as identidades.
- Desenvolver a API primeiro obriga a modelar o contrato antes das interfaces, e o CLI e o console passam a ser clientes finos do mesmo contrato.
- Alternativa descartada: manter o cadastro nativo do Zitadel (`prompt=create`). Não exige código, mas deixa o cadastro e a criação de usuários fora do loop, sem a cota, a auditoria e os limites da plataforma.

## Consequências

- O console do Zitadel deixa de ser acessível publicamente em stg e prd. Operadores o acessam pela rede interna.
- Os caminhos exatos do login v1 (o v2 está desativado) e dos recursos estáticos são confirmados no spike da Fase C.
- O desligamento do registro na instância atual é um ajuste na política de login, pelo console. Em instância nova, é variável de ambiente (nome a confirmar).
- O console web da plataforma é uma feature futura, depois da API e do CLI.
