# Conformidade da `sk` com o clig.dev

Matriz de referência da skill `cli-ux`. Fonte: <https://clig.dev/> (lida por inteiro em 2026-10-26). O clig.dev separa **Basics** (obrigatório: sem isso a CLI é difícil de usar ou "quebrada") do restante (desejável).

Como ler a coluna **Estado**:

- `Conforme`: verificado por execução ou leitura de código.
- `Divergência registrada`: a `sk` diverge de propósito e há decisão em `.decisions/` que diz isso.
- `Divergência SEM decisão`: a `sk` diverge, mas nenhuma decisão registra o motivo. Não é "deliberada" até alguém decidir: leve ao responsável (`AGENTS.md` §25.1).
- `Lacuna`: o clig.dev recomenda e a `sk` não faz.
- `N/A`: não se aplica ao produto.

Reexecute as verificações antes de repetir um estado: o código muda mais rápido que esta tabela.

## Basics

| Regra do clig.dev | Estado | Evidência / como verificar |
|---|---|---|
| Biblioteca de parsing (Typer) | Conforme | `pyproject.toml` |
| Código de saída 0 no sucesso e ≠ 0 na falha, por modo de falha | Conforme | `0` ok, `1` execução, `2` uso (`shared.py`); `sk config get x.y` → 2, sem sessão → 1 |
| Resultado em `stdout`, mensagens em `stderr` | Conforme | erros/avisos/`note` em `stderr`; `sk --output json auth login` → stdout vazio |

## Help

| Regra | Estado | Evidência / como verificar |
|---|---|---|
| `--help` em todo comando | Conforme | `test_help.py` |
| `-h` também mostra a ajuda | Conforme | `sk -h` e `sk ipm role list -h` → código 0 (`help_option_names` em `main.py`) |
| Ajuda concisa sem argumentos | Conforme (com ressalva) | `sk` e `sk ipm` mostram a ajuda; o código de saída é 2 (o clig.dev não fixa o código) |
| `sk help <cmd>` (CLIs estilo git) | Lacuna | `sk help ipm` → código 2 |
| Sugestão quando o usuário erra o nome | Conforme | `sk ipm rol list` → "Did you mean 'role'?" |
| Exemplos na ajuda, antes das opções | **Lacuna** | `sk/help.py` não tem campo de exemplo; 0 ocorrências de "example" em `sk --help` |
| Link para a doc web na ajuda | Conforme | rodapé de `sk --help` com `https://docs.smarkee.com.br` |
| Link de suporte/feedback na ajuda | **Lacuna** | só há o endereço da documentação; falta um canal de suporte |
| Comandos/opções mais comuns primeiro | Não verificado | a ordem dos grupos na raiz não foi avaliada contra o uso real |
| `--version` | Conforme | `sk --version` → `sk <versão do pacote>`, código 0, também com `--raw`/`--output json` |

## Output

| Regra | Estado | Evidência / como verificar |
|---|---|---|
| Saída legível por humanos em primeiro lugar | Conforme | painéis e tabelas Rich (decisão 0021) |
| Saída para máquinas onde não prejudica | Conforme | `--output json` e `--raw` (decisão 0093) |
| `--plain` para tabela legível por `grep`/`awk` | Divergência registrada (nome) | equivale a `--raw` (0093); o clig.dev chama de `--plain`, e o nome `--raw` foi escolha do responsável |
| `--json` | Divergência registrada (nome) | é `--output json`, global e **antes** do subcomando (0093) |
| Quando `stdout` não é TTY, sair legível por máquina | **Divergência SEM decisão** | em pipe a `sk` mantém as bordas Rich (largura 100) e só vira TSV com `--raw`. A 0093 define `--raw`, mas não registra por que o pipe não o ativa sozinho |
| Dizer ao usuário o que mudou; sugerir o próximo comando | Conforme | painel + `note` com o `get` (`shared.py`) |
| Sem animação fora de TTY | Conforme | não há animação (ver Robustness) |
| `-q`/`--quiet` | Lacuna | não existe |
| Cor só com intenção; desligar fora de TTY | Conforme | pipe → 0 escapes de cor; `stderr` é avaliado à parte (erro colorido com `stdout` em pipe) |
| `NO_COLOR` | Conforme | pseudo-terminal (`script -q /dev/null`): padrão 15 linhas com cor; `NO_COLOR=1` → 0. Sobram atributos (negrito), que o NO_COLOR não proíbe |
| `TERM=dumb` | Conforme | pseudo-terminal: 0 escapes |
| `FORCE_COLOR` | Conforme | em pipe, `FORCE_COLOR=1` volta a colorir |
| `--no-color` | Divergência registrada | decisão 0041 (sem opções de ambiente na linha de comando); `NO_COLOR` cobre o caso |
| Símbolos onde esclarecem | Conforme | `✓ ✗ → !` |
| Não mostrar informação só útil ao autor | Conforme | ajuda sem detalhe de implementação (0022) |
| `stderr` sem rótulos de log | Conforme | |
| Paginador para saída longa | N/A | listas são curtas por contrato |

## Errors

