# Changelog

Todas as alterações notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Added
- Diretrizes de padrão de comunicação com o harness (pt-BR) e convenções de idioma no código (código e logs em inglês; comentários, docstrings e help em pt-BR) no `AGENTS.md`.
- Governança geral e leis fundamentais para agentes de IA e engenharia (`AGENTS.md`).
- Especificações técnicas para mensageria assíncrona e integração com NATS JetStream (`docs/MESSAGING.md`, `docs/NATS.md`).
- Estrutura de roteamento e documentação oficial (`README.md`, `CONTRIBUTING.md`, `ROADMAP.md`).
- Estrutura para memória operacional de agentes (`MEMORY.md`) e registro de decisões arquiteturais (`.decisions/`).
- Estrutura inicial dos componentes de plataforma (`components/cli`, `components/manager`, `features/ipm`).
- Subagentes e skills especializados para o ambiente OpenCode (`messaging`, `platform`, `python`, `sonarqube`, `nats`, `python-quality`).
