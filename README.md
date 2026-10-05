# Smarkee

## 1. Introdução

O **Smarkee** é uma plataforma de arquitetura distribuída projetada para lidar com estado declarativo, mensageria semântica assíncrona e orquestração colaborativa entre humanos e Inteligências Artificiais. 

O projeto adota o conceito de "Desired" (estado desejado) e "Observed" (estado observado), garantindo alta resiliência, idempotência e observabilidade ponta a ponta na entrega de trabalho por meio do ecossistema NATS JetStream.

## 2. Objetivos

O projeto tem como premissas fundamentais:
- **Resiliência e Correção**: Desenvolver contratos assíncronos imutáveis onde a falha é esperada e tratada via deduplicação e *retries* controlados.
- **Transparência Semântica**: Explicitar o impacto e a intenção de cada componente e mensagem.
- **Governança Híbrida (IA e Humanos)**: Manter regras rígidas de atuação de software e código que garantam que as IAs possam estender a plataforma sem destruir o contexto, alucinar arquiteturas ou corromper a documentação oficial.

## 3. Estrutura de Documentação (Fonte Única da Verdade)

Para evitar duplicidade e conflitos operacionais, o projeto consolida o conhecimento em arquivos e diretórios estritos. Utilize este mapa para navegar pela documentação:

| Local | Finalidade |
|---|---|
| [`AGENTS.md`](AGENTS.md) | **Lei Geral.** Regras obrigatórias de governança, arquitetura e limites de atuação para Agentes de IA e Desenvolvedores. |
| [`docs/`](docs/) | **Especificações Técnicas.** Fonte Única de Verdade (SSOT) para contratos, fluxos e implementação.<br>👉 *Ver: [`docs/MESSAGING.md`](docs/MESSAGING.md), [`docs/NATS.md`](docs/NATS.md), [`docs/SCHEMA.md`](docs/SCHEMA.md), [`docs/RESOURCE-CONTROL-LOOP.md`](docs/RESOURCE-CONTROL-LOOP.md) e [`docs/RESOURCE-CONTROL-SECURITY.md`](docs/RESOURCE-CONTROL-SECURITY.md)* |
| [`.decisions/`](.decisions/) | **ADRs.** Diretório de registro para decisões arquiteturais permanentes que mudam o rumo do projeto. |
| [`ROADMAP.md`](ROADMAP.md) | **Planejamento.** Metas direcionais e de curto/longo prazo separadas em horizontes lógicos (*Now, Next, Later*). |
| [`CHANGELOG.md`](CHANGELOG.md) | **Histórico de Releases.** Registro cronológico (SemVer) e semântico das novidades, correções e remoções. |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | **Guia de Contribuição.** Fluxo prático e burocrático (Pull Requests, regras locais) para quem deseja colocar a mão na massa. |

*Notas sobre execução:* Pastas como `.workspace/` e `.journal/` são reservadas para arquivos temporários e logs da plataforma, respectivamente. A área de transferência de contexto para as IAs fica restrita ao arquivo `MEMORY.md`.

## 4. Primeiros Passos

Se você é um novo membro humano (ou um Agente sendo inicializado), seu fluxo de leitura deve ser:

1. Leia o **`AGENTS.md`** para entender as leis irrefutáveis do projeto.
2. Verifique o **`CONTRIBUTING.md`** para entender como atuar nos repositórios.
3. Consulte o **`ROADMAP.md`** para descobrir onde estamos focado hoje (`Now`) e o que virá em seguida (`Next`).
4. Para implementar soluções, estude rigorosamente os arquivos técnicos em **`docs/`**.
