---
name: CLI UX
description: Guia de procedimentos para projetar, revisar e auditar a experiência de uso (UX/DX) da CLI sk (clients/cli/) contra as decisões do projeto e o Command Line Interface Guidelines (clig.dev). Use sempre que criar ou alterar um subcomando, opção, mensagem de erro, texto de --help ou saída (--output json / --raw) da CLI, e ao pedirem avaliação de qualidade, usabilidade, conformidade com o clig.dev ou "UX da CLI" do sk.
---

# CLI UX (`sk`)

## Objetivo

Projetar, revisar e auditar a UX/DX da CLI `sk` (`clients/cli/`) de forma verificável: cada nota vem de um comando executado ou de uma linha de código citada, e cada divergência do clig.dev é classificada como **registrada** (há decisão) ou **sem decisão** (precisa do responsável).

Esta skill é um **guia de procedimento**. Ela não redefine as fontes da verdade:

- Regras universais → `AGENTS.md` (§2.7 referência de mercado, §16.1 idiomas, §23 `.workspace/`, §25.1 reavaliação de decisões)
- Engenharia Python e CLI → `.opencode/agents/python.md` (§20.1)
- Validação técnica → `.opencode/skills/python-quality/SKILL.md`
- Decisões da CLI → `.decisions/` `0007`, `0008`, `0021`, `0022`, `0035`, `0036`, `0041`, `0043`, `0093`, `0094`
- Documentação → `clients/cli/README.md` e `docs/cli/CLI-DEV-STG.md`
- Referência de mercado → [clig.dev](https://clig.dev/), com a matriz de conformidade em `references/clig-conformance.md`

**Precedência.** Uma decisão aceita vence o clig.dev. Mas só conta como "divergência deliberada" a que **está escrita** em `.decisions/`. Se a `sk` diverge e nenhuma decisão diz por quê, não presuma intenção: registre como "sem decisão" e leve ao responsável (`AGENTS.md` §25.1). Nunca altere um contrato em silêncio.

---

# Workflow

## 1. Isolar o ambiente

Nunca use a sessão real (`~/.config/sk`). Os testes que falam com a API também não devem rodar sem o usuário saber.

```bash
cd clients/cli
mkdir -p ../../.workspace/cli-audit
export XDG_CONFIG_HOME=$PWD/../../.workspace/cli-audit
unset SK_AUTH_ISSUER SK_API_URL SK_AUTH_CLIENT_ID SK_BSM_PROJECT_ID SK_OPERATOR_PROJECT_ID
SK=$PWD/.venv/bin/sk
# ... auditoria ...
rm -rf ../../.workspace/cli-audit
```

Regras para os testes manuais, porque cada uma já enganou uma auditoria:

- Redirecione `stdin` com `</dev/null`, para o comando não esperar entrada.
- Para comportamento de **terminal** (cor, largura), use um pseudo-terminal: `script -q /dev/null $SK ...`. Em pipe, "sem cor" não prova que `NO_COLOR` funciona, porque a CLI já desliga a cor fora de TTY.
- `getattr(command, "structured")` na árvore do Typer sempre dá falso: o valor fica na closure de `SkTyper.command`. Para saber se um comando é estruturado, execute `sk --output json <cmd>` e veja se sai com código 2 e "no structured output yet", ou use `git grep "structured=True"`.
- Ctrl-C: um processo em segundo plano no shell ignora SIGINT. Só conclua algo sobre interrupção testando num terminal interativo; senão registre "não verificado".
- macOS: não há `timeout`; use `git grep` (não `grep -r`).

## 2. Auditar os 9 critérios (nota 1 a 5)

Para cada critério, cite a evidência (comando + código de saída, ou arquivo:linha). Um item que você não executou ou leu fica **"não verificado"**, nunca "conforme".

### C1. Gramática, descoberta e `--help` (decisões 0022 e 0035; clig.dev *Help*, *Subcommands*)
- Hierarquia `sk <módulo> <tipo> <ação>` (ou `sk <grupo> <ação>` para `auth`, `config`, `account`); opções em `kebab-case`; mesmos verbos em todos os tipos.
- Todo `list` mostra `name | resourceId | phase` (+ `description` quando houver).
- Todo comando e opção passa por `sk/help.py` (`command()`/`option()`): `Resolution order: …` (exceto `config`) e `<descrição> [Tipo] [fontes] [required|optional]`.
- **Sem `[default: …]` duplicado**: o Typer acrescenta uma linha própria quando a opção tem `default` e não tem `show_default=False`. Verifique com `$SK --help` e `$SK sum service enable --help`, também com `COLUMNS=100`. O `test_help.py` não olha as opções da raiz (`--output`, `--raw`).
- `pytest tests/unit/test_help.py` passa.
- Descoberta (clig.dev): `-h`, `--version`, `sk help <cmd>`, exemplos na ajuda, link de suporte/doc, sugestão de nome (`Did you mean`). Veja o estado de cada um em `references/clig-conformance.md` e **reconfirme**.

### C2. Erros acionáveis (decisões 0021 e 0035; clig.dev *Errors*)
- Todo erro usa `ui.error(título, detalhe, hint=…)` em `stderr`, em inglês, com a causa e o próximo passo.
- O `hint` cita **só comandos que existem**. Liste os comandos citados com ``git grep -n -o -E '`sk [a-z -]+' src`` e execute cada um com `--help`. Um comando extinto (ex.: `sk init`, decisão 0036) é defeito.
- Sem traceback, sem URL interna do pydantic, sem valor sensível. Provoque: `config.toml` inválido, chave desconhecida, valor vazio, sem sessão.
- Erro inesperado: existe orientação de como reportar? (clig.dev pede.)

### C3. Contrato humano vs. máquina (decisão 0093; clig.dev *Output*)
- `--output`/`--raw` valem **antes** do subcomando; depois dele, código 2.
- `table`: painéis e tabelas em `stdout`; erros, avisos, `note` e URL de login em `stderr`.
- `--raw`: TSV com cabeçalho; painel como `rótulo<TAB>valor`; sem caixa nem cor.
- `--output json`: um único documento válido em `stdout` (`| python3 -m json.tool`), `[]` em lista vazia. Comando sem `structured=True` recusa com código 2 **antes** de qualquer efeito (teste com um comando que cria: `sk --output json ipm role create` deve falhar sem chamar a API).
- Em pipe sem `--raw` a `sk` mantém as bordas: classifique como "sem decisão" até haver registro (veja a matriz).

### C4. Códigos de saída (clig.dev *Basics*)
- `0` sucesso, inclusive idempotente ("Nothing to do"); `1` falha de execução (sessão, API, `--wait` com Operation `failed`/`rejected`, timeout); `2` uso ou configuração inválida.
- Teste pelo menos: opção obrigatória ausente (2), chave de config desconhecida (2), sem sessão (1), `--output json` em comando não estruturado (2), opção global depois do subcomando (2).

### C5. Semântica assíncrona (`202` e `--wait`)
- Sem `--wait`: deixa claro que foi só aceito; mostra `resourceId`, `operationId` e como consultar.
- Com `--wait`: espera a convergência, renova a sessão onde muda o token (`sum service enable|disable`) e, no tempo esgotado, diz que o pedido segue em andamento e dá o `get`.
- Feedback durante a espera: o `--wait` hoje dorme em laço sem escrever nada. O clig.dev pede resposta em < 100 ms e progresso em operação longa. Verifique se ainda é assim (`git grep -n "WAIT_POLL_SECONDS" src`).
- Só leitura de código nesta etapa, a menos que o usuário autorize rodar contra a API.

### C6. Segurança e higiene de terminal (`AGENTS.md` §4; decisão 0093; clig.dev *Arguments*)
- Todo texto vindo da API ou de arquivo passa por `output.sanitize()` (ANSI/OSC e controles C0/C1) antes do terminal.
- Nenhum segredo em flag nem em variável de ambiente (`git grep -n -i -E '"--(password|token|secret)"|SK_[A-Z_]*(TOKEN|SECRET|PASSWORD)'` não pode achar nada); chaves só por arquivo, gravado com `0600`.
- Exclusão irreversível tem guarda: `unprotect` antes do `delete` no loop (decisão 0043) e `--yes` em `sk account delete` (sem ele: código 2).

### C7. Acessibilidade e terminal (decisão 0021; clig.dev *Output*)
O estado nunca depende só de cor (símbolo `✓ ✗ → !` + coluna `phase`), e identificadores não podem ser cortados (`no_wrap` em `ui.table`).

Teste cor **em pseudo-terminal** e separe cor de atributo (negrito não é cor e o `NO_COLOR` não o proíbe):

```bash
color() { LC_ALL=C grep -cE $'\033\\[([0-9;]*;)?(3[0-7]|9[0-7]|38|48)[;m]'; }
script -q /dev/null $SK config list 2>&1 | color                 # > 0
NO_COLOR=1 script -q /dev/null $SK config list 2>&1 | color      # = 0
TERM=dumb  script -q /dev/null $SK config list 2>&1 | color      # = 0
$SK config list | color                                          # = 0 (pipe)
FORCE_COLOR=1 $SK config list | color                            # > 0
NO_COLOR=1 script -q /dev/null sh -c "$SK ipm role get 2>&1 >/dev/null" | color   # erro (stderr) = 0
```

### C8. Coerência código ↔ documentação e configuração
- `sk config list` mostra **todas** as seções de `sk/settings.py` (`SkSettings`). Compare com `SECTION_MODELS` em `commands/config.py`.
- Cada módulo de `src/sk/commands/` tem seção em `clients/cli/README.md`: compare `ls src/sk/commands` e `grep '^## ' README.md`.
- Procure frases que contradizem decisões: `git grep -n -i "português" README.md` (a 0035 fixou inglês) e menções a comportamento removido (por exemplo, o `*` da Organization ativa, retirado em `14ccbd9`).
- `docs/cli/CLI-DEV-STG.md` reflete os comandos e variáveis reais.

### C9. Robustez e interrupção (clig.dev *Robustness*, *Signals*)
- Validação antes do efeito (código 2 antes de chamar a API).
- Timeout HTTP existe e é razoável; saber se é configurável.
- Idempotência: `Idempotency-Key` por pedido; repetir `disable` é "Nothing to do".
- Ctrl-C sai rápido e sem traceback (teste só em terminal interativo; senão "não verificado").

---

## 3. Classificar as divergências do clig.dev

Para cada divergência encontrada, use `references/clig-conformance.md` como ponto de partida e **reconfira** com execução. Classifique em:

- **Registrada**: cite a decisão (ex.: opções globais antes do subcomando → 0093).
- **Sem decisão**: descreva o atrito, o que o clig.dev recomenda e o trade-off. Peça ao responsável que decida (`AGENTS.md` §25.1); não corrija sozinho.
- **Lacuna**: o clig.dev recomenda e a `sk` não faz; avalie o custo (`AGENTS.md` §6: não adicione `--quiet`, `--dry-run` etc. sem requisito).

Prioridade dos achados: defeito (a CLI se contradiz ou mente) > lacuna de *Basics* > divergência sem decisão > lacuna desejável.

## 4. Validação técnica

Se a tarefa alterou `clients/cli/`, rode a skill `python-quality` (ruff, pyright, pytest com cobertura, Sonar). Alterar o comportamento de `--help` ou de erros pede teste em `tests/unit/`.

---

# Resultado

```text
CLI UX Audit (sk) — <data>

C1 Gramática, descoberta e --help:        <1-5>/5 — PASS/WARN/FAIL
C2 Erros acionáveis:                      <1-5>/5
C3 Contrato humano vs. máquina:           <1-5>/5
C4 Códigos de saída:                      <1-5>/5
C5 Semântica assíncrona (202 / --wait):   <1-5>/5
C6 Segurança e higiene de terminal:       <1-5>/5
C7 Acessibilidade e terminal:             <1-5>/5
C8 Coerência código ↔ documentação:       <1-5>/5
C9 Robustez e interrupção:                <1-5>/5

Não verificado: <o que não foi executado e por quê>

Defeitos (arquivo:linha ou comando):
- ...

Conformidade com o clig.dev:
- Registradas: ...
- Sem decisão (para o responsável): ...
- Lacunas: ...
```

Apague `.workspace/cli-audit` ao fim.
