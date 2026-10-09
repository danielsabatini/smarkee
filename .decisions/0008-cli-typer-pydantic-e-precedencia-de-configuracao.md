# 0008 — CLI: Typer, Pydantic e precedência de configuração

- **Data:** 2026-10-09
- **Status:** Aceita

## Contexto

O CLI `sk` vai crescer com os comandos da plataforma (`sk auth ...`) e dos módulos (`sk ipm ...`). Cada comando precisa de configuração (issuer, client ID, URLs de API) vinda de mais de uma fonte, com uma ordem previsível e igual em todos os comandos.

## Decisão

- **Python 3.14**, **Typer** para os comandos e **Pydantic** com **pydantic-settings** para a configuração (`components/cli`).
- **Precedência**, da maior para a menor: **parâmetro → variável de ambiente → arquivo de configuração → default**.
  - Os parâmetros do Typer são repassados ao pydantic-settings como argumentos de inicialização, somente quando informados (`None` e flag não ativada não são repassados).
  - As variáveis de ambiente são lidas só pelo pydantic-settings. O Typer não usa `envvar`, para que a precedência tenha uma única fonte.
  - O arquivo de configuração é `$XDG_CONFIG_HOME/sk/config.toml` (padrão `~/.config/sk/config.toml`), acrescentado entre o ambiente e o default por `settings_customise_sources`. Arquivos `.env` e diretórios de secrets não são lidos.
- **Nomes:** uma seção por escopo. Variável `SK_<SEÇÃO>_<CAMPO>` e tabela `[<seção>]` no arquivo: `SK_AUTH_*` e `[auth]` para a plataforma, `SK_IPM_*` e `[ipm]` para o módulo IPM.
- **Grafia por meio** (`docs/SCHEMA.md`, *Grafia dos nomes por meio*): chaves do arquivo em camelCase (`clientId`), flags em kebab-case (`--client-id`), variáveis em maiúsculas (`SK_AUTH_CLIENT_ID`) e campos Python em snake_case (`client_id`). A conversão do arquivo é feita só pela fonte TOML do sk (`CamelCaseTomlSettingsSource`). Uma chave fora do camelCase (inclusive `client_id`) ou desconhecida é rejeitada, para que um erro de digitação não seja ignorado em silêncio.
- **`sk auth init`** cria o `config.toml` a partir dos parâmetros ou das variáveis (sem ler o arquivo que vai criar). Issuer e client ID são obrigatórios e **não têm valor padrão no código**, porque mudam por ambiente (dev, stg, prd) e quando a instância do Zitadel é recriada. O comando não sobrescreve um arquivo existente sem `--force`.
- O arquivo de configuração guarda configuração, e não credenciais. Os tokens ficam em `credentials.json` (decisão 0007).
- `pretty_exceptions_show_locals=False` explícito no Typer: mostrar variáveis locais em erros exporia tokens.

## Justificativa

- Parâmetro, ambiente e default já são a ordem nativa do pydantic-settings. Só o arquivo exige configuração, então a regra fica explícita e testável sem código de mesclagem próprio.
- Alias camelCase no modelo (`alias_generator`) foi descartado: verificado com pydantic-settings 2.15, ele faz as variáveis `SK_AUTH_CLIENT_ID` serem rejeitadas, e a alternativa (`validate_by_name`) faria o arquivo aceitar as duas grafias.
- O Typer gera os comandos e a ajuda a partir das assinaturas tipadas e escala melhor que o `argparse` para muitos subcomandos.
- O Pydantic valida e tipa a configuração na fronteira de entrada (`python.md`, seção 23).

## Consequências

- Dependências de runtime do `sk`: `typer` (que traz `click`, `rich` e `shellingham`), `pydantic` e `pydantic-settings` (que traz `python-dotenv`, embora `.env` não seja lido).
- Os textos de ajuda escritos pelo projeto estão em pt-BR. Os textos embutidos do Typer e do Click (`Usage`, `Options`, `Show this message and exit`) permanecem em inglês.
- A marcação Rich nos textos de ajuda está desligada (`rich_markup_mode=None`), para que `[auth]` apareça literalmente.
