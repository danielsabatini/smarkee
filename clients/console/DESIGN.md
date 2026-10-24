---
name: Smarkee Console
description: Console administrativo web unificado da plataforma Smarkee IT Solutions.
colors:
  brand-50: '#ecfdf5'
  brand-100: '#d1fae5'
  brand-200: '#a7f3d0'
  brand-300: '#6ee7b7'
  brand-400: '#34d399'
  brand-500: '#10b981'
  brand-600: '#16a34a'
  brand-700: '#15803d'
  brand-800: '#065f46'
  brand-900: '#064e3b'
  surface-canvas: '#f8fafc'
  surface-card: '#ffffff'
  surface-subtle: '#f1f5f9'
  text-primary: '#0f172a'
  text-secondary: '#475569'
  text-muted: '#64748b'
  border-subtle: '#e2e8f0'
  border-strong: '#cbd5e1'
  status-ready-bg: '#dcfce7'
  status-ready-text: '#15803d'
  status-progress-bg: '#dbeafe'
  status-progress-text: '#1d4ed8'
  status-warning-bg: '#fef3c7'
  status-warning-text: '#b45309'
  status-failed-bg: '#fee2e2'
  status-failed-text: '#b91c1c'
typography:
  body:
    fontFamily: 'var(--font-sans)'
  label:
    fontFamily: 'var(--font-mono)'
rounded:
  sm: '4px'
  md: '8px'
  lg: '12px'
  xl: '16px'
  full: '9999px'
components:
  status-badge-ready:
    backgroundColor: '{colors.status-ready-bg}'
    textColor: '{colors.status-ready-text}'
    padding: '4px 10px'
    rounded: '{rounded.full}'
  copyable-id:
    backgroundColor: '{colors.surface-subtle}'
    textColor: '{colors.text-primary}'
    typography: '{typography.label}'
    padding: '8px 12px'
    rounded: '{rounded.md}'
  nav-link-active:
    backgroundColor: '{colors.brand-50}'
    textColor: '{colors.brand-900}'
    typography: '{typography.body}'
    padding: '8px'
    rounded: '{rounded.md}'
  demo-badge:
    backgroundColor: '#fffbeb'
    textColor: '#92400e'
    padding: '2px 4px'
    rounded: '{rounded.sm}'
  empty-state:
    backgroundColor: '#f8fafc'
    textColor: '{colors.text-primary}'
    padding: '40px 24px'
    rounded: '{rounded.lg}'
---

# Design System: Smarkee Console

## Overview

**Creative North Star: "O Painel de Controle Declarativo"**

A interface prioriza a clareza operacional acima de tudo. O ruído visual é mínimo, permitindo que os estados de recursos (Pending, Ready, Failed) e a reconciliação contínua falem por si mesmos. A UI adota tons sóbrios de azul-marinho para tipografia e um verde vivo como acento para estados de sucesso e identidade da marca, garantindo legibilidade máxima sobre superfícies claras.

**Key Characteristics:**

- **Clareza de Estado:** Explicitar a assincronia; cores semânticas atreladas diretamente às fases do loop de controle.
- **Sólido e Preciso:** Raios sutis, bordas nítidas delimitando áreas. Ausência de sombras marcadas.
- **Zero Falsos Progressos:** A interface apenas reflete a API sem simular respostas imediatas.
- **Desenvolvido para humanos e teclados:** Navegação eficiente, uso de atalhos e rótulos acessíveis.

## Colors

Um sistema claro, focado em alta densidade de dados e clareza de estado.

### Primary (Marca)

