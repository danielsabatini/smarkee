---
name: Feature Bootstrap
description: Guia de procedimentos para criar uma feature nova (módulo × tipo) na ordem do roteiro, com a verificação de cada passo. Use ao criar `features/<módulo>/<tipo>`, ao conferir se o roteiro foi seguido ou ao retomar uma feature parcial.
---

# Feature Bootstrap

## 1. Papel desta skill

Esta skill é um **guia de procedimentos** que chama ferramentas (`templates/feature/sync.py`, `uv`, Ruff, Pyright, pytest). Ela define **a ordem e a verificação de cada passo**; não define regras.

```text
Fonte da verdade do tema → docs/FEATURE-BOOTSTRAP.md (roteiro, nomes derivados, o que é manual)
Template e semente       → .decisions/0064 e 0065, templates/feature/sync.py
Estrutura da feature     → .decisions/0063
Atuação do agent         → .opencode/agents/feature.md
Registros compartilhados → skill feature-registers
Lint, tipos e Sonar      → skill python-quality e agent sonarqube
```

Não repita aqui o conteúdo desses documentos: aponte para eles. Em conflito, prevalece o `AGENTS.md`, depois o roteiro.

---

## 2. Entradas

`<módulo>` e `<tipo>` (uma palavra em minúsculas e dígitos, sem hífen), a forma do recurso (escolhe o modelo, roteiro passo 1), a regra de negócio (de uma decisão em `.decisions/` ou do responsável) e os schemas. O que faltar é perguntado, não presumido (`AGENTS.md` §9).

---

## 3. Pré-condições

Pare e informe se alguma falhar:

```bash
test ! -e features/<módulo>/<tipo> && test ! -e schemas/<módulo>.<tipo>.index.json && echo livre
python templates/feature/sync.py --check; echo $?        # deve ser 0
git status --short                                       # o que não for seu é do usuário
ls features/*/*/pyproject.toml | wc -l                   # 3 ou mais: ver a nota abaixo
```

Com três ou mais features, procure em `.decisions/` a decisão que fecha "gerar os motores ou extrair uma biblioteca comum" (0064). Sem ela, não prossiga sozinho: pergunte (`feature.md`, seção 2).

---

## 4. Procedimento

Cada passo termina verificado antes do seguinte. O conteúdo de cada passo está no roteiro; aqui está só o que rodar para provar que terminou.

| Passo do roteiro | Feito quando | Verificação |
|---|---|---|
| 2. Contrato | schemas e índice existem, com exemplos | `cd schemas && uv run pytest -q` |
| 3. Projeto | pasta criada, semente ajustada, modelos gerados | `python templates/feature/sync.py --new <módulo> <tipo>`; `cd features/<módulo>/<tipo> && uv lock && uv run datamodel-codegen`; `python templates/feature/sync.py --check` |
| 4. Papéis | seis papéis com `main.py`, `settings.py` e `domain/` puro | `uv run ruff check . && uv run ruff format --check . && uv run pyright` |
| 4. Guia de parâmetros | `docs/CONFIGURATION.md` gerado dos `settings.py` | `uv run python ../../../templates/feature/configuration_guide.py` e depois `... --check` (rc 0) |
| 4. Testes | testes unitários dos motores e `test_role_entrypoints.py` | `uv run pytest tests/*/unit tests/*/contract -q` |
| 5. Banco | migração `0001-<tipo>.sql`; papéis do módulo | skill `postgresql` |
| 6. Mensageria | `consumers/*.json` ajustados; nenhum Stream criado | skill `nats` |
| 7 a 9. Registros | cada arquivo compartilhado tocado | skill `feature-registers` |
| 10. Documentação | README, DATA-FLOW, diagramas, `IMPLEMENTATION-STATUS` | revisão contra o roteiro |
| 11. Verificação final | tudo acima passou | seção 5 |

Regras que valem em todos os passos (fontes no `feature.md` e no `AGENTS.md`):

* o que o `sync.py` grava não é copiado nem editado à mão: altere o modelo e sincronize (§22);
* a semente (`pyproject.toml`, `compose.yaml`, `config.toml`, `.env.example`, `consumers/`) é da feature depois de criada;
* declarar um perfil em `PROFILES` só se o código da feature já for igual ao do modelo;
* temporários ficam em `.workspace/` (§23); sem commit, push ou operação destrutiva sem pedido (§20).

---

## 5. Verificação final

```bash
python templates/feature/sync.py --check
cd features/<módulo>/<tipo>
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run python ../../../templates/feature/configuration_guide.py --check   # guia de parâmetros em dia (rc 0)
uv run pytest tests/*/unit tests/*/contract -q
cd ../../../schemas && uv run pytest -q
```

Depois, a skill `python-quality`: o Quality Gate vem do MCP do SonarQube, nunca estimado, e a cobertura do código novo fica acima de 80% sem testes artificiais. Os testes de integração e o e2e exigem a stack de dev; se ela não estiver no ar, declare o que **não** foi verificado (§19).

---

## 6. Resultado

Use o formato do `feature.md`, seção 8, e não reporte "pronta" com passo pulado ou item de verificação que falhou ou não rodou (§32). O que a infraestrutura de dev ainda não tem é uma lacuna declarada em `docs/IMPLEMENTATION-STATUS.md` (§2.5).

Se o roteiro estiver errado ou desatualizado, corrija `docs/FEATURE-BOOTSTRAP.md` em vez de contornar.
