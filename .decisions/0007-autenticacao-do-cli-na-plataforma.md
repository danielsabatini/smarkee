# 0007 — Autenticação do CLI na plataforma

- **Data:** 2026-10-09
- **Status:** Aceita

## Contexto

O CLI `sk` precisa autenticar o usuário antes de chamar as APIs da plataforma. O provedor de identidade é o Zitadel, exposto pelo gateway (`infrastructure/dev/README.md`). Havia três dúvidas: onde fica o login (comando de um módulo ou da plataforma, e em `features/` ou `components/`), se ele exige uma API própria e como o CLI obtém e guarda os tokens.

## Decisão

- **O login é da plataforma:** o comando é `sk auth login`, e não `sk ipm auth login`. O código fica no núcleo do CLI (`components/cli/src/sk/`).
- **Sem API de autenticação:** o `sk` fala direto com o Zitadel pelo gateway, usando o issuer público. Nenhum serviço da plataforma participa do login.
- **Auth não é uma feature:** não tem recurso no Resource Control Loop (sem `desired`, `observed`, Manager, Reconciler ou Executor). Por isso não fica em `features/`. Cada API valida os tokens recebidos (assinatura pelo JWKS, issuer, audience e roles); essa validação será uma biblioteca compartilhada, com local definido quando a primeira API precisar dela (candidato: `platform/identity`).
- **Fluxo:** OIDC Authorization Code com PKCE S256 e retorno em loopback `http://127.0.0.1:<porta efêmera>/callback` (RFC 7636 e RFC 8252). O CLI é um cliente público, sem segredo. No Zitadel, a aplicação nativa registra `http://127.0.0.1/callback`: em aplicação nativa, o Zitadel ignora a porta para loopback (`equalURI` em `zitadel/oidc` compara somente o caminho e a query).
- **Armazenamento:** os tokens ficam em `$XDG_CONFIG_HOME/sk/credentials.json` (padrão `~/.config/sk/credentials.json`), com permissão `0600` e gravação atômica.
- **Cliente OIDC na biblioteca padrão:** o fluxo usa `urllib` e `http.server`, sem biblioteca OIDC. O framework do CLI e a configuração seguem a decisão 0008.
- **TLS por padrão:** issuer e endpoints `http` são recusados, salvo permissão explícita (`--allow-insecure-http` ou `SK_AUTH_ALLOW_INSECURE_HTTP=true`), usada só em desenvolvimento.

## Justificativa

- O Zitadel já implementa o login. Uma API intermediária acrescentaria um serviço, credenciais e superfície de ataque sem requisito (`AGENTS.md`, seções 6 e 25).
- PKCE com loopback foi escolhido pelo usuário em vez do Device Authorization Grant. A alternativa dispensa o servidor local e funciona por SSH, mas exige digitar um código no navegador.
- O arquivo `0600` segue o padrão de ferramentas como kubectl e gcloud e não depende de keychain do sistema operacional, que varia entre plataformas e não existe em CI e containers. A alternativa (`keyring`) é mais segura em repouso, mas adiciona dependência e comportamento variável.
- A biblioteca padrão cobre o fluxo OIDC sem dependência nova (`python.md`, seção 13).

## Consequências

- O ID token não é validado localmente, e as claims dele não são usadas. A identidade exibida vem do userinfo, e a validação de tokens é responsabilidade das APIs.
- Os tokens ficam em texto claro, protegidos só pela permissão do arquivo.
- Pendente: `sk auth logout`, renovação pelo refresh token, audience e roles do projeto no escopo do login (depende da definição das roles) e o local da biblioteca de validação de tokens.
- A configuração da aplicação nativa no Zitadel é manual, pelo console (`infrastructure/dev/README.md`, *Login do CLI*), e se perde com `docker compose down -v`.
