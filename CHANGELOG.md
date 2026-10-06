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

- Resource Control Loop: o `actionId` passa a incluir a observação que motivou a decisão (a correção de drift não é mais descartada como duplicata); o Executor consulta o desfecho do `actionId` em `RESULT` antes de executar; ordenação causal após `completed`/`failed` (`causationId` da observação); falhas contadas pelo Manager com suspensão da reconciliação no `desired`; observação periódica particionada por `resourceId`; condition `ObservationStale` (`docs/RESOURCE-CONTROL-LOOP.md`, `docs/MESSAGING.md`, `docs/NATS.md`).
- Resource Control Loop: documento simplificado (de 2104 para cerca de 1700 linhas), com fluxos redundantes consolidados.

- Schemas: `docs/SCHEMA.md` reescrito e tornado agnóstico de produto, domínio e formato. Passa a definir política de versionamento (`MAJOR.MINOR`, coexistência, migração do estado retido), regra do leitor tolerante com modos de validação estrito e tolerante, política de enums, segurança dos contratos (limites obrigatórios, classificação de sensibilidade, campos atribuídos pelo servidor, validação nas fronteiras), anotações de campo para a comparação `desired` × `observed`, parâmetros de recurso do control loop, família de contratos por `messageType` e artefatos derivados. O exemplo de envelope foi alinhado a `docs/MESSAGING.md`.
- Schemas: padrão concreto de `resourceId`, limites de referência, regex de tempo linear, referências apenas locais, classificação de sensibilidade obrigatória (sem valor padrão), campos `writer = server` atribuídos pelo componente responsável, `schemaVersion` como versão do contrato completo da mensagem, republicação do estado retido preservando a geração, conversão na leitura, tratamento de falha de validação como falha permanente e testes de compatibilidade nos dois sentidos. `desiredGeneration` não muda quando só `reconciliation` muda (`docs/SCHEMA.md`, `docs/MESSAGING.md`).
- Vocabulários distintos: `lifecycle` (intenção em `desired`), `presence` (resultado em `observed`) e `phase` (fase consolidada do recurso); novo campo de controle `reconciliation` (`active`/`suspended`) em `desired`.

- SSOT: toda unidade atômica do Manager começa com acesso exclusivo ao registro do recurso (`FOR UPDATE`), o que impede que `observed` e resultados processados em paralelo sobrescrevam as `conditions` um do outro (`docs/SSOT.md`, `docs/POSTGRESQL.md`).
- SSOT: idempotência de `requested` pela identidade da Operation (`operationId`), atribuída pela API e derivada da chave de idempotência no escopo do solicitante; o contrato `requested` ganha `operationId` e `requestDigest`. A Operation ganha o estado `rejected` com motivo (`conflict`, `validation`, `not_found`) (`docs/SSOT.md`, `docs/SCHEMA.md`).
- SSOT: o relay publica o outbox de forma sequencial, sem `FOR UPDATE`, e confere a posse da trava consultiva antes de cada lote (`docs/POSTGRESQL.md`).
- PostgreSQL: a API lê o SSOT somente pelas views versionadas `<tipo>_v<MAJOR>` e `<tipo>_operation_v<MAJOR>`; o Manager deixa de ter `SELECT` no outbox; `PUBLIC` perde `CONNECT` e `TEMPORARY` no banco; parâmetros de sessão nos papéis de login de runtime; limites de comprimento nas colunas de identificação (`docs/POSTGRESQL.md`).
- Infraestrutura de desenvolvimento: o administrador do PostgreSQL passa a ser `postgres`, e o banco do SSOT é criado pela inicialização (`infrastructure/dev`).

### Removed
- SSOT: tabela de inbox; a idempotência de entrada é garantida pelas regras semânticas (`docs/SSOT.md`, `docs/POSTGRESQL.md`).

### Fixed
- SSOT: resultados `completed` e `failed` reentregues eram contados de novo, e resultados de geração anterior eram contados contra a geração atual; nova tabela `<tipo>_action_result` registra o `actionId` (`docs/SSOT.md`, `docs/POSTGRESQL.md`).
- SSOT: restauração a um ponto no tempo podia reutilizar uma geração já publicada com outro conteúdo; novo procedimento de recuperação executado antes de liberar o Manager e o relay (`docs/SSOT.md`, `docs/POSTGRESQL.md`).

### Added
- Especificação do SSOT: modelo lógico, dicionário de dados, invariantes, unidade atômica de gravação por mensagem, concorrência otimista, idempotência semântica, outbox com ordem por recurso, segurança, evolução e recuperação, agnóstica de tecnologia de armazenamento (`docs/SSOT.md`).
- Implementação de referência do SSOT em PostgreSQL com `jsonb`: mapeamento, DDL de referência exercitado em contêiner descartável, concorrência otimista, relay do outbox de instância única (sem `SKIP LOCKED`), privilégios por serviço, migrações, retenção, PITR e verificações (`docs/POSTGRESQL.md`).
- Especificação de mensageria assíncrona semântica e integração com NATS JetStream (`docs/MESSAGING.md`, `docs/NATS.md`).
- Especificação de governança, versionamento e evolução de schemas de contratos (`docs/SCHEMA.md`).
- Especificação do padrão Resource Control Loop para gerenciamento declarativo e convergente de recursos (`docs/RESOURCE-CONTROL-LOOP.md`).
- Especificação de segurança do Resource Control Loop: modelo de ameaças, identidades, autorização no barramento, proteção da `action`, confiabilidade da observação e limites de abuso (`docs/RESOURCE-CONTROL-SECURITY.md`).
- Estrutura inicial dos componentes da plataforma (`components/cli`, `components/manager`, `features/ipm`), ainda sem implementação.
- Licença Apache-2.0 (`LICENSE`).
