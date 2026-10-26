# Usar a CLI `sk` em dev e stg

Guia de quem desenvolve ou opera a plataforma e precisa apontar a CLI para um ambiente que **não** é produção. Em produção não há nada a configurar: os valores da plataforma são o padrão da CLI (decisão [`0036`](../../.decisions/0036-padroes-de-producao-da-cli-e-fim-do-sk-init.md)). O uso dos comandos está em [`clients/cli/README.md`](../../clients/cli/README.md).

> **Sobre o nome:** o projeto chama a homologação de `stg` (`AGENTS.md` §2.5). Este guia usa `stg`.

## 1. Como a CLI escolhe o ambiente

Cada valor vem de uma única fonte, na ordem, do mais forte para o mais fraco (decisões `0008` e `0041`):

```text
variável SK_*  →  ~/.config/sk/config.toml  →  padrão de produção
```

O ambiente (provedor de identidade, client ID, URL da API, IDs dos projetos de roles, HTTP sem TLS) **não tem opção de linha de comando**. Em dev e stg ele é escolhido por variáveis, carregadas de um `.env` com `source`.

O padrão de produção ainda é o marcador `000000000000000000` (18 zeros) para o client ID e para os IDs dos projetos, porque o Zitadel de produção ainda não foi provisionado. Por isso `sk auth login` recusa o login sem sobrescrita.

## 2. Preparar o ambiente (uma vez)

```bash
cd clients/cli
cp -n .env.example .env     # o .env fica fora do git
uv sync
```

Preencha o `.env` com os valores do ambiente. Os IDs vêm do console do Zitadel ou de [`infrastructure/dev/README.md`](../../infrastructure/dev/README.md). Nada ali é segredo: são endereços e IDs públicos.

| Variável | Para que serve |
|---|---|
| `SK_AUTH_ISSUER` | Issuer OIDC (Zitadel, pelo gateway) |
| `SK_AUTH_CLIENT_ID` | Client ID da aplicação `cli` no projeto `clients` |
| `SK_AUTH_ALLOW_INSECURE_HTTP` | `true` só onde não há TLS (dev) |
| `SK_API_URL` | Endereço da API (gateway), para todos os módulos |
| `SK_API_ALLOW_INSECURE_HTTP` | `true` só onde não há TLS (dev) |
| `SK_CORE_PROJECT_ID` | ID do projeto `roles-core` |
| `SK_SUM_PROJECT_ID` | ID do projeto `roles-sum` |
| `SK_IPM_PROJECT_ID` | ID do projeto `roles-ipm` |
| `SK_BSM_PROJECT_ID` | ID do projeto `roles-bsm` |
| `SK_OPERATOR_PROJECT_ID` | ID do projeto `roles-operator` (só para operadores) |

**Todas as linhas precisam de `export`.** Sem ele, o `source` define a variável só no shell e a CLI não a enxerga. Nesse caso o login **omite a audience em silêncio** e o token vem sem as roles daquele projeto.

### Dev

O mapa de endereços, o `/etc/hosts` e as credenciais da stack local estão em [`infrastructure/dev/README.md`](../../infrastructure/dev/README.md). Valores de dev:

```bash
export SK_AUTH_ISSUER=http://ipm-dev.smarkee.com.br:8080
export SK_AUTH_ALLOW_INSECURE_HTTP=true     # dev não tem TLS
export SK_API_URL=http://api-dev.smarkee.com.br:8080
export SK_API_ALLOW_INSECURE_HTTP=true
```

Os IDs (`SK_AUTH_CLIENT_ID` e os cinco `SK_*_PROJECT_ID`) são os do **seu** Zitadel de dev: cada instância gera IDs próprios, e eles mudam se o Zitadel for recriado.

### Stg

O mecanismo é o mesmo de dev: o `.env` do stg com o issuer, a URL da API e os IDs do Zitadel do stg. Os valores do stg **ainda não existem** (a configuração do Zitadel para stg e prd não está decidida, ver [`IMPLEMENTATION-STATUS.md`](../platform/IMPLEMENTATION-STATUS.md)). Quando existirem, o stg deve ter TLS, então `SK_*_ALLOW_INSECURE_HTTP` não deve ser `true`.

### Conferir o que vale

```bash
source .env
env | grep PROJECT_ID          # devem aparecer as 5 variáveis
uv run sk config list          # cada chave, o valor efetivo e a origem (default, file ou env)
```

Se `env | grep PROJECT_ID` mostrar menos de cinco, falta `export` no `.env`.

## 3. Login como usuário comum

```bash
source .env
uv run sk auth login           # abre o navegador; a URL também é impressa
uv run sk auth whoami
```

O token só traz as permissões que existiam quando foi emitido. Depois de mudar roles de um usuário, use `uv run sk auth refresh`.

## 4. Login como operador

