# Teste de jornada da plataforma

Esta suíte é um **teste**, e não um componente (decisão 0017). Fica na raiz porque cruza features e não
pertence a nenhuma: cada feature mantém o seu e2e de contrato (`features/core/account/tests/e2e`,
`features/sum/service/tests/e2e`), e este prova a **jornada** de uma pessoa usando a plataforma.

Black-box: usa a rede (gateway, Zitadel, Mailpit) e a **CLI real** (`sk`), e não importa o código de nenhum
componente.

## O que a jornada faz, em ordem

1. Cadastra uma pessoa (`POST /v1/core/accounts`, anônimo) com e-mail único de teste.
2. Lê no **Mailpit** o e-mail de ativação (um só, "Verificar e-mail") e, pela página do link, confirma o e-mail e define a senha.
3. `sk auth login`: login interativo de verdade (Authorization Code com PKCE e refresh token). O
   "navegador" é um falso (`tests/browser.py`, usado pelo `tests/login_browser.py` como `BROWSER`) que abre o
   endereço de login, preenche usuário e senha, dispensa a oferta de segundo fator e entrega o retorno ao
   servidor local do `sk`. Não usa nenhuma credencial privilegiada.
4. Confere que a conta nova já tem as roles base do SUM (`sum.ipm.*`, concedidas no cadastro, decisão 0033) e que o token **ainda não** tem as `ipm.*`.
5. `sk sum service enable --service ipm --wait`: o serviço chega a `Ready`, a Operation a `completed`, a sessão é
   renovada e **o token já traz as `ipm.organization.*`** (concedidas pelo Executor do SUM), sem novo login. Um
   segundo `enable` aponta a ligação existente.
6. Organization pela CLI real, com o `ipm` ligado: `sk ipm organization create --wait` (a organização chega a `Ready`, `active`, no Zitadel), `get` e `list`, um segundo `create` recusado pela cota com a orientação, `update --wait` (renomeia), e `delete --wait` (a Organization some); depois `get` dá `not found` e a lista fica vazia. A Organization é removida mesmo se um passo falhar.
7. Renovação da sessão: com o access token vencido, a CLI o renova pelo refresh token.
8. `sk sum service disable --wait`: converge, revoga as roles e o token **perde** as `ipm.*`; um segundo `disable` não
   tem nada a fazer. `sk auth refresh` renova a sessão sob demanda.
9. Limpeza: a pessoa é removida pela API com o próprio token (falha alto se não der), e as linhas
   `absent` da ligação são apagadas do SSOT quando há acesso ao banco.

## O que não cobre (declarado, não verificado)

- **Cadastro e login em produção** (stg/prd): só o dev.
- **Erros de rede e caos**: ficam nos e2e das features.
- **Operador** (`sum.service.admin`): fora do escopo.

## Configuração

Por variável de ambiente. Sem as obrigatórias, os testes são pulados.

| Variável | Padrão | Uso |
|---|---|---|
| `E2E_CLI_CLIENT_ID` | (obrigatória) | Client ID da aplicação `cli` (projeto `clients`, decisão 0034) |
| `E2E_CORE_PROJECT_ID` | (obrigatória) | ID do projeto `roles-core` (audience pedida no login) |
| `E2E_SUM_PROJECT_ID` | (obrigatória) | ID do projeto `roles-sum` (audience pedida no login) |
| `E2E_IPM_PROJECT_ID` | (obrigatória) | ID do projeto `roles-ipm` (audience pedida no login; as `ipm.*` chegam por ela) |
| `E2E_API_URL` | `http://api-dev.smarkee.com.br:8080` | Gateway da API |
| `E2E_ISSUER` | `http://ipm-dev.smarkee.com.br:8080` | Zitadel pelo gateway |
| `E2E_MAILPIT_URL` | `http://localhost:8025` | Mailpit do dev |
| `E2E_CLI_PROJECT` | `clients/cli` | Projeto `uv` da CLI usada nos testes |
| `E2E_SUM_MANAGER_DATABASE_URL` | (opcional) | Papel `sum_service_manager_login` (apaga a ligação de teste) |
| `E2E_SUM_MAINTENANCE_DATABASE_URL` | (opcional) | Papel `sum_service_maintenance_login` (apaga as linhas de apoio). Sem as duas, a limpeza do SSOT é pulada |

Os IDs e o client ID do dev saem do Zitadel (console ou `infrastructure/dev/README.md`).

## Como rodar

```bash
uv sync
uv run pytest
```

Pré-requisito: a stack de dev no ar (Zitadel e login, gateway, Account, SUM e Mailpit). Cada execução cria e
remove uma pessoa nova; nada é compartilhado entre execuções.
