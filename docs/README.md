# Documentação

Índice por pergunta. Cada tema tem **uma** fonte de verdade; os outros arquivos apontam para ela (`AGENTS.md` §1.1).

| Pergunta | Onde |
|---|---|
| Como funciona o ciclo `desired` → `observed` → `action`? Quais são os papéis? | [`RESOURCE-CONTROL-LOOP.md`](loop/RESOURCE-CONTROL-LOOP.md) |
| Quais são as regras de segurança do loop (identidades, ações destrutivas, observação)? | [`RESOURCE-CONTROL-SECURITY.md`](loop/RESOURCE-CONTROL-SECURITY.md) |
| O que significa cada mensagem, e como é o envelope e o Subject? | [`MESSAGING.md`](messaging/MESSAGING.md) |
| Como o NATS JetStream é usado (Streams, consumers, partição, retry)? | [`NATS.md`](messaging/NATS.md) |
| Como inspeciono o NATS pela CLI (Streams, consumers, mensagens, atrasos) para depurar? | [`NATS-CLI.md`](messaging/NATS-CLI.md) |
| Como os contratos (JSON Schema) são definidos e evoluem? | [`SCHEMA.md`](data/SCHEMA.md) |
| **O que o banco guarda e com quais garantias** (modelo lógico, entidades e relacionamentos, unidade atômica, outbox)? | [`SSOT.md`](data/SSOT.md), seção 7 |
| **Como o banco é estruturado no PostgreSQL** (tabelas, colunas, índices, views, privilégios, DDL)? | [`POSTGRESQL.md`](data/POSTGRESQL.md), seção 6 |
| O que trafega e o que é gravado em cada passo de uma feature (rota, payload, query, linhas)? | `features/<módulo>/<tipo>/docs/<MÓDULO>-<TIPO>-DATA-FLOW.md` (padrão: [`.decisions/0024`](../.decisions/0024-data-flow-por-feature.md); modelo: [`CORE-ACCOUNT-DATA-FLOW.md`](../features/core/account/docs/CORE-ACCOUNT-DATA-FLOW.md)) |
| Como é o banco de um tipo real (diagrama de entidade e relacionamento, índices, quem grava o quê)? | [`features/core/account/README.md`](../features/core/account/README.md), seção 11 |
| Como são os logs dos componentes (formato OpenTelemetry, campos, o que não registrar)? | [`OBSERVABILITY.md`](telemetry/OBSERVABILITY.md) |
| Como a telemetria é coletada, roteada e gravada (agente, roteador, telemeters, filas, Kubernetes)? | [`OBSERVABILITY-ARCHITECTURE.md`](telemetry/OBSERVABILITY-ARCHITECTURE.md) |
| Como apontar a CLI `sk` para dev ou stg, logar como usuário ou operador e resolver os erros comuns? | [`cli/CLI-DEV-STG.md`](cli/CLI-DEV-STG.md) |
| Como fazer backup, verificar integridade, restaurar e resetar o ambiente de desenvolvimento de forma segura? | [`backup/dev/BACKUP.md`](backup/dev/BACKUP.md) |
| Como começar uma feature nova (o que gerar, copiar e registrar)? | [`FEATURE-BOOTSTRAP.md`](platform/FEATURE-BOOTSTRAP.md) |
| O que já está implementado e o que falta, item a item? | [`IMPLEMENTATION-STATUS.md`](platform/IMPLEMENTATION-STATUS.md) |
| Por que foi decidido assim? | [`.decisions/`](../.decisions/) |

## Estrutura

| Pasta | Tema |
|---|---|
| [`loop/`](loop/) | Ciclo de controle de recursos e sua segurança |
| [`messaging/`](messaging/) | Modelo de mensagens e NATS JetStream |
| [`data/`](data/) | SSOT, PostgreSQL e contratos (JSON Schema) |
| [`platform/`](platform/) | Criação de features e estado da implementação |
| [`telemetry/`](telemetry/) | Logs, métricas e traces |
| [`cli/`](cli/) | Uso da CLI `sk` |
| [`backup/`](backup/dev/BACKUP.md) | Backup, restauração e reset seguro de ambientes |
| [`console/`](console/), [`billing/`](billing/) | Console e faturamento |

## Diagramas

Em [`diagrams/`](diagrams/): `ssot-er-logico` (entidades e relacionamentos lógicos), `postgresql-er-fisico` (o mesmo, em tabelas e colunas), `ssot-gravacao-por-mensagem` (quais registros cada mensagem altera) e `postgresql-privilegios` (quem lê e escreve cada tabela). A fonte é o `.mmd` ao lado de cada `.svg`; regere o SVG quando alterar o `.mmd` (por exemplo, `npx @mermaid-js/mermaid-cli -i <arquivo>.mmd -o <arquivo>.svg`). O ER físico deve ser revisado quando uma migração mudar uma tabela. Os diagramas de um tipo concreto ficam na feature (`features/core/account/docs/`). Imagens estáticas antigas: [`images/README.md`](images/README.md).
