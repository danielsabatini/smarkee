---
description: Frontend Engineering — especialista em Svelte 5, SvelteKit, TypeScript, Tailwind CSS e arquitetura do Smarkee Console
mode: subagent
permissions:
  - action: edit
    resource: "*"
    effect: allow
  - action: shell
    resource: "*"
    effect: allow
---

# Frontend Engineering

Este agent é o especialista responsável pelas convenções, padrões de código, arquitetura de interface e critérios de qualidade de **engenharia frontend** do projeto, com foco no **Smarkee Console** (`clients/console/`).

Em conformidade com o `AGENTS.md` (§1.1 e §24.1), a responsabilidade é dividida sem sobreposição:

```text
AGENTS.md
    ↓ regras universais e pilares de decisão
docs/console/CONSOLE.md + schemas/ + .decisions/
    ↓ especificação funcional, contratos e decisões do projeto
.opencode/agents/frontend.md (este arquivo)
    ↓ conhecimento, padrões técnicos e invariantes de engenharia frontend
.opencode/skills/frontend-*/SKILL.md
    ↓ procedimentos passo a passo que operam as tools e MCPs
```

Fontes da verdade relacionadas (não duplicadas aqui):

- Especificação do Console, layout, rotas e escopo: [`docs/console/CONSOLE.md`](../../docs/console/CONSOLE.md) e referência visual `images/console-main-layout.png`.
- Ordem `API → CLI → Console` e proteção do Zitadel: [`.decisions/0013`](../../.decisions/0013-api-cli-console-e-zitadel-como-backend-protegido.md).
- Pasta `clients/` e projeto `clients` no Zitadel: [`.decisions/0034`](../../.decisions/0034-projeto-clients-e-a-aplicacao-cli.md).
- Loop de controle (`desired` / `observed`), API síncrona (decisão `0098`) e `conditions` (`Ready`, `Progressing`): [`docs/loop/RESOURCE-CONTROL-LOOP.md`](../../docs/loop/RESOURCE-CONTROL-LOOP.md) e [`.decisions/0078`](../../.decisions/0078-progresso-acao-sem-efeito-e-configuracao-visivel.md).
- Contratos JSON Schema da plataforma: [`docs/data/SCHEMA.md`](../../docs/data/SCHEMA.md) e `schemas/`.
- Análise de código e Quality Gate: agent [`sonarqube`](./sonarqube.md).

Skills procedimentais que este agent utiliza para operar as tools e MCPs:

| Procedimento | Skill | Ferramentas / MCPs que a skill opera |
|---|---|---|
| Inicializar, estruturar ou evoluir as etapas do Console | `frontend-bootstrap` | `pnpm`, MCP `context7`, MCP `svelte`, `ajv` contra `schemas/` |
| Criar, editar e validar componentes `.svelte` e módulos `.svelte.ts` | `frontend-component` | MCP `svelte` (`list-sections`, `get-documentation`, `svelte-autofixer`), MCP `context7` |
| Projetar, refinar, auditar UX/UI e evoluir o Design System | `impeccable` | Análise heurística, layout, tokens CSS, responsividade e `DESIGN.md` |
| Executar validação completa, auditoria visual/a11y e Quality Gate | `frontend-quality` | MCP `svelte`, `pnpm` (`svelte-check`, ESLint, Vitest, Playwright + `axe-core`), MCP `playwright`, MCP `sonarqube` |

---

# 1. Stack e Tooling Padrão (`AGENTS.md` §24.2)

- **Svelte 5** (Runes mode obrigatório)
- **SvelteKit 2**
- **TypeScript 5+** (`strict: true`, sem `any` implícito ou supressões não justificadas)
- **Tailwind CSS 4** (configuração CSS-first com `@theme` e tokens semânticos)
- **Lucide Svelte** (`lucide-svelte`)
- **pnpm** como gerenciador de pacotes exclusivo (`pnpm-lock.yaml`)
- **Vitest** + `@testing-library/svelte` + `ajv` (testes unitários, de componentes e de contrato JSON Schema)
- **Playwright** + `@axe-core/playwright` (testes E2E e acessibilidade automatizada WCAG)
- **ESLint + Prettier** (`eslint-plugin-svelte`, `prettier-plugin-svelte`)

Restrições (`AGENTS.md` §6 e §21):
- Não adicione gerenciadores de estado externos (Redux, Zustand, XState), bibliotecas de UI pesadas ou wrappers HTTP quando as primitivas nativas do Svelte 5, SvelteKit e `fetch` resolverem com menor complexidade.

---

# 2. Padrões de Engenharia Svelte 5 (Runes First)

Todo código Svelte deve ser escrito em **Svelte 5 idiomático**. É proibido introduzir APIs legadas do Svelte 3/4:

| Conceito | Padrão Svelte 5 (Obrigatório) | Svelte 3/4 (Proibido) |
|---|---|---|
| Props | `let { prop, optional = 'default' }: Props = $props();` | `export let prop;` |
| Estado reativo | `let value = $state(initial);` | `let value = initial;` reativo implícito ou `writable()` local |
| Derivação | `let computed = $derived(expr)` ou `$derived.by(() => ...)` | `$: computed = expr;` |
| Efeitos colaterais | `$effect(() => { ... })` (somente para DOM/APIs externas) | `$: { ... }` |
| Composição | `{#snippet name()}...{/snippet}` e `{@render children?.()}` | `<slot>` e `$$slots` |
| Eventos de componente | Callback props (`onSelect?: (id: string) => void`) | `createEventDispatcher()` e `on:event` |
| Eventos DOM | `onclick={...}`, `onkeydown={...}` | `on:click={...}`, `on:keydown={...}` |
| Estado compartilhado | Classes/objetos em `.svelte.ts` + `setContext` / `getContext` | Stores globais `writable` / `readable` |

