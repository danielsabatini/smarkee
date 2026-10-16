# 0023 — `sk init` com os endereços de produção e `sk config` para alterar o arquivo

- **Data:** 2026-10-13
- **Status:** Aceita. Complementa as decisões 0008 (configuração da CLI) e 0013 (ordem de acesso e exposição do Zitadel); a regra de precedência da 0008 não muda.

> **Atualização (decisão 0036):** o `sk init` foi removido, e os valores de produção passaram a ser o padrão da CLI; o arquivo só sobrescreve. O que esta decisão diz sobre `sk init` está superado; `sk config` continua.

## Contexto

A CLI `sk` dependia de o usuário configurar endereços à mão: `sk auth init` gravava só a seção `[auth]`, e nenhum comando gravava `[core] apiUrl`. Um usuário final não consegue fazer isso sem editar o arquivo ou conhecer variáveis de ambiente.

Os endereços da plataforma não são segredos. O provedor de identidade (`issuer`), a URL da API e o client ID de uma aplicação nativa são públicos. Eles variam só por ambiente, e o ambiente de produção (prd) é o que o usuário final usa.

A proposta inicial era um seletor de ambiente (`--env`) com uma tabela de endereços embutida. Ela foi descartada: exige que o usuário conheça ambientes, e a CLI passa a ter um conceito de ambiente em tempo de execução que a configuração já resolve.

## Decisão

- **Nomes dos hosts, por papel e por ambiente**, `<papel>-<ambiente>.smarkee.com.br`, com prd sem sufixo:

  | Papel | dev | stg | prd |
  |---|---|---|---|
  | Provedor de identidade (Zitadel) | `ipm-dev.smarkee.com.br` | `ipm-stg.smarkee.com.br` | `ipm.smarkee.com.br` |
  | API da plataforma (gateway) | `api-dev.smarkee.com.br` | `api-stg.smarkee.com.br` | `api.smarkee.com.br` |

  `ipm-*` é o host de identidade. Não designa o módulo `features/ipm` (Organization).
- **`sk init`** é o comando de topo que cria o arquivo `config.toml`. Grava `[auth]` e `[core]` com os **padrões de produção**: `https://ipm.smarkee.com.br` e `https://api.smarkee.com.br`. Os parâmetros (`--issuer`, `--client-id`, `--api-url`, `--allow-insecure-http`) e as variáveis `SK_*` substituem esses padrões. Não sobrescreve um arquivo existente sem `--force`.
- **`sk config`** consulta e altera o arquivo: `list` mostra todas as chaves; `get` imprime o valor; `set` valida a chave e o valor e regrava o arquivo. As chaves vêm dos modelos de configuração, e um campo novo aparece sem mudança no comando.
- **Client ID de produção provisório.** O `sk init` grava `pendente-prd` e avisa que o valor definitivo ainda não existe. A troca é pendente: deve acontecer quando o ambiente de produção for criado, e antes disso o login de produção não funciona.
- **HTTP.** O `init` recusa endereço `http` sem `--allow-insecure-http`; com a flag, libera as duas seções. O `config set` aceita `http` com aviso, e o uso recusa o endereço enquanto a permissão da seção não estiver ativa.
- **O arquivo continua opcional.** Parâmetro, variável `SK_*` e arquivo seguem a ordem da 0008. Sem configuração, a mensagem de erro manda rodar `sk init`.
- **`sk auth init` foi removido.** A CLI ainda não foi lançada, então não há compatibilidade a manter.

## Justificativa

- Um comando de topo, com padrões de produção, deixa o uso mais simples: o usuário final roda `sk init` e depois `sk auth login`.
- O `sk config` evita editar o arquivo à mão e permite que as chaves cresçam com a CLI, sem novo comando para cada parâmetro.
- Manter a precedência da 0008 preserva o uso por variável de ambiente, que automação e testes usam, e não obriga o arquivo.
- Os endereços de produção embutidos não aumentam a superfície de ataque, porque são públicos. O que protege a conta são o login e os tokens.
- **Alternativas descartadas:**
  - *Seletor `--env` com tabela embutida:* obriga o usuário a conhecer ambientes, e a CLI passa a carregar uma tabela que a configuração já resolve.
  - *Arquivo obrigatório:* quebra o uso por variável de ambiente e a automação.
  - *Preservar comentários do arquivo no `config set`:* exigiria uma dependência nova de edição de TOML. O arquivo é gerenciado pelo `sk`, e isso é dito na ajuda.

## Consequências

- Mudar um endereço de produção exige publicar a CLI de novo. É o custo de embutir os padrões.
- O client ID de produção (`pendente-prd`) precisa ser trocado quando o ambiente existir. Até lá, o `sk init` avisa.
- `stg` e `prd` ainda não estão implantados. Os endereços são o alvo, e os valores definitivos (porta, certificado e disponibilidade) são confirmados na implantação de cada ambiente.
- A configuração do dev continua válida: o dev é configurado com `sk init --force` e os endereços de dev (`http://…:8080`), documentados em `infrastructure/dev/README.md`.
- `sk config set` regrava o arquivo inteiro: comentários feitos à mão não são preservados.
- `sk config get` imprime o valor puro na saída padrão. Essa é a exceção à regra de saída pela `ui` da decisão 0021.
