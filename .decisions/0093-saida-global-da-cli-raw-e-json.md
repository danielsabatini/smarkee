# 0093 — Opções globais de saída da CLI: `--raw` e `--output table|json`

- **Data:** 2026-10-26
- **Status:** Aceita e implementada. Complementa a 0021 (apresentação com Rich), atualiza a exceção do `sk config get` e é compatível com a 0041 (sem opções de ambiente na linha de comando).

## Contexto

A saída da CLI `sk` é feita para pessoas (painéis e tabelas do Rich). Para automação (`jq`, `awk`, scripts de CI), o usuário precisava extrair `resourceId` de caixas desenhadas. Os padrões de mercado são `kubectl -o json`, `gh --json` e `aws --output`: uma opção global que troca o formato, sem mudar os comandos.

Duas decisões de escopo do responsável: sem YAML (evitar dependência nova, §21 do `AGENTS.md`) e sem variável de ambiente `SK_OUTPUT` (a 0041 mantém a linha de comando livre do que é do ambiente, mas o formato é escolha de cada execução, e não do ambiente; fica só na linha de comando).

## Decisão

- **`--output table|json`** (padrão `table`) e **`--raw`**, opções do grupo raiz, válidas para qualquer comando. Ficam **antes do subcomando**: `sk --output json ipm role list`. Depois do subcomando, o Typer recusa com código 2.
- **`--raw`** é saída sem caixa nem cor: tabelas viram TSV com cabeçalho, painéis viram linhas `rótulo<TAB>valor`, o JSON sai compacto em uma linha. Valores têm TAB e quebra de linha trocados por espaço, para não desalinhar o TSV.
- **`--output json`** emite **um único documento JSON** na saída padrão por execução:
  - `get`: o objeto do recurso; com `--operation-id`, a chave `operation`.
  - `list`: um array (`[]` quando vazio, sem nota).
  - pedidos assíncronos: o aceite (`resourceId`, `operationId`) sem `--wait`; com `--wait`, só o recurso convergido (o painel intermediário "… requested" não sai) ou `{"resourceId", "state": "removed"}` na remoção convergida.
  - "Nothing to do" (`update`, `protect`, `unprotect`, `disable`): o recurso atual, no formato do `get`; a nota vai para a saída de erro.
- As chaves são camelCase, os nomes da API; tuplas viram listas; booleanos e números mantêm o tipo.
- **`note` (orientações) vai para a saída de erro** em `--raw` e em `--output json`, para a saída padrão ter só dados. Em `table` nada muda. Em falha, a saída padrão fica vazia, o erro vai para a saída de erro e o código de saída não muda.
- **Negação por padrão:** um comando só aceita `--output json` se for declarado com `structured=True` (`SkTyper`, `sk/command_app.py`). Os demais recusam com código 2 e "This command has no structured output yet." **antes de qualquer chamada à API**, porque criar/apagar acontecem antes da impressão. Hoje estão fora: `auth login`, `auth refresh` e `config get|set`. `config get` já é dado cru para scripts.
- **Sem segredos:** o JSON vem dos modelos de `features/` (auditados: nenhum campo de token ou senha) ou de dicionários explícitos. `auth whoami` emite só `user`, `issuer` e `expiresAt`, nunca token nem claims do provedor.
- **Limpeza de escapes em todos os modos (inclusive `table`):** sequências de escape e controles C0/C1 vindos da API ou de arquivo são removidos antes de chegar ao terminal em painéis, tabelas, notas, erros e avisos. No JSON, os controles ficam como `\uXXXX` e o dado não é alterado.

## Justificativa

- **Segurança:** a negação por padrão impede o efeito colateral sem saída estruturada; a limpeza fecha a injeção de sequências de terminal por nomes e descrições; nenhum segredo entra no JSON.
- **Simplicidade:** duas opções, um formato estruturado (JSON, lido por qualquer ferramenta), nenhuma dependência nova.
- **Referência de mercado (§2.7):** `kubectl -o`, `gh --json`; divergência: o formato vem antes do subcomando, por ser opção do grupo raiz no Typer.
- **Caminho aditivo (§2.6):** um formato novo (por exemplo YAML) entra em `OutputFormat` sem mudar os comandos; um comando novo ganha `structured=True`.

## Consequências

- Todo comando novo declara `structured=True` e passa `data=` para `ui.panel`/`ui.table`, ou fica recusado em JSON.
- A exceção do `sk config get` da 0021 permanece: continua imprimindo só o valor.
- Uma mudança de campo do modelo muda o JSON: o JSON é contrato (§10) e segue a compatibilidade da CLI.
- O modo é gravado a cada invocação pelo callback raiz; testes restauram o padrão com `output.configure(raw=False)`.
