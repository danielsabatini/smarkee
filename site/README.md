# Smarkee IT Solutions — Website Oficial

Website institucional e portal público da **Smarkee IT Solutions**, uma plataforma de nuvem declarativa com controle de identidade multi-tenant (IPM), catálogo sob demanda (SUM), auditoria imutável (AEM) e observabilidade aberta (ODM).

## 🚀 Tecnologias

- **Framework:** SvelteKit (Svelte 5 Runes)
- **Estilização:** Tailwind CSS v4 com design tokens oficiais da Smarkee
- **Tipografia:** Inter (sans) e JetBrains Mono (mono)
- **Ícones:** Lucide Svelte
- **Qualidade & Testes:** Vitest, TypeScript estrito, ESLint, Prettier

## 📁 Estrutura de Rotas

- `/`: Landing page de alto impacto com:
  - Hero com proposta de valor, métricas e preview do console
  - Suíte de módulos (IPM, SUM, AEM, ODM) e CLI `sk`
  - Simulador interativo do **Loop de Controle Declarativo** (Desired vs Observed)
  - Visualizador de código com abas (CLI, REST API, JSON Schema V1)
  - Chamada para os artigos recentes do blog
  - Seção final de conversão
- `/blog`: Diretório do Blog com busca e filtros por categoria
- `/blog/[slug]`: Artigos técnicos detalhados com autor, tempo de leitura e tags
- `/produtos`: Detalhamento técnico dos módulos da plataforma
- `/solucoes`: Casos de uso (Internal Developer Platform, Multi-tenant Cloud, Governança)
- `/sobre`: Missão institucional, arquitetura e pilares da engenharia
- `/contato`: Formulário de contato e agendamento de demonstração técnica

## 🛠️ Comandos

Na pasta `/Users/dsfreitas/code/smarkee/site`:

```bash
# Instalar dependências
pnpm install

# Iniciar servidor de desenvolvimento (porta 3000)
pnpm dev

# Verificação estática de tipos Svelte/TS
pnpm check

# Lint e validação de formatação
pnpm lint

# Testes unitários
pnpm test:unit

# Build de produção
pnpm build

# Pré-visualização do build de produção
pnpm preview
```
