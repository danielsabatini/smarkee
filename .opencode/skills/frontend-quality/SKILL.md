---
name: Frontend Quality
description: Executar a validação completa de qualidade de um componente Frontend (Svelte 5 / SvelteKit / TypeScript), incluindo MCP svelte-autofixer, svelte-check, ESLint, Prettier, Vitest (com validação de contratos JSON Schema), Playwright E2E (com auditoria a11y axe-core), inspeção visual e Quality Gate do SonarQube.
---

# Frontend Quality

## Objetivo

Executar o workflow completo de validação de qualidade de um componente Frontend (`clients/console/`).

Esta skill é um **guia de procedimento** que orquestra a execução das ferramentas de validação. Ela define **a ordem de execução e o registro do resultado**; as regras das ferramentas e da linguagem pertencem aos respectivos agents e documentos:

- Engenharia Frontend → `.opencode/agents/frontend.md`
- Especificação do Console → `docs/console/CONSOLE.md`
- Contratos oficiais → `docs/data/SCHEMA.md` e `schemas/`
- SonarQube e Quality Gate → `.opencode/agents/sonarqube.md`
- Regras universais → `AGENTS.md`

Não redefina aqui as regras dessas fontes.

---

# Workflow

## 1. Identificar o componente e sincronizar o ambiente

Execute a validação a partir do diretório do projeto frontend (`clients/console/`).

Garanta que as dependências estejam instaladas conforme o lockfile:

```text
pnpm install --frozen-lockfile
```

(Durante o bootstrap inicial antes da criação do lockfile, utilize `pnpm install`).

---

## 2. Validar componentes com o MCP `svelte-autofixer`

Para todo arquivo `.svelte` e `.svelte.ts` criado ou modificado no escopo:

1. Chame `tools.svelte["svelte-autofixer"]` via `execute` com `desired_svelte_version: 5` e o nome do arquivo (`filename`).
2. Se `issues` ou `suggestions` não estiverem vazios (ou `require_another_tool_call_after_fixing: true`), aplique as correções e execute `svelte-autofixer` novamente até zerar.

Não avance para os próximos passos enquanto o `svelte-autofixer` reportar problemas.

---

## 3. Executar `svelte-check` e Type Checking (`pnpm check`)

Sincronize os tipos gerados pelo SvelteKit e execute a verificação estática:

```text
pnpm check
```

Confirme:
- `0 errors`
- `0 warnings` (incluindo avisos de acessibilidade estática do compilador Svelte).

---

## 4. Executar Lint e Formatação (`pnpm lint`)

Execute a validação do ESLint e do Prettier:

```text
pnpm lint
```

Se houver falha de formatação ou regra do ESLint, corrija antes de prosseguir.

---

## 5. Executar Testes Unitários, Cobertura e Contratos (`pnpm test:unit`)

Execute os testes unitários e de componentes com Vitest e cobertura:

```text
pnpm test:unit
```

Confirme que a suíte valida:
1. **Unidade e Componentes:** estado reativo, filtros, seletores, adaptadores e validadores de identificador (`OPAQUE_IDENTIFIER_PATTERN`).
2. **Contratos (`schemas/`):** os payloads gerados pelo `MockDataAdapter` (`AccountResource`, `OrganizationResource`, `OrganizationUserResource`, `ServiceLinkResource`, `Operation`) são validados contra os arquivos JSON Schema reais em `../../schemas/` usando `ajv`.
3. **Cobertura:** reporte o percentual obtido e compare com a meta (>80% em código novo).

---

## 6. Executar Build de Produção (`pnpm build`)

Garanta que o bundle de produção do SvelteKit compila sem erros de SSR ou imports inválidos:

```text
pnpm build
```

---

## 7. Executar Testes E2E e Acessibilidade (`pnpm test:e2e`)

Execute a suíte Playwright:

```text
pnpm test:e2e
```

Confirme:
- Jornadas do `docs/console/CONSOLE.md` §12 aprovadas (layout, menu lateral, seletor de organização sem vazamento de dados, painel de operações e responsividade).
- Auditoria de acessibilidade automatizada (`@axe-core/playwright`) sem violações críticas/sérias de contraste, semântica ou `aria-label`.
- Ausência de erros no `console` do navegador (`page.on('pageerror')` / `console.error`).

---

## 8. Inspeção Visual e Interativa via MCP `playwright` (quando aplicável)

Quando houver alteração visual relevante no layout ou nos componentes do Dashboard:
1. Utilize o servidor MCP `playwright` para abrir o Console em execução local, inspecionar o snapshot de acessibilidade e capturar screenshot em viewport desktop (`1440x900`) e mobile (`390x844`).
2. Compare a composição, hierarquia e paleta com a referência `images/console-main-layout.png`.

---

## 9. Executar Análise do SonarQube (quando configurado)

Quando `clients/console/sonar-project.properties` estiver configurado e o SonarQube local disponível:
1. Execute o scanner conforme `.opencode/agents/sonarqube.md`.
2. Aguarde o processamento da tarefa (`ceTaskId`).
3. Consulte o Quality Gate obrigatoriamente pelo MCP `sonarqube` (`get_quality_gate_status`).

Se o SonarQube não estiver disponível ou configurado para o componente na etapa atual, registre explicitamente como `NOT VERIFIED` com o motivo (`AGENTS.md` §19 e §32).

---

# Resultado

Ao concluir, apresente o resultado de forma explícita:

```text
Frontend Quality

MCP svelte-autofixer: PASS/FAIL
Typecheck & svelte-check (pnpm check): PASS/FAIL
Lint & Formatting (pnpm lint): PASS/FAIL
Unit Tests & Coverage (pnpm test:unit): PASS/FAIL
Schema Contracts (ajv vs schemas/): PASS/FAIL
Production Build (pnpm build): PASS/FAIL
E2E & a11y axe-core (pnpm test:e2e): PASS/FAIL
Visual Inspection (MCP playwright): PASS/FAIL/NOT VERIFIED
SonarQube Quality Gate: PASS/FAIL/NOT VERIFIED

Overall: PASS/FAIL
```

Nunca transforme uma etapa não executada em `PASS`. Use `NOT VERIFIED` e informe a razão.