O operador é um usuário da organização `operator` no Zitadel (decisão [`0084`](../../.decisions/0084-organizacao-operator-e-projeto-roles-operator.md)). Em dev, o usuário padrão é `admin@operator.smarkee.internal`, e a senha é a definida no provisionamento do Zitadel de dev. **Não registre a senha em arquivo versionado, log ou documento.**

As permissões `*.admin` (por exemplo `ipm.role.admin`) ficam no projeto `roles-operator`. Elas só entram no token se o login pedir a audience desse projeto, ou seja, **só com `SK_OPERATOR_PROJECT_ID` exportado** (e `SK_BSM_PROJECT_ID`, para o `bsm`). Um operador que entra sem essa variável **não recebe** as roles de operador, e o Receiver o trata como usuário comum.

### Do zero (limpar tudo e logar de novo)

1. **Confira o `.env`**: as cinco variáveis `SK_*_PROJECT_ID` com `export` (seção 2).
2. **Apague a sessão antiga**: `rm ~/.config/sk/credentials.json`.
3. **Limpe a Organization ativa**, se houver uma obsoleta (seção 6): remova a linha `organizationId` da seção `[ipm]` em `~/.config/sk/config.toml`. O `sk config set ipm.organizationId ""` é recusado ("cannot be empty").
4. **Abra um terminal novo** e carregue o ambiente:
   ```bash
   cd clients/cli
   source .env
   env | grep PROJECT_ID
   ```
5. **Faça o login**: `uv run sk auth login`. No navegador, entre com o usuário operador. Se o navegador já tiver outro usuário logado no Zitadel, use uma janela anônima ou encerre a sessão lá antes.
6. **Confira**: `uv run sk auth whoami` e `uv run sk ipm role list`.

### Conferir se o token é de operador

O `whoami` só mostra o usuário. Para ver as `*.admin` do token:

```bash
python3 - <<'EOF'
import json, base64, pathlib
c = json.loads(pathlib.Path.home().joinpath(".config/sk/credentials.json").read_text())
tok = next(v for v in c.values() if isinstance(v, str) and v.startswith("ey") and v.count(".") == 2)
p = json.loads(base64.urlsafe_b64decode(tok.split(".")[1] + "=="))
print(sorted(x for k, v in p.items() if k.endswith(":roles") for x in v if x.endswith(".admin")))
EOF
```

Para o operador de dev, a lista deve trazer `bsm.account.admin`, `core.account.admin`, `ipm.group.admin`, `ipm.organization.admin`, `ipm.permission.admin`, `ipm.role.admin` e `ipm.user.admin`. Lista vazia indica `.env` sem `export`.

## 5. Várias sessões ao mesmo tempo

A CLI grava a configuração e as credenciais em `$XDG_CONFIG_HOME/sk/` (padrão `~/.config/sk/`). Para manter, por exemplo, um usuário comum e um operador sem um apagar a sessão do outro, aponte cada terminal para um diretório próprio:

```bash
export XDG_CONFIG_HOME=$HOME/.config/sk-operador     # só neste terminal
uv run sk auth login
```

O `credentials.json` guarda tokens (permissão `0600`): trate o diretório como segredo.

## 6. Problemas conhecidos

| Sintoma | Causa | O que fazer |
|---|---|---|
| `Role not found.` em `sk ipm role list` (e `404` no log do gateway com `organizationId=...`) | `ipm.organizationId` no `config.toml` aponta para uma Organization que não existe mais (por exemplo, após `scripts/dev/cleanup`) e o usuário não é operador. A API devolve `404` para não revelar existência, e a listagem inteira falha | Remova `organizationId` do `config.toml` ou ative uma Organization válida. Com `ipm.role.admin` no token, o filtro não bloqueia |
| O token do operador não tem nenhuma `*.admin` | `SK_BSM_PROJECT_ID` ou `SK_OPERATOR_PROJECT_ID` sem `export` no `.env` | Corrija o `.env`, apague o `credentials.json` e refaça o login (seção 4) |
| `sk auth login` recusa o login citando valores provisórios | Faltam o client ID ou os IDs dos projetos (o padrão ainda é `000000000000000000`) | Carregue o `.env` (`source .env`) |
| `URL without TLS refused` | `SK_*_ALLOW_INSECURE_HTTP` não está `true` e o endereço é `http` | Em dev, exporte as duas variáveis `ALLOW_INSECURE_HTTP`. Em stg, use `https` |
| `could not reach the API` ou issuer em `api.smarkee.com.br` | O `.env` não foi carregado neste terminal, e a CLI usou o padrão de produção | `source .env` e confira com `sk config list` |

## 7. Para scripts

`--output json` e `--raw` valem **antes** do subcomando (`uv run sk --output json ipm role list`). Veja a seção "Para scripts" do [`README` da CLI](../../clients/cli/README.md) e a decisão [`0093`](../../.decisions/0093-saida-global-da-cli-raw-e-json.md).
