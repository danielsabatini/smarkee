# Changelog

Todas as alterações notáveis neste projeto serão documentadas neste arquivo.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.1.0/),
e este projeto adere ao [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [Unreleased]

### Changed
- Mensageria: `desired` e `observed` passam a usar sempre a operação `changed` (um endereço por recurso); o resultado da observação (`present`, `absent`, `unknown`) passa a ser o campo `presence`, e `observedAt` torna-se obrigatório em `observed`. Novos campos do envelope: `actionId` e `requestedBy` (`docs/MESSAGING.md`).
- NATS: um Stream por `messageType` (`REQUESTED` e `ACTION` em `WorkQueue`; `DESIRED` e `OBSERVED` em `Limits` com o último estado por recurso; `RESULT` e `UPDATED` em `Limits` com `MaxAge`), consumidores por função e autorização por Stream (`docs/NATS.md`).
- Resource Control Loop: subjects de exemplo alinhados à operação `changed` (`docs/RESOURCE-CONTROL-LOOP.md`).
- NATS: consumers classificados em trabalho, persistência e estado em memória. Trabalho e persistência usam consumer durável pull compartilhado; Reconciler e Observer usam um consumer por instância com `DeliverLastPerSubject`; o Executor usa `pinned_client` com `max_ack_pending=1` em `ACTION` e lê o `desired` por Direct Get. Cada consumer possui filtro único `<módulo>.<tipo>` (`docs/NATS.md`).
- Segurança: identidade e permissões por serviço (`<módulo>-<tipo>-<papel>`), escopadas por `<módulo>.<tipo>`; nenhum serviço de runtime possui purge ou administração de Stream (`docs/RESOURCE-CONTROL-SECURITY.md`).
- Remoção de recursos: o último `desired` permanece como tombstone até limpeza por job administrativo, em vez de purge pelo Manager (`docs/NATS.md`).

### Added
- Especificação de mensageria assíncrona semântica e integração com NATS JetStream (`docs/MESSAGING.md`, `docs/NATS.md`).
- Especificação de governança, versionamento e evolução de schemas de contratos (`docs/SCHEMA.md`).
- Especificação do padrão Resource Control Loop para gerenciamento declarativo e convergente de recursos (`docs/RESOURCE-CONTROL-LOOP.md`).
- Especificação de segurança do Resource Control Loop: modelo de ameaças, identidades, autorização no barramento, proteção da `action`, confiabilidade da observação e limites de abuso (`docs/RESOURCE-CONTROL-SECURITY.md`).
- Estrutura inicial dos componentes da plataforma (`components/cli`, `components/manager`, `features/ipm`), ainda sem implementação.
- Licença Apache-2.0 (`LICENSE`).
