# Smarkee Console (`clients/console/`)

Interface web oficial (GUI) da plataforma **Smarkee**, construída em **Svelte 5 (Runes)**, **SvelteKit 2**, **TypeScript estrito** e **Tailwind CSS v4**.

A especificação funcional e arquitetural completa encontra-se em [`docs/console/CONSOLE.md`](../../docs/console/CONSOLE.md).

---

## Arquitetura e Alinhamento com a Plataforma

- **Ordem `API → CLI → Console` (`.decisions/0013` e `.decisions/0034`):** O Console é um consumidor público (OIDC Authorization Code + PKCE para a aplicação `console` no projeto `clients` do Zitadel) das mesmas APIs HTTP/JSON expostas pelos _Receivers_ no gateway APISIX. Nenhum segredo é armazenado no navegador.
- **Modelo Assíncrono (`202 Accepted`):** Toda mutação (`POST`, `PATCH`, `DELETE`) retorna `202 Accepted` com `operationId` e `resourceId`. O `OperationWatcher` acompanha a convergência entre `desired` e `observed` (`accepted` → `in_progress` → `completed` / `failed` / `rejected` / `superseded`) sem inventar percentuais numéricos de progresso estimados.
- **Contratos JSON Schema verificados (`schemas/`):** Os tipos em `src/lib/types/` e os dados do `MockDataAdapter` são validados em suíte automatizada (`ajv`) contra os arquivos `.schema.json` reais de `schemas/common/`, `schemas/core/account/`, `schemas/ipm/organization/`, `schemas/ipm/user/` e `schemas/sum/service/`.
- **Isolamento de Contexto (`Organization`):** A troca de organização no `OrganizationSelector` limpa sincronicamente o estado da organização anterior e recria a árvore principal via `{#key consoleState.activeOrganizationId}`.
- **Transparência sobre Módulos em Preview:** Módulos ainda não implementados no backend (`AEM`, `ODM`, Agentes, Runners, Ferramentas) exibem selo explícito `Preview / Demonstrativo`.

---

## Comandos Principais (`pnpm`)

```bash
# Instalar dependências
pnpm install

# Servidor de desenvolvimento
pnpm dev

# Verificação de tipos SvelteKit + TypeScript
pnpm check

# Lint (ESLint) e formatação (Prettier)
pnpm lint

# Testes unitários e de contrato JSON Schema (Vitest + Ajv)
pnpm test:unit

# Testes End-to-End e Acessibilidade WCAG AA (Playwright + axe-core)
pnpm test:e2e

# Build de produção
pnpm build
```