- **Verde Smarkee (Brand 500-700)** (#10b981 a #15803d): Acentos interativos primários e indicadores de que a plataforma está operando em conformidade (Ready).

### Neutral (Superfícies e Texto)

- **Canvas** (#f8fafc): O fundo global da aplicação, reduzindo a fadiga visual.
- **Card** (#ffffff): Superfícies contendo dados e agrupamentos lógicos.
- **Text Primary** (#0f172a): Texto de leitura de alta ênfase (azul-marinho quase preto).
- **Text Secondary** (#475569): Meta-informações e rótulos secundários.
- **Border Subtle** (#e2e8f0): Linhas de grade e delimitadores internos muito suaves.

### Semantic Status (Estados do Loop de Controle)

- **Ready** (bg: #dcfce7, text: #15803d): Recurso convergiu com sucesso.
- **Progress** (bg: #dbeafe, text: #1d4ed8): Recurso pendente ou reconciliando ativamente (azul).
- **Warning** (bg: #fef3c7, text: #b45309): Estado degradado ou requisição rejeitada (âmbar).
- **Failed** (bg: #fee2e2, text: #b91c1c): Operação falhou (vermelho).

## Typography

**Body Font:** Inter, system-ui, sans-serif
**Label/Mono Font:** JetBrains Mono, ui-monospace, monospace

**Character:** Utilitária e técnica. Usa a legibilidade da Inter para leitura e a previsibilidade da JetBrains Mono para IDs e dados técnicos.

### Hierarchy

- **Body** (400, texto principal): O cavalo de batalha do console, usado para nomes de recursos e descrições.
- **Label** (500, Mono): Identificadores (UUIDs), chaves, valores JSON e metadados.

## Layout

**Container:** O console restringe layouts internos para melhorar o scanning visual em telas ultra-largas (max-w-7xl).
**Densidade:** Média-alta. Espaçamentos não devem sacrificar a quantidade de dados visíveis.
**Rhythm:** Baseado na escala padrão do Tailwind (4px, 8px, 16px, 24px).

## Elevation & Depth

**The Flat-By-Default Rule.** Superfícies são planas. A separação visual entre camadas é alcançada principalmente por meio de bordas suaves (`border-slate-200`) e leves alterações tonais no fundo (`bg-slate-50` vs `bg-white`), sem dependência excessiva de sombras (box-shadow).

## Shapes

O sistema form-language foca na estrutura geométrica previsível.

- **Superfícies (Cartões, painéis, modais):** Cantos arredondados, variando de médios (8px) a grandes (12px/16px) dependo da escala da superfície (`rounded-lg` e `rounded-xl`).
- **Badges/Tags:** Formatos "pill" totalmente arredondados (`rounded-full`).

## Components

### Status Badge

- **Shape:** Pill (9999px / `rounded-full`).
- **Style:** Fundo de cor muito clara (ex: `bg-status-ready-bg`) com texto de alta saturação (`text-status-ready-text`) e borda fina de 20% de opacidade da cor do texto.
- **Behavior:** Frequentemente acompanhados de ícones Lucide pequenos (14px) para reforçar a semântica de estado (CheckCircle2, Loader2, AlertTriangle, XCircle).

### Navigation Link (Sidebar)

- **Shape:** Arredondado (8px / `rounded-lg`).
- **Active State:** Fundo sutil da marca (`bg-brand-50`), texto forte (`text-brand-900`) e anel/borda para foco (`ring-1 ring-brand-200/80`).
- **Default / Hover:** Texto neutro (`text-slate-700`), muda para fundo sutil ao passar o mouse (`hover:bg-slate-100 hover:text-slate-900`).

### Campos e Inputs de Cópia Técnica (CopyableId)

- **Shape:** Arredondado (8px / `rounded-lg`).
- **Style:** Fundo sutil (`bg-slate-100`), texto escuro (`text-slate-900`) com tipografia Monospace pequena (11px).
- **Behavior:** Permitem clique único e feedback imediato de cópia bem-sucedida, mudando o ícone para verde da marca (`text-brand-700` e `hover:bg-brand-100`).

### Demo Badge

- **Shape:** Arredondado (4px / `rounded`) ou ícone interativo (pílula expansível).
- **Style:** Cores de atenção semântica para diferenciar do conteúdo de produção (fundo `amber-50`, texto `amber-800`, borda `amber-200`).

### Empty State

- **Shape:** Contêiner espaçoso (12px / `rounded-xl`).
- **Style:** Fundo quase transparente (`bg-slate-50/70`), borda tracejada (`border-dashed border-slate-300`).
- **Iconografia:** Círculo de destaque sutil da marca (`bg-brand-50 text-brand-700`) centralizado.

## Do's and Don'ts

### Do:

- **Do** expor IDs longos (ex: UUIDs 36-char) preferencialmente em tipografia monoespaçada sem quebras no meio, garantindo cópia segura.
- **Do** usar sempre uma cor de fundo sutil para Badges (50 ou 100), nunca sólida (500 ou 600), para manter o conforto na leitura de muitas tags na tela.
- **Do** atrelar a linguagem visual ao estado atual refletido pelo servidor.

### Don't:

- **Don't** ocultar atrasos operacionais ou estado de progresso atrás de spinners globais de carregamento. Cada recurso possui seu próprio badge com estado e loader local.
- **Don't** usar vermelho ou verde puros para estética. A cor no Smarkee possui estrito valor semântico de status e marca.