| Regra | Estado | Evidência / como verificar |
|---|---|---|
| Reescrever o erro para humanos, com causa e dica | Conforme (1 defeito) | `ui.error(title, detail, hint)`. Defeito: `config.py:110` aconselha `sk init --force`, comando extinto (0036) |
| Sem traceback por padrão | Conforme | `main()` captura `Exception` e mostra o painel "Unexpected error" só com o tipo, código 1 (`KeyboardInterrupt` segue seu curso) |
| Erro inesperado: como reportar o bug | **Lacuna parcial** | o painel aponta a documentação (`https://docs.smarkee.com.br`); falta um canal de suporte e um modo de diagnóstico (traceback) |
| Erros do mesmo tipo agrupados | Não verificado | cada comando falha com um painel; não há caso de múltiplos erros para testar |

## Arguments and flags

| Regra | Estado | Evidência / como verificar |
|---|---|---|
| Preferir flags a argumentos posicionais | Conforme | tudo é `--opção` (`--resource-id`, `--name`) |
| Versão longa de toda flag | Conforme | |
| Poucas flags de uma letra | Conforme | só `-h` (ajuda) |
| Nomes padrão de flags | Parcial | `--output` na `sk` é formato; no clig.dev `-o/--output` é arquivo de saída. `--force`/`--dry-run` não existem; `--yes` só em `account delete` |
| Confirmar antes de algo perigoso | Divergência registrada | a CLI não tem prompt: a guarda é o par `protect`/`unprotect` no loop (0043) e `--yes` na conta |
| Nunca exigir um prompt | Conforme | só o login abre navegador |
| `-` para ler `stdin`/escrever `stdout` | Parcial | `--public-key-file -` lê a `stdin` (pipe, teto de 64 KiB, sem eco do conteúdo). `auth login --key-file -` é recusado de propósito (a sessão relê o arquivo a cada renovação). Escrever em `stdout` não existe |
| Valor opcional com palavra especial ("none") | Conforme | `sk config unset <chave>` devolve a chave ao padrão (idempotente; avisa se uma variável `SK_*` ainda vale) |
| Ordem independente de opções e subcomandos | Divergência registrada | `--output`/`--raw` só antes do subcomando (0093); o clig.dev recomenda o contrário |
| Segredo não vem por flag nem por variável de ambiente | Conforme | só `--key-file` (arquivo, `0600`); não há `--token`/`--password`; nenhum `SK_*` de token |

## Interactivity

| Regra | Estado | Evidência |
|---|---|---|
| Prompt só em TTY; `--no-input` | N/A | a CLI não faz prompt |
| Ctrl-C sai rápido | Não verificado | um processo em segundo plano ignora SIGINT; teste só em pseudo-terminal interativo |

## Subcommands

| Regra | Estado | Evidência |
|---|---|---|
| Consistência de nomes/verbos entre objetos | Conforme | `create/update/protect/unprotect/delete/get/list` em todos os `ipm` |
| `substantivo verbo`, dois níveis | **Divergência SEM decisão** | a `sk` usa três (`sk ipm role list`). Plausível (módulo → tipo → ação), mas nenhuma decisão o registra |
| Sem comandos ambíguos (ex.: `update` x `upgrade`) | Conforme | a árvore de comandos não tem pares parecidos |
| Aliases explícitos e estáveis | Conforme | `sa` = `serviceaccount` |
| Sem abreviação arbitrária | Conforme | `sk ipm rol` não vale |

## Robustness

| Regra | Estado | Evidência |
|---|---|---|
| Validar a entrada cedo | Conforme | código 2 antes de chamar a API; `--output json` recusado antes do efeito |
| Responder em < 100 ms; progresso em operação longa | Conforme | `--wait` mostra o estado e o tempo decorrido na stderr (`ui.waiting`): em terminal, um indicador numa linha, apagado ao sair; fora de terminal, uma linha por mudança de estado. A stdout não é tocada |
| Timeout configurável com padrão razoável | Parcial | `--timeout` do `--wait` e `api.timeoutSeconds` (`SK_API_TIMEOUT_SECONDS`, 1 a 300, padrão 10) existem; o do provedor de identidade (`oidc.py`, 30 s) segue fixo |
| Recuperável / idempotente | Conforme | `Idempotency-Key` por pedido; `disable` sobre desabilitado é "Nothing to do" (código 0) |

## Future-proofing

| Regra | Estado | Evidência |
|---|---|---|
| Mudanças aditivas; avisar antes de quebrar | Conforme | decisões 0036/0093 preservam contratos |
| Sem comando "pega-tudo" | Conforme | |
| Saída humana pode mudar; scripts usam `--raw`/`--output json` | Conforme | 0093 |

## Configuration, ambiente, nomes, distribuição, analytics

| Regra | Estado | Evidência |
|---|---|---|
| XDG | Conforme | `XDG_CONFIG_HOME` respeitado (usado no isolamento da auditoria) |
| Precedência flag > env > arquivo > padrão | Conforme | decisão 0008 (a 0041 tira as opções de ambiente da linha de comando) |
| Variáveis `MAIUSCULAS_COM_UNDERSCORE`, prefixo próprio | Conforme | `SK_<SEÇÃO>_<CAMPO>` |
| `.env` não substitui arquivo de configuração | Conforme | `config.toml` |
| Nome curto, minúsculo, memorável | Conforme | `sk` |
| Sem telemetria sem consentimento | Conforme | não há |
