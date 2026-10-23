# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Svelte 5, SvelteKit, TypeScript, Tailwind CSS

## Users

Usuários finais e administradores de organizações que utilizam a plataforma.

## Product Purpose

Console administrativo web unificado da plataforma Smarkee IT Solutions. Interface para lidar com estado declarativo, mensageria semântica assíncrona e orquestração colaborativa entre humanos e IAs.

## Positioning

Um cliente fino web da API pública da Smarkee que gerencia recursos assíncronos e expõe o modelo de reconciliação (estado desejado vs. estado observado) e as operações (Operations) da plataforma de forma semântica e clara (pt-BR), ocultando a complexidade dos contratos internos de infraestrutura.

## Operating Context

Navegador web, operando como cliente de uma API baseada em NATS JetStream (via REST adaptadores) e integrada ao Zitadel via OIDC (Authorization Code Flow com PKCE) para autenticação. 

## Capabilities and Constraints

- Cliente fino da API pública: não reinventa regras de autorização ou de domínio.
- Gestão de Identidade e Organizações (IPM), Serviços (SUM), Eventos de Auditoria (AEM) e Observabilidade (ODM).
- Contratos TypeScript são rigorosamente derivados dos JSON Schemas presentes em `schemas/`.
- Tolerância a falhas temporárias, operações assíncronas do loop de controle, e falha de convergência. 
- Componentes e navegação com uso rigoroso de Svelte 5 e seus runes.

## Brand Commitments

- Identidade visual própria da Smarkee com Verde vivo como cor primária; fundo claro; tipografia azul-marinho escura.
- Evitar a paleta azul predominante do Google Cloud Console.
- Idioma pt-BR para a interface de usuário; termos técnicos e de contrato em inglês.
- Logotipos oficiais na pasta `images/`.

## Evidence on Hand

- Referência visual aprovada em `images/console-main-layout.png`.
- Documentação e regras rígidas de UI/UX descritas em `docs/console/CONSOLE.md`.
- Contratos de schemas JSON em `schemas/`.

## Product Principles

1. Explicitar a assincronia e os estados (Pending/Reconciling/Ready/Failed) em vez de omitir, mas usar linguagem humana em vez de JSON puro.
2. A UI segue estritamente a API sem inventar regras de negócio, dados falsos ou falsos progressos.
3. Simplicidade, segurança e reatividade nativa do Svelte 5 (Runes) no cliente.

## Accessibility & Inclusion

- Suporte completo a navegação por teclado, foco visível, rótulos ARIA (aria-label, aria-expanded), e atalhos globais (⌘K/Ctrl+K).
- Respeitar prefers-reduced-motion e contraste adequado (nunca comunicar estado apenas com cor).
