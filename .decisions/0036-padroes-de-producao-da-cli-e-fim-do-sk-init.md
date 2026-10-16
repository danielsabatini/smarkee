# 0036 — Os valores de produção são o padrão da CLI, e `sk init` deixa de existir

- **Data:** 2026-10-16
- **Status:** Aceita. Substitui a parte da decisão 0023 que criou o `sk init` e a que fazia do arquivo o lugar dos endereços; a precedência da decisão 0008 não muda.

## Contexto

A 0023 criou o `sk init`, que gravava no `config.toml` os endereços de produção, para o usuário final não editar o arquivo. Na prática, o arquivo virou um passo obrigatório: sem ele, a CLI não tinha emissor nem API, e os IDs dos projetos de roles (que o login passou a exigir com a decisão 0034, para o token valer no Receiver de cada módulo) não tinham nenhum padrão. Um usuário final precisaria gravar seis valores que são sempre os mesmos em produção e que não são segredo.

## Decisão

- **Os valores da plataforma são o padrão dos campos da configuração:** `auth.issuer`, `auth.clientId`, `api.url` e os `projectId` de `core`, `sum` e `ipm`. A CLI funciona em produção sem arquivo, sem variável e sem opção. `allowInsecureHttp` continua falso e é só de desenvolvimento.
- **`sk init` é removido.** Nenhum comando cria o arquivo por conta própria.
- **O arquivo de configuração continua existindo, só para sobrescrever** (a ordem da 0008 é a mesma: parâmetro → variável → arquivo → padrão). Quem usa dev ou stg sobrescreve com o arquivo, com `SK_*` ou com as opções.
- **O endereço da API passa a `[api]`** (`api.url` e `api.allowInsecureHttp`, `SK_API_URL`): ele vale para todos os módulos, e `[core]` guardava, além dele, o `projectId` do módulo core. `[core]` fica só com o `projectId`, ao lado de `[sum]` e `[ipm]`. Um arquivo antigo com `[core] apiUrl` é recusado (chave desconhecida).
- **`sk config`** passa a mostrar a configuração **efetiva**: `list` mostra cada chave, o valor e a origem (`default`, `file` ou `env`), e `get` imprime o valor efetivo. `set` cria o arquivo se não existir e grava **só as sobrescritas**: um valor que ficou no padrão não vai para o arquivo. Não há `unset`.
- **O que ainda não existe em produção é marcado, e não escondido:** o client ID e os IDs dos três projetos de roles só nascem quando o Zitadel de produção for provisionado. O padrão deles é o marcador `000000000000000000` (18 zeros), e `sk auth login` recusa o login nomeando os valores que faltam (código 2), em vez de seguir com um valor que falharia adiante sem dizer por quê.

## Justificativa

- **Simplicidade e segurança:** o usuário final não configura nada, e não há valor de produção digitado à mão (e errado). Os valores não são segredo (a 0023 já dizia).
- **Robustez:** o arquivo deixa de ser um passo obrigatório que o usuário pode esquecer, e o erro de um valor ausente nomeia o valor.
- **Alternativa descartada:** descobrir os IDs dos projetos por um endpoint da plataforma. É uma peça nova, sem necessidade enquanto houver poucos módulos. Pode voltar quando houver muitos.

## Consequências

- **Dev e stg configuram por sobrescrita:** `sk config set` para cada valor (README da CLI e `infrastructure/dev/README.md`). A configuração existente de quem já usa o dev continua válida; falta só `ipm.projectId`, que passa a ser exigido pelo login enquanto o padrão for `000000000000000000`.
- **Preencher os padrões de produção** (client ID e os três IDs em `sk/defaults.py`) é pendência de quando o Zitadel de produção existir. Enquanto forem `000000000000000000`, o login em produção é recusado com a lista do que falta.
- **Quebra de compatibilidade (CLI em `0.x`):** o comando `sk init` desaparece; quem o usava em script passa a usar `sk config set`.
- **Não verificado:** o comportamento contra um Zitadel de produção, que ainda não existe.
