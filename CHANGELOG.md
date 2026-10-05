# Changelog

Todas as alterações notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Added
- Especificação de mensageria assíncrona semântica e integração com NATS JetStream (`docs/MESSAGING.md`, `docs/NATS.md`).
- Especificação de governança, versionamento e evolução de schemas de contratos (`docs/SCHEMA.md`).
- Especificação do padrão Resource Control Loop para gerenciamento declarativo e convergente de recursos (`docs/RESOURCE-CONTROL-LOOP.md`).
- Especificação de segurança do Resource Control Loop: modelo de ameaças, identidades, autorização no barramento, proteção da `action`, confiabilidade da observação e limites de abuso (`docs/RESOURCE-CONTROL-SECURITY.md`).
- Estrutura inicial dos componentes da plataforma (`components/cli`, `components/manager`, `features/ipm`), ainda sem implementação.
- Licença Apache-2.0 (`LICENSE`).
