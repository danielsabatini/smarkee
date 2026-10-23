---
name: Smarkee IT Solutions Site
description: Plataforma de Hospedagem Focada no seu Produto (Vitrine Comercial)
colors:
  brand-primary: '#059669'
  brand-primary-hover: '#047857'
  brand-surface: '#ecfdf5'
  brand-accent: '#34d399'
  text-heading: '#0f172a'
  text-body: '#475569'
  surface-canvas: '#f8fafc'
  surface-card: '#ffffff'
  border-subtle: '#e2e8f0'
  border-strong: '#cbd5e1'
typography:
  display:
    fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif'
    fontSize: 'clamp(2.25rem, 5vw, 3.75rem)'
    fontWeight: 800
    lineHeight: 1.2
    letterSpacing: '-0.025em'
  headline:
    fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif'
    fontSize: '1.875rem'
    fontWeight: 800
    lineHeight: 1.25
  title:
    fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif'
    fontSize: '1.125rem'
    fontWeight: 700
    lineHeight: 1.4
  body:
    fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif'
    fontSize: '0.875rem'
    fontWeight: 400
    lineHeight: 1.625
  label:
    fontFamily: 'Inter, ui-sans-serif, system-ui, sans-serif'
    fontSize: '0.75rem'
    fontWeight: 700
  mono:
    fontFamily: 'JetBrains Mono, ui-monospace, SFMono-Regular, monospace'
    fontSize: '0.75rem'
    fontWeight: 600
rounded:
  sm: '4px'
  md: '8px'
  lg: '12px'
  xl: '16px'
  full: '9999px'
spacing:
  sm: '8px'
  md: '16px'
  lg: '24px'
  xl: '32px'
  2xl: '48px'
components:
  button-primary:
    backgroundColor: '{colors.brand-primary}'
    textColor: '{colors.surface-card}'
    rounded: '{rounded.xl}'
    padding: '6px 16px'
  button-primary-hover:
    backgroundColor: '{colors.brand-primary-hover}'
  button-large:
    backgroundColor: '{colors.brand-primary}'
    textColor: '{colors.surface-card}'
    rounded: '{rounded.xl}'
    padding: '12px 24px'
---

# Design System: Smarkee IT Solutions Site

## Overview

**Creative North Star: "Plataforma Simples e Acessível"**

A vitrine de tecnologia que transmite confiança, clareza e proximidade. O sistema visual constrói uma superfície ampla e limpa — operando predominantemente no espectro claro (Light Mode) — onde o verde esmeralda entra com precisão para indicar identidade e chamada para ação (CTAs). O tom é profissional, focado em benefícios comerciais.

A plataforma busca ser um contraponto acessível à densidade típica de provedores de nuvem globais. Diferente do Console Smarkee (focado em Operate/trabalho denso), o site é Persuade: sua missão é educar, atrair e converter.

**Key Characteristics:**

- Canvas claros predominantes (branco e tons suaves de slate).
- Verde Esmeralda (Emerald-600) usado em botões de ação primários e acentos estratégicos.
- Hierarquia tipográfica que privilegia pesos altos (Extrabold 800) em títulos para impacto sem depender de fontes enormes.
- Bordas sutis arredondadas (16px) e sombras restritas, priorizando um visual limpo e sem poluição.

## Colors

O sistema utiliza a paleta Slate para estrutura e textos, pontuado pela paleta Emerald (Verde) para a marca.

### Primary

- **Emerald Primary** (`#059669` / emerald-600): Cor principal da marca, reservada para botões de CTA, links interativos críticos e ícones de destaque.
- **Emerald Hover** (`#047857` / emerald-700): Utilizado nos estados de hover de botões primários.

### Neutral

- **Heading Text** (`#0f172a` / slate-900): Títulos principais (h1, h2, h3).
- **Body Text** (`#475569` / slate-600): Parágrafos e subtítulos longos.
- **Canvas** (`#f8fafc` / slate-50): Fundo base para grandes blocos de separação visual (ex: seção hero).
- **Card Background** (`#ffffff`): Fundo primário de cartões, barra de navegação e componentes modulares.
- **Border Subtle** (`#e2e8f0` / slate-200): Usado nas divisões e contornos dos cartões secundários.

### Named Rules

**The Emerald Signal Rule.** A cor verde esmeralda não deve ser utilizada como cor de texto para parágrafos longos ou fundos densos. Ela atua estritamente como um sinal de ação ou demarcação da marca.

## Typography

**Display Font:** Inter (com fallback para system-ui)
**Body Font:** Inter
**Mono Font:** JetBrains Mono (usada exclusivamente para representações de código ou comandos CLI).

**Character:** Limpo, pragmático e altamente legível.

### Hierarchy

- **Display** (800, `clamp(2.25rem, 5vw, 3.75rem)`, 1.2): Utilizado apenas no título principal (Hero) de cada página.
- **Headline** (800, 1.875rem, 1.25): Títulos de seção grandes.
- **Title** (700, 1.125rem, 1.4): Títulos de cartões de módulos e capacidades.
- **Body** (400, 0.875rem, 1.625): Textos explicativos e descrições gerais.
- **Label** (700, 0.75rem, uppercase opcional): Rótulos de formulário e categorias (ex: tags do blog).
- **Mono** (600, 0.75rem, 1.625): Trechos de terminal ou configurações técnicas.

### Named Rules

**The Weight Is the Hierarchy Rule.** Não crie hierarquia utilizando fontes diferentes ou cores gritantes. O contraste principal entre um título e um parágrafo é feito através do peso da fonte (800 vs 400).

## Layout

Containers centrais com largura máxima controlada (`max-w-7xl` para o grid da página e `max-w-4xl` para textos centralizados e artigos). Espaçamentos amplos entre seções (py-16 ou py-28) para permitir a "respiração" do conteúdo comercial.

## Elevation & Depth

Sistema "Flat-by-Default" pontuado por sombras extremamente suaves (shadow-2xs) em botões ou contêineres de repouso, utilizando `shadow-md` unicamente no hover para indicar que o componente é clicável (ex: cards que levam a uma página de detalhe).

## Shapes

- **16px (`rounded-xl`):** Raio de curvatura padrão em quase todos os botões e contêineres de card interativos.
- **Full (`rounded-full`):** Exclusivo para tags/badges que indicam status pequenos ou avatares de blog.

## Components

### Buttons

- **Shape:** 16px radius (`rounded-xl`).
- **Primary:** Fundo emerald-600, texto branco, padding adaptativo. Sombra 2xs de repouso.
- **Secondary / Ghost:** Fundo branco, texto slate-700, borda slate-200.

### Cards / Containers

- **Style:** Fundo branco com bordas slate-200 para separar sutilmente do background slate-50, sem bordas pesadas.

## Do's and Don'ts

### Do:

- **Do** utilizar a família de cores Slate para organizar e delimitar seções em vez de utilizar contornos grossos.
- **Do** garantir contraste impecável nas cores do texto principal.

### Don't:

- **Don't** utilizar temas escuros (Dark Mode) ou componentes dark densos no site comercial (reservado para Console).
- **Don't** entulhar a homepage de tabelas ou códigos, use o JetBrains Mono em snippets bem específicos e isolados.
