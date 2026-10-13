# sk — CLI da plataforma smarkee

CLI do usuário da plataforma, em Typer e Pydantic. Requer Python 3.14 e [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run sk --help
```

## Configuração

Cada valor é resolvido nesta ordem, do mais forte para o mais fraco: **parâmetro → variável de ambiente → arquivo de configuração → default** (`.decisions/0008-cli-typer-pydantic-e-precedencia-de-configuracao.md`).

- Variáveis: `SK_<SEÇÃO>_<CAMPO>`, por exemplo `SK_AUTH_CLIENT_ID`. Os módulos usam a própria seção (`SK_IPM_*`).
- Arquivo: `$XDG_CONFIG_HOME/sk/config.toml` (padrão `~/.config/sk/config.toml`), com uma tabela por seção e **chaves em camelCase**. Uma chave desconhecida ou fora do camelCase (por exemplo `client_id`) é rejeitada.
- O mesmo nome muda só de grafia entre os meios: `--client-id`, `SK_AUTH_CLIENT_ID`, `clientId` (`docs/SCHEMA.md`, *Grafia dos nomes por meio*).

O arquivo pode ser criado por `sk auth init` ou à mão:

```bash
uv run sk auth init --issuer URL --client-id ID [--allow-insecure-http] [--force]
```

```toml
[auth]
issuer = "http://ipm-dev.smarkee.com.br:8080"
clientId = "<client-id-da-aplicação-sk>"
allowInsecureHttp = true  # somente em desenvolvimento
```

O `init` usa parâmetro → variável → default (não lê o arquivo que vai criar), exige issuer e client ID, recusa issuer `http` sem `--allow-insecure-http` e não sobrescreve um arquivo existente sem `--force`. Issuer e client ID não têm valor padrão: variam por ambiente (um por ambiente, compartilhado por todas as organizations) e mudam quando a instância do Zitadel é recriada.

O arquivo guarda configuração, e não credenciais. Os tokens ficam em `credentials.json`, no mesmo diretório.

## Autenticação

```bash
uv run sk auth login [--issuer URL] [--client-id ID] [--allow-insecure-http]
```

O login é da plataforma, e não de um módulo. O `sk` autentica o usuário direto no provedor de identidade (Zitadel), pelo gateway, sem API própria de autenticação:

1. obtém o discovery OIDC do issuer e confere que o `issuer` anunciado é o configurado;
2. abre o navegador na URL de autorização (Authorization Code com PKCE S256) e também a imprime, para o caso de o navegador não abrir;
3. recebe o retorno em `http://127.0.0.1:<porta efêmera>/callback`, escutando só no loopback, por no máximo 5 minutos, e confere o `state`;
4. troca o código pelos tokens (cliente público, sem segredo) e consulta o userinfo para exibir o usuário autenticado;
5. grava os tokens em `$XDG_CONFIG_HOME/sk/credentials.json` (padrão `~/.config/sk/credentials.json`), com permissão `0600` e gravação atômica. Um novo login substitui o anterior.

| Opção | Variável de ambiente | Chave em `[auth]` | Significado |
|---|---|---|---|
| `--issuer` | `SK_AUTH_ISSUER` | `issuer` | URL do issuer OIDC, acessado pelo gateway |
| `--client-id` | `SK_AUTH_CLIENT_ID` | `clientId` | Client ID da aplicação nativa do `sk` no provedor |
| `--allow-insecure-http` | `SK_AUTH_ALLOW_INSECURE_HTTP=true` | `allowInsecureHttp = true` | Aceita issuer `http`. Somente em desenvolvimento |

Códigos de saída: `0` sucesso; `1` falha no login ou na gravação, ou cancelamento (Ctrl+C); `2` uso incorreto (issuer ou client ID ausente, configuração inválida).

### `sk auth whoami`

```bash
uv run sk auth whoami [--allow-insecure-http]
```

Mostra o usuário da sessão gravada e confirma com o provedor que o acesso ainda vale:

1. lê `credentials.json`; sem o arquivo, diz que não há sessão e aponta `sk auth login`;
2. se o acesso já venceu pela data gravada, para ali, sem consultar o provedor;
3. consulta o userinfo com o access token. Se o provedor recusar ou não responder, a mensagem traz a causa e o comando não mostra o usuário.

A saída nunca mostra tokens. Código `0` com sessão válida; `1` sem sessão, sessão vencida ou sessão não confirmada pelo provedor.

Limitações atuais:

- o `sk` não valida localmente a assinatura do ID token e não usa as claims dele; a identidade exibida vem do userinfo, e a validação dos tokens é responsabilidade dos Receivers que os recebem;
- não há `logout` nem renovação automática pelo refresh token;
- o arquivo de credenciais guarda tokens em texto claro, protegido apenas pela permissão do sistema de arquivos.

Configuração do Zitadel no ambiente de desenvolvimento: `infrastructure/dev/README.md`, seção *Login do CLI*.

## Qualidade

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest --cov --cov-report=term-missing
```

Os testes de integração (`tests/integration`) exercitam o fluxo completo contra um provedor OIDC falso em loopback; não dependem do Zitadel.

## Cadastro (`sk register`)

```bash
uv run sk register --name Ana --surname Souza --email ana@dominio.com
```

Pede o cadastro de um usuário pela API do módulo `core`. É **anônimo**: não exige login, não envia token (mesmo que existam credenciais salvas) e não pede senha. A pessoa define a senha depois, na página do provedor, a partir do e-mail de ativação. O cadastro é assíncrono: o comando confirma que o pedido foi aceito (`resourceId` e `operationId`), e não que a conta já existe.

| Opção | Variável de ambiente | Chave em `[core]` | Significado |
|---|---|---|---|
| `--name` | | | Nome próprio (obrigatório, 1 a 256 caracteres) |
| `--surname` | | | Sobrenome (obrigatório, 1 a 256 caracteres) |
| `--email` | | | E-mail, também o nome de login (obrigatório) |
| `--api-url` | `SK_CORE_API_URL` | `apiUrl` | URL base da API do módulo core, pelo gateway |
| `--allow-insecure-http` | `SK_CORE_ALLOW_INSECURE_HTTP=true` | `allowInsecureHttp = true` | Aceita a API em HTTP. Somente em desenvolvimento |

```toml
[core]
apiUrl = "http://api-dev.smarkee.com.br:8080"
allowInsecureHttp = true  # somente em desenvolvimento
```

Os dados são validados antes do envio, com os mesmos limites do contrato. Um e-mail mal formado não gera nenhuma chamada à API. Códigos de saída: `0` pedido aceito; `1` serviço indisponível, limite de taxa ou falha de conexão; `2` uso incorreto ou dado recusado pela API.

Depois do cadastro, a pessoa recebe dois e-mails do provedor (verificação de e-mail e definição de senha). Enquanto a conta não é ativada, `sk auth login` não consegue autenticar. O passo a passo para ativar a conta, e para pedir outro link ou código quando o anterior expirou, está em `features/core/user/README.md`, seção 4.7.

## Saída no terminal

Os comandos mostram sucesso em painel e erro com causa e dica de correção. Cores aparecem só em terminal interativo, e `NO_COLOR` é respeitado. A apresentação está em `src/sk/ui.py` (`.decisions/0021-apresentacao-da-cli-com-rich.md`). A saída de sucesso vai para a saída padrão, e a de erro para a saída de erro.

## Textos de ajuda

A ajuda (`--help`) segue um padrão único, montado por `src/sk/ajuda.py` e verificado em `tests/unit/test_ajuda.py` (`.decisions/0022-padrao-dos-textos-de-ajuda-da-cli.md`). Cada opção aparece como:

```text
--api-url  Endereço da API da plataforma. [String] [env SK_CORE_API_URL | arquivo [core] apiUrl] [obrigatório]
```

- `[String]` ou `[Booleano]`: o tipo do valor.
- `[env … | arquivo … | padrão …]`: de onde o valor pode vir, na ordem de resolução (parâmetro, variável de ambiente, arquivo de configuração, padrão). Só aparecem as fontes que existem.
- `[obrigatório]` (vermelho) ou `[opcional]`: sem padrão, a opção é obrigatória.

Os textos descrevem o que o comando faz, sem detalhes de implementação. Novos comandos usam `comando()` e `opcao()`.
