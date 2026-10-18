# 0058 — Evolução aditiva: do simples ao avançado, sem descartar o trabalho

- **Data:** 2026-10-18
- **Status:** Aceita e aplicada ao `AGENTS.md` (§2.6). Complementa as decisões 0056 e 0057.
- **Origem:** pedido do responsável pelo projeto: "mesmo começando mais simples, a decisão deve seguir um caminho de evolução do simples ao avançado; o trabalho deve ser reaproveitado e evoluído, não descartado para começar tudo de novo".

## Contexto

O §2.2 (decisão 0056) pede que cada etapa entregue valor e pergunta se a etapa seguinte aproveita a atual ou a joga fora. Era uma pergunta, não uma regra. Uma etapa pode entregar valor sozinha e, ainda assim, ser um beco sem saída: funciona hoje, mas o passo seguinte exige refazê-la.

## Decisão

- **Nome:** *evolução aditiva*. Cada etapa avançada é construída **sobre** a anterior, e não no lugar dela. Termos próximos na literatura: *walking skeleton*, *tracer bullet* e *evolutionary architecture*; aqui o termo é o do §2.6 do `AGENTS.md`.
- **§2.6 "Caminho de evolução: do simples ao avançado":** ao escolher a solução simples, escolhe-se a que o próximo passo possa **estender**. Toda etapa declara o que **permanece**, o que é **acrescentado** e o que é **substituído** (com motivo, custo e migração, §10 e §31). Contratos, nomes e dados da etapa simples são os da avançada. Uma solução simples que só serve se for descartada é um desvio, não um degrau.
- **Descartar continua legítimo** quando a direção estava errada ou quando o trabalho era um experimento declarado, em `.workspace/` (§23).
- **Limite:** a regra não autoriza construir antes o ponto de extensão ou a flexibilidade hipotética (§6 e §25). O caminho aditivo vem de escolher bem o simples.

## Justificativa

- **Simplicidade:** reaproveitar evita duplicar esforço e mantém uma só linha de evolução.
- **Robustez:** o que já foi verificado (testes, contratos, dados) segue valendo na etapa seguinte.
- **Consistência com o §2.2 e o §2.3:** a etapa simples já entrega valor e já cumpre o piso; a avançada soma, sem refazer.

## Exemplos no trabalho de observabilidade (como aplicar)

| Etapa simples | Etapa avançada | Permanece | Acrescenta | Substitui |
|---|---|---|---|---|
| `trace_id` nos logs (0055) | spans com o SDK do OpenTelemetry | `traceparent` propagado, campo `trace_id`, contrato de log 0045, migrações do outbox | spans e duração por etapa | nada |
| Métricas derivadas dos logs (conector `count`) | métricas emitidas pelos componentes | nomes e atributos das métricas, o pipeline `metrics/app` | emissão no processo, para o que o log não mostra | só a contagem que passar a vir do componente, com os mesmos nomes (migração sem perda) |
| Arquivos com rotação no `telemetry-gateway` | backend persistente | o receptor OTLP, a semconv, o `telemetry-agent` | novo exportador no lugar do `file` | o exportador `file`, trocado por configuração |

## Consequências

- Planos e decisões passam a trazer, por etapa, "o que permanece / o que acrescenta / o que substitui".
- Quando uma etapa simples exigir descarte, isso é declarado antes, com motivo e custo, e não descoberto depois.
