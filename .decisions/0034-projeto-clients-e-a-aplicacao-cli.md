# 0034 — Projeto `clients` do Zitadel, a aplicação `cli` e a pasta `clients/`

- **Data:** 2026-10-16
- **Status:** Aceita. Ajusta a decisão 0032 (a aplicação `cli` deixa de morar em `roles-core`) e a 0010 (a verificação de role na autenticação passa a valer só nos projetos de roles).

## Contexto

A decisão 0032 deixou a aplicação `cli` dentro do projeto `roles-core`, e a 0033 supôs que bastava o login pedir a audience e as roles do projeto `roles-sum` para o token valer no Receiver do SUM. Ao rodar a jornada de ponta a ponta (cadastro, ativação, `sk auth login` e `sk sum service enable`), o `enable` voltou `403` mesmo com a pessoa tendo `sum.ipm.*`.

Medido no Zitadel de dev (v4.19.4), no login interativo (Authorization Code com PKCE), com `aud` e `projects:roles` pedidos para `roles-core` e `roles-sum`:

| A aplicação mora em | Roles no token |
|---|---|
| `roles-core` | só as de `roles-core` |
| `roles-sum` | só as de `roles-sum` |
| um projeto sem roles | as de `roles-core` **e** as de `roles-sum` |

Ou seja: com a aplicação dentro de um projeto de roles, o Zitadel só coloca no token as roles desse projeto, e o token não vale nos Receivers dos outros módulos. Com `projectRoleAssertion` ligado ou desligado no projeto sem roles, o resultado é o mesmo; com a verificação de role na autenticação (`projectRoleCheck`) ligada, o login é recusado (ninguém tem role nesse projeto).

## Decisão

- **Projeto `clients`**, na organização `core`: guarda as aplicações dos clientes da plataforma (hoje a `cli`; depois o console). Não tem roles e não é delegado à `register` por Project Grant. `projectRoleAssertion` ligado e **`projectRoleCheck` desligado**.
- **Aplicação `cli`** passa a morar em `clients`, com a mesma configuração (nativa, PKCE sem segredo, redirect `http://127.0.0.1/callback`, Authorization Code e Refresh Token, access token JWT, roles no token). O client ID muda.
- **O `sk` pede a audience de cada módulo no login:** `[core] projectId` (`roles-core`), `[sum] projectId` (`roles-sum`) e `[ipm] projectId` (`roles-ipm`), ou as variáveis `SK_<SEÇÃO>_PROJECT_ID`. O token só traz as roles dos projetos pedidos: sem `[ipm]`, as roles `ipm.*` concedidas pelo SUM nunca chegariam a ele. Sem a chave de um módulo, o Receiver dele recusa o token (sem a audience dele). A verificação de role que antes acontecia no login continua nos Receivers, que exigem a audience do próprio projeto e a role de ação.
- **Pasta `clients/`** (antes `components/`), na raiz: a casa de tudo que é cliente da API pública da plataforma (`cli` hoje; `console`, `terraform` e outros depois). O repositório fica em três eixos: `platform/` (o que roda), `features/` (o que a plataforma faz) e `clients/` (quem a usa). O nome é o do protocolo (aplicação registrada = *client* do OIDC).
- **Teste de jornada** em `tests/e2e/` (raiz): cruza features e não pertence a nenhuma.

## Justificativa

Alternativas consideradas para o token valer em todos os módulos, em ordem de segurança, simplicidade, robustez e disponibilidade:

- **Uma aplicação por projeto de roles** (`cli` em `roles-core`, `cli-sum` em `roles-sum`): mantém a verificação de role no login, mas custa um login por módulo e uma aplicação por módulo.
- **O Receiver consultar as autorizações no Zitadel** (`ListAuthorizations`) em vez de confiar no token: um login só, mas cada pedido faz uma chamada ao provedor e o Receiver ganha uma credencial com poder de leitura.
- **Zitadel Action** que acrescenta as roles dos projetos da audience: uma peça nova e frágil para manter.
- **Aplicação num projeto sem roles** (escolhida): um login só, nenhuma peça nova, nenhuma credencial nova. Mede-se o efeito acima.

## Consequências

- **Segurança, o custo aceito:** sem `projectRoleCheck`, qualquer conta da instância consegue autenticar na aplicação `cli`; antes, só quem tinha ao menos uma role em `roles-core`. O token dessa conta carrega só as roles que ela de fato tem (nenhuma, se não tiver) e as audiences pedidas, e os Receivers recusam sem a role de ação. Não há dado exposto pelo login em si. Aceito porque a autorização real está nos Receivers; a conferência de estrutura (`identity/conformance`) fixa que `clients` não tem roles nem verificação de role.
- **Provisionamento:** o projeto e a aplicação são criados à mão (`infrastructure/dev/README.md`), como os demais. O client ID da `cli` muda (um por ambiente); quem já usa a CLI roda `sk config set auth.clientId <novo>` e grava os `projectId` dos módulos.
- **A aplicação antiga** (`cli` em `roles-core`) foi removida do Zitadel de dev em 2026-10-16, depois de o client ID novo estar em uso. A suíte de conformidade fixa que nenhum projeto de roles tem aplicações.
- **Configuração da CLI:** a chave `core.projectId` é nova, e `sk config` passou a conhecer a seção `[sum]` (antes, uma alteração por `sk config set` apagava `[sum] projectId` do arquivo).
- **Não verificado:** `projectRoleAssertion` do `clients` desligado e ligado deram o mesmo resultado nas roles do token; o ligado foi mantido. A produção (stg/prd, Kubernetes) repete o desenho por configuração; não foi exercida aqui.
