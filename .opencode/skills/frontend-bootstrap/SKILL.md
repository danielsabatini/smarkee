---
name: Frontend Bootstrap
description: Guia de procedimentos para inicializar e evoluir o Smarkee Console (clients/console/) na ordem incremental de etapas do docs/console/CONSOLE.md, com verificação em cada passo. Use ao criar clients/console/, ao implementar uma etapa do roteiro ou ao retomar uma implementação parcial.
---

# Frontend Bootstrap

## 1. Papel desta skill

Esta skill é um **guia de procedimentos** que executa a construção incremental do Smarkee Console em `clients/console/` seguindo o roteiro de `docs/console/CONSOLE.md` (§13). Ela define **a ordem de execução, as ferramentas acionadas em cada etapa e o critério de verificação de cada passo**; não redefine regras arquiteturais.

```text
Especificação funcional e roteiro → docs/console/CONSOLE.md
Referência visual e marca         → images/console-main-layout.png e images/
Contratos oficiais JSON Schema    → schemas/common/ e schemas/<módulo>/<tipo>/
Conhecimento do especialista      → .opencode/agents/frontend.md
Procedimento de componentes       → skill frontend-component
Procedimento de qualidade/testes  → skill frontend-quality
```

Não repita aqui as regras dessas fontes. Em conflito, prevalece o `AGENTS.md`, depois `docs/console/CONSOLE.md`.

---

## 2. Pré-condições

Antes de iniciar qualquer etapa, execute e verifique:

1. **Inspeção da árvore de trabalho (`AGENTS.md` §8):**
   ```bash
   git status --short
   ```
   Arquivos modificados que não façam parte da tarefa atual pertencem ao usuário e não devem ser sobrescritos ou revertidos.
2. **Inspeção dos ativos visuais oficiais (`docs/console/CONSOLE.md` §4.1):**
   Confirme os arquivos presentes em `images/` e leia visualmente `images/console-main-layout.png` com a tool `read`.
3. **Inspeção dos JSON Schemas oficiais (`docs/console/CONSOLE.md` §7.1):**
   Confirme os schemas em `schemas/common/`, `schemas/core/account/`, `schemas/ipm/organization/`, `schemas/ipm/user/` e `schemas/sum/service/`.

---

## 3. Procedimento Incremental por Etapa (`AGENTS.md` §2.2)

Cada etapa deve terminar verificada antes de iniciar a seguinte.

| Etapa | Escopo (`docs/console/CONSOLE.md` §13) | Ferramentas / Skills Acionadas | Verificação de Saída da Etapa |
|---|---|---|---|
| **Etapa 1 — Fundação e Contratos** | Inicializar projeto em `clients/console/` (`pnpm`, SvelteKit + Svelte 5, TS estrito, Tailwind CSS, Lucide, Vitest, `ajv`, Playwright, `@axe-core/playwright`, ESLint, Prettier); copiar logotipos oficiais de `images/` para `static/brand/`; criar tipos em `src/lib/types/` espelhando `schemas/`; implementar `MockDataAdapter`, `ResourceWatcher` e `console-context.svelte.ts` | `pnpm`, MCP `context7` (se necessário para config de Tailwind v4 / SvelteKit), skill `frontend-component` para `.svelte.ts` | `pnpm check` (0 erros) e `pnpm test:unit` validando com `ajv` que os recursos do `MockDataAdapter` passam nos JSON Schemas reais de `../../schemas/` |
| **Etapa 2 — Shell e Navegação** | Tokens visuais da Smarkee em `src/app.css`; `AppHeader.svelte`, `OrganizationSelector.svelte`, `GlobalSearch.svelte`, `Sidebar.svelte`, `OperationsPanel.svelte` e `+layout.svelte` | Skill `frontend-component` (com MCP `svelte-autofixer` em cada componente criado) | MCP `svelte-autofixer` (0 issues em todos os componentes), `pnpm check` e testes unitários de troca de organização e filtros |
| **Etapa 3 — Dashboard e Visões Operacionais** | Componentes do Dashboard (`OrganizationSummary`, `QuickAccessGrid`, `ServiceCards`, `RecentResources`, `ServiceStatusTable`); `+page.svelte`; rotas e placeholders dos módulos (`IPM`, `SUM`, `AEM`, `ODM`, `Configurações`); simulação interativa de reconciliação (`Pending` → `Reconciling` → `Ready`) | Skill `frontend-component` (com MCP `svelte-autofixer` em cada componente e página) | MCP `svelte-autofixer` (0 issues), `pnpm check` e `pnpm build` |
| **Etapa 4 — Verificação Completa e Documentação** | Testes E2E e acessibilidade (`Playwright` + `@axe-core/playwright`), inspeção visual no navegador via MCP `playwright`, `README.md` de `clients/console/` e Quality Gate | Skill `frontend-quality` (que orquestra Vitest, Playwright, MCP `playwright` e MCP `sonarqube`) | Todos os itens da skill `frontend-quality` aprovados (`PASS`) |

---

## 4. Regras de Execução durante o Bootstrap

1. **Proibição de código legado Svelte 3/4:** todo componente nasce em Svelte 5 Runes e passa imediatamente pela skill `frontend-component` (`tools.svelte["svelte-autofixer"]`).
2. **Prova matemática de contrato desde a Etapa 1:** o teste de contrato em Vitest (`tests/unit/schema-contracts.test.ts`) deve carregar os arquivos `.v1.schema.json` de `../../schemas/` e validar os objetos retornados pelo `MockDataAdapter`. Isso impede qualquer deriva entre o Console e os Receivers reais.
3. **Arquivos temporários:** qualquer script auxiliar ou rascunho deve ficar exclusivamente em `.workspace/` (`AGENTS.md` §23).
4. **Sem operações destrutivas:** não altere código de `features/`, `schemas/` ou `infrastructure/` durante o bootstrap do Console, salvo se solicitado explicitamente pelo responsável (`AGENTS.md` §7).

---

## 5. Resultado

Ao concluir uma etapa ou o bootstrap completo, apresente o relatório estruturado:

```text
Frontend Bootstrap

Etapa concluída: <1 / 2 / 3 / 4 — Completa>
Arquivos em clients/console/: <resumo por diretório>
Verificação da etapa:
  - MCP svelte-autofixer: PASS/FAIL
  - pnpm check: PASS/FAIL
  - pnpm lint: PASS/FAIL
  - pnpm test:unit (incluindo contratos ajv): PASS/FAIL
  - pnpm build: PASS/FAIL
  - pnpm test:e2e (Playwright + axe-core): PASS/FAIL/NOT VERIFIED
  - Inspeção visual (MCP playwright): PASS/FAIL/NOT VERIFIED
```