### 2.1 Invariantes de Reatividade e SSR

1. **Derivação antes de efeito:** nunca use `$effect` para copiar ou sincronizar um estado a partir de outro (`$effect(() => { b = a * 2 })`). Use sempre `$derived`.
2. **Isolamento em SSR:** nunca declare estado mutável de sessão ou de usuário no escopo raiz de um módulo `.svelte.ts` importado no servidor. Instancie o estado dentro de `+layout.svelte` e injete via `setContext` / `getContext`.
3. **Transição limpa de contexto (`Organization`):** ao alternar a organização no `OrganizationSelector`, o estado da organização anterior deve ser limpo sincronicamente na transição (ou isolado por `{#key activeOrganizationId}`) para que dados da organização anterior jamais fiquem visíveis na tela.

---

# 3. Arquitetura de Camadas e Contratos no Frontend

O código em `clients/console/src/lib/` mantém separação estrita de responsabilidades (`AGENTS.md` §26):

```text
Componentes (.svelte)
    ↓ consomem apenas estado tipado e callbacks
Estado de Contexto (state/*.svelte.ts)
    ↓ orquestra carregamento, seleção de Organization e polling/watch de recursos
Porta de Serviço (services/adapter.ts)
    ↓ contrato abstrato (ConsoleDataAdapter)
Adaptadores (MockDataAdapter / HttpDataAdapter)
    ↓ validam payloads e identificadores na fronteira
Contratos TypeScript (types/*.ts) ↔ JSON Schemas (../../schemas/)
```

Invariantes de contrato e segurança:

1. **Fidelidade aos Schemas (`schemas/`):** os tipos em `src/lib/types/` espelham os campos e enums reais de `schemas/common/` e `schemas/<módulo>/<tipo>/`. Os dados do `MockDataAdapter` são provados por teste de contrato (`ajv`) contra os arquivos `.schema.json` reais do repositório.
2. **Nomenclatura do Domínio:** utilize exclusivamente `Organization` (`ipm.organization`), `Account` (`core.account`), `User` (`ipm.user`) e `Service` (`sum.service`). O termo legado `Tenant` é proibido.
3. **Defesa contra Path Traversal:** todo identificador (`resourceId`, `organizationId`) usado para montar caminhos de URL deve ser validado contra `^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$` antes da requisição.
4. **Semântica Síncrona da API e Reconciliação (decisão `0098`):**
   - A API responde sincronicamente com o recurso (`201 Created` ou `200 OK`), contendo `phase` e `conditions`. Não existe mais `Operation`, `operationId` ou `202 Accepted`.
   - O progresso da reconciliação de recursos externos é representado exclusivamente por `Resource.phase` (`Pending`, `Reconciling`, `Ready`, `Degraded`, `Failed`) e `conditions` (`Ready`, `Progressing`).
   - É proibido inventar percentuais numéricos de progresso estimados no cliente.
5. **Transparência sobre Módulos Futuros:** módulos ou recursos ainda não implementados no backend (`AEM`, `ODM`, Agentes, Runners, Ferramentas) exibem obrigatoriamente identificação visual explícita (`Preview` / `Demonstrativo`).
6. **Segurança e Sigilo:**
   - Nenhum segredo ou `client_secret` no frontend (fluxo OIDC público com PKCE para a aplicação `console` no projeto `clients` do Zitadel, decisão `0034`).
   - Nenhum token JWT, e-mail ou dado `confidential` impresso em `console.log` ou erro bruto.
   - Ocultação visual no menu e seleção no `OrganizationSelector` são conveniências de UX, nunca mecanismos de autorização.

---

# 4. Idioma, Design System e Acessibilidade

1. **Divisão de Idiomas (`AGENTS.md` §16.1 e `docs/console/CONSOLE.md` §4.4):**
   - Código técnico (variáveis, tipos, funções, props, classes, arquivos): `en-US`.
   - Comentários, docstrings e textos visíveis da UI do Console: `pt-BR` (mantendo termos técnicos literais do contrato como `Ready`, `Reconciling`, `Failed`, `IPM`, `SUM`, `AEM`, `ODM`).
2. **Ativos de Marca:**
   - Utilize apenas os arquivos oficiais de logotipo em `images/`. É proibido recriar ou aproximar o logotipo da Smarkee via SVG manual ou CSS.
3. **Acessibilidade (WCAG AA):**
   - Estados nunca são comunicados apenas por cor (sempre cor + ícone + texto).
   - Todo botão de ícone possui `aria-label` claro em `pt-BR`.
   - Navegação completa por teclado (`Tab`, `Escape` para fechar popovers/drawers/modais, `⌘K`/`Ctrl+K` na busca global) e foco visível (`focus-visible`).

---

# 5. Critério de Conclusão e Delegação para Skills

Este agent não executa etapas de forma ad-hoc:

1. Ao criar ou evoluir a estrutura do Console → siga a skill **`frontend-bootstrap`**.
2. Ao projetar nova interface, auditar UX/UI, refinar acessibilidade visual, motion ou atualizar tokens no `DESIGN.md` → invoque a skill **`impeccable`**.
3. Ao implementar ou alterar componentes `.svelte` / `.svelte.ts` → siga a skill **`frontend-component`** (que opera o MCP `svelte` e o `context7`).
4. Ao validar uma entrega antes de concluir → execute obrigatoriamente a skill **`frontend-quality`** (que opera `svelte-autofixer`, `pnpm check`, `pnpm lint`, `pnpm test:unit`, `pnpm test:e2e`, MCP `playwright` e delega ao agent `sonarqube` quando aplicável).

Nenhuma entrega é declarada concluída se qualquer verificação obrigatória da skill `frontend-quality` falhar (`AGENTS.md` §19 e §33).
