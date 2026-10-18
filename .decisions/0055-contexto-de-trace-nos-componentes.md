# 0055 — Contexto de trace nos componentes (fase 1 do trace distribuído)

- **Data:** 2026-10-18
- **Status:** Aceita e implementada em desenvolvimento. Estende as decisões 0045, 0050 e 0054.
- **Origem:** a avaliação de observabilidade de 2026-10-17 (item 1: "implementar o trace distribuído, passo a passo").

## Contexto

O gateway cria o trace de cada requisição (decisões 0050 e 0054), mas o trace terminava ali: os componentes não liam o `traceparent`, o NATS e o outbox não o carregavam e os logs não tinham `trace_id`. Não era possível seguir um pedido do gateway até o Zitadel pelos logs.

Os componentes são autônomos por papel e só têm 9 dependências, sem OpenTelemetry. Adotar o SDK em 18 componentes é uma dependência nova (AGENTS §21) e um custo de manutenção. Os logs, porém, já podem levar `trace_id` e `trace_flags` (contrato 0045).

## Decisão

- **Fase 1: repassar o contexto e gravá-lo nos logs. Sem SDK e sem spans.** O `traceparent` W3C entra pelo Receiver (header HTTP injetado pelo gateway), vai no **header NATS `traceparent`** (ao lado de `Nats-Msg-Id`, fora do envelope) e é gravado em uma **coluna `traceparent` do outbox**, para o Manager e o Publisher, que são processos diferentes, não o perderem.
- **Código compartilhado.** `schemas/observability/python/logging_config.py` (sincronizado nos 18 componentes pelo `sync.py`, decisão 0046) ganha `bind_traceparent`, `current_traceparent` e `TRACEPARENT_HEADER`: um `ContextVar` com validação estrita (versão `00`, minúsculas, ids não nulos; senão, descarta) e o `JsonFormatter` passa a emitir `trace_id` e `trace_flags`. `span_id` não é emitido (não há span).
- **Fluxo:** Receiver (middleware ASGI puro) → NATS → Manager (consome, grava o outbox com o contexto) → Publisher (lê a coluna, publica o header) → Reconciler (guarda o contexto no `desired` e aplica à `action`) → Executor (repassa ao `completed`/`failed`) → Manager → Publisher. O consumidor associa o contexto à mensagem em tratamento e o **limpa em `finally`**.
- **Observer não propaga:** as observações são periódicas e não nascem de um pedido; começam sem contexto.
- **Eventos de log por unidade de trabalho** (`request published`, `message handled`, `outbox message published`, no Executor `action handled` e no Reconciler `action published`), porque os componentes quase não logam no fluxo normal e o `trace_id` ficaria invisível.
- **Migração aditiva** `…-<tipo>-outbox-traceparent.sql` em cada módulo (`ADD COLUMN IF NOT EXISTS`, com `CHECK` do formato). As permissões existentes (INSERT do Manager, SELECT do Publisher na tabela) já cobrem a coluna nova.

## Justificativa

- **Segurança:** o contexto vem só do gateway (a borda descarta o do cliente, decisão 0054); o valor é validado antes de ser repassado ou registrado; nada de dado pessoal novo.
- **Simplicidade:** nenhuma dependência nova; uma mudança pequena e igual em todos os componentes.
- **Robustez:** o contexto sobrevive à queda entre Manager e Publisher (está no outbox) e ao Reconciler, que decide em outro momento (está no estado).
- **Alternativa descartada, por ora:** o SDK do OpenTelemetry com spans. Dá a duração por hop, mas exige uma dependência em 18 componentes; fica para a fase 2, com a aprovação do §21.

## Verificação (2026-10-18)

- Testes unitários novos e existentes em todos os componentes (Receiver, Manager, Publisher, Reconciler, Executor): validação do formato, limpeza do contexto, header NATS e herança do `desired` pela `action`. Ruff, pyright e pytest verdes nos 18.
- Jornada com a CLI real 12 de 12; e2e do `core/account` 8 (3 puladas), do `ipm/organization` 7 (7 puladas) e do `sum/service` 8 (6 puladas), os mesmos números de antes da mudança.
- Cadastro real: o mesmo `trace_id` do span do gateway apareceu nos logs de Receiver, Manager, Publisher, Reconciler e Executor (inclusive nas chamadas HTTP do Executor ao Zitadel), em menos de 2 s. Um `traceparent` forjado pelo cliente não chegou aos componentes. No `sum` e no `ipm`, uma operação da jornada mostrou o mesmo `trace_id` em todos os papéis.

## Consequências

- Os logs de app passam a trazer `trace_id`/`trace_flags` e podem ser correlacionados aos traces do gateway pelo `trace_id`. O trace ainda tem um só span (o do gateway): não há duração por hop.
- Há um registro a mais por mensagem em cada hop: volume de log maior, ainda pequeno em dev.
- Pendências: a chamada HTTP do Receiver do `sum` ao `ipm` não repassa o `traceparent`; o ciclo de observação não tem trace; o `trace_id` não é gravado no `Operation` do SSOT, então não dá para achá-lo a partir do `operationId` sem os logs.
- Uma linha do outbox criada antes da migração tem `traceparent` nulo: segue sem contexto, sem erro.
