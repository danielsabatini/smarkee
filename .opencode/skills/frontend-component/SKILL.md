---
name: Frontend Component
description: Guia de procedimentos para projetar, implementar, refatorar e validar componentes Svelte 5 (.svelte) e módulos reativos (.svelte.ts) usando os MCPs svelte e context7. Use sempre que criar ou editar arquivos .svelte ou .svelte.ts no Smarkee Console.
---

# Frontend Component

## 1. Papel desta skill

Esta skill é um **guia de procedimentos** que opera os servidores MCP `svelte` e `context7` durante a criação ou edição de componentes `.svelte` e módulos `.svelte.ts`. Ela define **como usar as tools passo a passo**; não redefine as regras de engenharia.

```text
Regras de engenharia Svelte 5 / TypeScript → .opencode/agents/frontend.md
Especificação visual e funcional           → docs/console/CONSOLE.md e images/console-main-layout.png
Validação completa do projeto              → skill frontend-quality
```

Em conflito, prevalece o `AGENTS.md`, depois `docs/console/CONSOLE.md` e `.opencode/agents/frontend.md`.

---

## 2. Procedimento A: Consultar documentação oficial antes de implementar (MCPs `svelte` e `context7`)

Sempre que o componente envolver uma API do Svelte 5, SvelteKit, Tailwind CSS v4 ou Lucide cuja sintaxe exata precise ser confirmada (`AGENTS.md` §9):

1. **Para Svelte 5 e SvelteKit (MCP `svelte` via `execute`):**
   - Passo 1: liste as seções disponíveis chamando `tools.svelte["list-sections"]()`.
   - Passo 2: identifique nos `use_cases` todas as seções relevantes (ex.: `$state`, `$derived`, `$props`, `snippets`, `load`, `page`).
   - Passo 3: busque todas de uma só vez com `tools.svelte["get-documentation"]({ section: [...] })`.
2. **Para Tailwind CSS v4, Vitest, Playwright ou Lucide (MCP `context7` via `execute`):**
   - Passo 1: resolva o ID da biblioteca com `tools.context7["resolve-library-id"]({ libraryName: "Tailwind CSS", query: "..." })`.
   - Passo 2: consulte a documentação atualizada com `tools.context7["query-docs"]({ libraryId: "...", query: "...", language: "TypeScript" })`.

Nunca adivinhe configurações do Tailwind v4 ou APIs do Svelte 5 sem consultar os MCPs quando houver incerteza.

---

## 3. Procedimento B: Implementar o componente `.svelte` ou módulo `.svelte.ts`

1. **Definir o contrato de entrada (`$props`):**
   - Declare a interface `Props` em TypeScript estrito (`en-US`).
   - Use desestruturação com `$props()`: `let { ... }: Props = $props();`.
   - Para composição visual, receba `Snippet` do `svelte` e renderize com `{@render ...}`.
   - Para eventos de componente, use callbacks tipados (`onSelect?: (id: string) => void`), nunca `createEventDispatcher`.
2. **Modelar estado e derivações:**
   - Estado local com `$state(...)`.
   - Cálculos, filtros e formatações com `$derived(...)` ou `$derived.by(() => ...)`.
   - Não use `$effect` para calcular estado derivado.
3. **Aplicar acessibilidade e estados obrigatórios (`docs/console/CONSOLE.md` §11):**
   - Inclua tratamento explícito para `loading`, `error`, `empty` e `success` quando o componente exibir dados.
   - Combine cor semântica + ícone (`lucide-svelte`) + texto para qualquer status (`Ready`, `Reconciling`, `Failed`).
   - Adicione `aria-label` em `pt-BR` em todos os botões que contenham apenas ícone.
   - Adicione suporte a teclado (`Escape` para fechar popovers/drawers, `aria-expanded`, `aria-current="page"`).
4. **Gravar o arquivo** usando `write` ou `edit`.

---

## 4. Procedimento C: Validar e corrigir com o MCP `svelte-autofixer` (Obrigatório)

Imediatamente após escrever ou editar qualquer arquivo `.svelte` ou `.svelte.ts`:

1. Execute `tools.svelte["svelte-autofixer"]` via `execute`:

   ```javascript
   return await tools.svelte["svelte-autofixer"]({
     code: "<conteúdo completo do arquivo>",
     desired_svelte_version: 5,
     filename: "NomeDoComponente.svelte" // apenas o nome base com extensão
   });
   ```

2. Analise o retorno (`issues`, `suggestions`, `require_another_tool_call_after_fixing`):
   - Se houver qualquer item em `issues` ou `suggestions`, edite o arquivo para corrigir.
   - Chame `tools.svelte["svelte-autofixer"]` novamente com o código corrigido.
   - Repita até que `issues` esteja vazio e `require_another_tool_call_after_fixing` seja `false`.

**Nota:** Nunca chame `tools.svelte["playground-link"]` para componentes escritos no repositório (`AGENTS.md` §7 e instrução do MCP).

---

## 5. Procedimento D: Verificação rápida de tipos

Após o `svelte-autofixer` aprovar os componentes alterados, execute no diretório `clients/console/`:

```bash
pnpm check
```

Confirme `0 errors` e `0 warnings` antes de considerar o componente pronto.

---

## 6. Resultado

Ao concluir a criação ou alteração de componentes, registre:

```text
Frontend Component

Arquivos processados: <lista de .svelte / .svelte.ts>
MCP svelte-autofixer: PASS (0 issues)
svelte-check (pnpm check): PASS (0 errors, 0 warnings)
```
