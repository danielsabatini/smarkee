# 0095 — Opção global `-q`/`--quiet` da CLI

- **Data:** 2026-10-26
- **Status:** Aceita e implementada. Complementa a 0093 (saída global) e é compatível com a 0041 (sem opções de ambiente na linha de comando).

## Contexto

Em scripts e CI, a CLI `sk` imprime orientações ("Follow it with…", "Confirm it with…") e, com `--wait`, o progresso da espera. São úteis a uma pessoa e ruído num log. Os padrões de mercado (`curl -s`, `git -q`, `kubectl --quiet`, `gh`) oferecem uma opção que silencia o que é só informativo, sem esconder erro nem resultado.

## Decisão

- **`-q` / `--quiet`**, opção do grupo raiz, válida para qualquer comando. Fica **antes do subcomando**, como `--output` e `--raw`: `sk -q ipm role create …`. Depois do subcomando, o Typer recusa com código 2.
- **Suprime somente o que é informativo:** as notas de orientação (`ui.note`, inclusive a de "lista vazia" em `table`) e o progresso do `--wait`.
- **Nunca suprime:** erros, avisos (`ui.warning`), o painel ou a tabela de resultado, nem o documento de `--output json`/`--raw`. O código de saída não muda.
- **Sem `SK_QUIET`:** como o formato de saída, é escolha de cada execução, e não do ambiente (0041, 0093).
- O modo é gravado a cada invocação pelo callback raiz, dentro de `OutputMode`, como `raw` e `format`.

## Justificativa

- **Segurança e robustez:** um aviso (por exemplo, "uma variável `SK_*` ainda prevalece") pode mudar o que o usuário entende ter acontecido; por isso nunca é silenciado. `--quiet` não pode esconder falha.
- **Simplicidade:** um booleano no modo de saída já existente, sem dependência nova e sem caminho paralelo.
- **Referência de mercado (§2.7):** `git -q`, `curl -s`, `kubectl --quiet`. Divergência: vem antes do subcomando, por ser opção do grupo raiz (igual à 0093).
- **Caminho aditivo (§2.6):** um nível `-qq` ou `--verbose` entraria em `OutputMode` sem mudar os comandos.

## Consequências

- Quem usa `--quiet` com `table` e uma listagem vazia não vê mensagem alguma: o código de saída 0 é o sinal. Para um array vazio explícito, usa-se `--output json`.
- Todo texto informativo novo passa por `ui.note` (ou pelo progresso), e assim respeita a opção; um aviso ou erro novo continua passando por `ui.warning`/`ui.error`.
- Testes restauram o padrão com `output.configure(raw=False)`.
