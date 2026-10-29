---
name: Feature Bootstrap
description: Guia de procedimentos para criar uma feature nova (módulo × tipo) na ordem do roteiro, com a verificação de cada passo. Use ao criar `features/<módulo>/<tipo>`, ao conferir se o roteiro foi seguido ou ao retomar uma feature parcial.
---

# Feature Bootstrap

## 1. Papel desta skill

Esta skill é um **guia de procedimentos** que chama ferramentas (`templates/feature/sync.py`, `uv`, Ruff, Pyright, pytest). Ela define **a ordem e a verificação de cada passo**; não define regras.

```text
Fonte da verdade do tema → docs/platform/FEATURE-BOOTSTRAP.md (roteiro, nomes derivados, o que é manual)
Template, semente, perfis → .decisions/0064, 0065 e 0075, templates/feature/sync.py
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
grep -m1 "Status" .decisions/0075-motores-identicos-gerados-do-template.md   # deve ser "Aceita"
```

A escolha entre gerar os módulos comuns e extrair uma biblioteca comum está fechada pela 0075 (o que é idêntico vem do template, por perfil). Se o recurso pedir um comportamento fora dos perfis, pare e pergunte (`feature.md`, seção 2).

---

## 4. Procedimento

Cada passo termina verificado antes do seguinte. O conteúdo de cada passo está no roteiro; aqui está só o que rodar para provar que terminou.

| Passo do roteiro | Feito quando | Verificação |
|---|---|---|
| 2. Contrato | schemas e índice existem, com exemplos | `cd schemas && uv run pytest -q` |
| 3. Projeto | pasta criada, semente ajustada, perfis declarados em `PROFILES` (`api-http` e, se usa projeções, `organization-projection`/`member-projection`), modelos gerados | `python templates/feature/sync.py --new <módulo> <tipo>`; acrescente `"<módulo>/<tipo>"` aos perfis e rode `python templates/feature/sync.py --write`; `cd features/<módulo>/<tipo> && uv lock && uv run datamodel-codegen`; `python templates/feature/sync.py --check` |
| 4. Papéis | `api`, `publisher` e (se há provedor externo) `controller`, cada um com `main.py`, `settings.py` e `domain/` puro; contrato de cada perfil escrito (roteiro, passo 3) | `uv run pyright` sem `Import ... could not be resolved`; depois `uv run ruff check . && uv run ruff format --check . && uv run pyright` |
| 4. Invariantes do loop | a API admite recurso e `desired` numa só transação, sem Operation; o Controller só confirma `observedGeneration` depois de reobservar | testes de `tests/api` e `tests/controller` no molde do modelo; prova final no e2e (passo 11) |
| 4. Guia de parâmetros | `docs/CONFIGURATION.md` gerado dos `settings.py` | `uv run python ../../../templates/feature/configuration_guide.py` e depois `... --check` (rc 0) |
| 4. Testes | testes unitários de cada papel e `test_role_entrypoints.py` | `uv run pytest tests/*/unit tests/*/contract -q` |
| 5. Banco | migração `0001-<tipo>.sql` com o estado atual de todas as migrações do modelo; papéis do módulo | `grep -n observed_generation migrations/0001-<tipo>.sql`; skill `postgresql` |
| 6. Mensageria | nenhum Stream criado; os consumers do Controller e das projeções são criados por ele na partida | skill `nats` |
| 7 a 9. Registros | cada arquivo compartilhado tocado | skill `feature-registers` |
| 10. Documentação | README, DATA-FLOW, diagramas, `IMPLEMENTATION-STATUS` | revisão contra o roteiro |
| 11. Verificação final | tudo acima passou | seção 5 |

Regras que valem em todos os passos (fontes no `feature.md` e no `AGENTS.md`):

* o que o `sync.py` grava não é copiado nem editado à mão: altere o modelo e sincronize (§22);
* a semente (`pyproject.toml`, `k8s/{base,overlays/dev}`, `compose.yaml`, `config.toml`, `.env.example`) é da feature depois de criada;
* a feature nova declara em `PROFILES` os perfis que usa logo depois do `--new` e escreve o contrato de cada um (roteiro, passo 3); uma feature existente só entra num perfil quando o código dela já é igual ao do modelo;
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

Use o formato do `feature.md`, seção 8, e não reporte "pronta" com passo pulado ou item de verificação que falhou ou não rodou (§32). O que a infraestrutura de dev ainda não tem é uma lacuna declarada em `docs/platform/IMPLEMENTATION-STATUS.md` (§2.5).

Se o roteiro estiver errado ou desatualizado, corrija `docs/platform/FEATURE-BOOTSTRAP.md` em vez de contornar.
