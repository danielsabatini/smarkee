# 0041 — CLI sem opções de linha de comando para o ambiente

- **Data:** 2026-10-16
- **Status:** Aceita e implementada. Complementa a 0036 (padrões de produção) e atualiza a precedência da 0008: a CLI não tem opções de linha de comando para o que é do ambiente.

## Contexto

Os comandos aceitavam `--issuer`, `--client-id`, `--allow-insecure-http` e `--api-url` (e a decisão 0036 já deu à CLI os padrões de produção). Em produção ninguém precisa dessas opções; em dev e stg o ambiente se escolhe por variável (`.env`), uma vez por sessão de trabalho, e não a cada comando.

## Decisão

- **`--issuer`, `--client-id`, `--allow-insecure-http` e `--api-url` deixam de existir**, em todos os comandos (`auth login|whoami|refresh`, `register`, `sum service` e `ipm organization`). O provedor, o client ID e a permissão de HTTP sem TLS vêm só de variáveis (`SK_AUTH_ISSUER`, `SK_AUTH_CLIENT_ID`, `SK_AUTH_ALLOW_INSECURE_HTTP` e `SK_API_ALLOW_INSECURE_HTTP`), do arquivo de configuração ou do padrão de produção, nessa ordem de precedência.
- **O endereço da API** vem de `SK_API_URL`, de `[api] url` ou do padrão de produção. A precedência passa a ser variável, arquivo, padrão. Como as outras ferramentas de linha de comando, a CLI não repete na linha de comando o que é escolha do ambiente.
- A permissão de HTTP é separada por alvo: `[auth]` vale para o provedor de identidade e `[api]` para a API; antes, a opção valia para os dois.

## Justificativa

- **Segurança:** HTTP sem TLS não se liga por engano numa linha de comando copiada; é uma escolha do ambiente (dev e stg), visível no `.env`.
- **Simplicidade:** menos opções por comando, uma só fonte para o que é do ambiente.

## Consequências

- **Quebra de contrato da CLI** (versão ainda sem release): quem usava as opções passa a usar variáveis. A mensagem de endereço recusado já aponta `SK_API_ALLOW_INSECURE_HTTP=true`.
- Corrige em parte as decisões 0007, 0008 e 0023, que citam essas opções (histórico mantido).
