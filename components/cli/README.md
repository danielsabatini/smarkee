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

Limitações atuais:

- o `sk` não valida localmente a assinatura do ID token e não usa as claims dele; a identidade exibida vem do userinfo, e a validação dos tokens é responsabilidade das APIs que os recebem;
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
