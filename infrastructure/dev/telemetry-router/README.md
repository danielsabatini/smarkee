# telemetry-router

O **telemetry-router** **roteia** cada sinal de telemetria ao telemeter que o grava e **não grava em nenhum backend**. Decisão [`0062`](../../../.decisions/0062-coleta-de-telemetria-em-duas-camadas.md).

## Função

1. **Recebe** OTLP: gRPC (`4317`) do `telemetry-agent` e HTTP (`4318`) do plugin `opentelemetry` do APISIX, só na rede `internal`.
2. **Normaliza os spans do APISIX** à semconv (`gateway-semconv.yaml`, decisão 0050) **antes** de rotear, para cada telemeter receber o span conforme (e a query redigida).
3. **Roteia** cada sinal ao telemeter dono:
   - **logs**: pelo Resource (`smarkee.module` e `smarkee.resource.type`, contrato 0045);
   - **spans**: pelo atributo `apisix.service_name` (o ADC define um serviço por feature);
   - **métricas**: todas ao `platform-telemeter` (as de contêiner são de infra).
   O que não casa com nenhuma feature com telemeter próprio vai ao `platform-telemeter`.
4. **Envia** por OTLP gRPC, com **fila em disco** (`data/`) e retry explícitos por destino.

## O que ele não faz

- **Não grava** em arquivo nem em backend: quem grava são os telemeters.
- **Não lê** logs de contêineres: isso é do `telemetry-agent`.
- Não conhece o negócio: só usa o que os sinais já trazem.

## Como acrescentar uma feature com telemeter

Em `config.yaml`: uma linha na tabela de `routing/logs` e de `routing/traces`, uma pipeline por sinal e um exportador `otlp_grpc/<feature>`; e o serviço `<módulo>-<tipo>-telemeter` no `compose.yaml` da feature. Nada muda nos apps nem no agente.

## Fila e falhas

Cada destino tem `sending_queue` em disco (1000 lotes, sem bloquear quando cheia) e `retry_on_failure` até 10 minutos. Se o roteador reiniciar durante a queda de um telemeter, a fila persiste. Telemeter ausente: o que era dele se perde depois da fila. Medido em dev: 150 de 150 registros, sem duplicatas, nos dois caminhos.

## Arquivos

| Arquivo | Função |
|---|---|
| `config.yaml` | receptores, roteamento (`routing/logs`, `routing/traces`), exportadores e pipelines |
| `gateway-semconv.yaml` | processador que ajusta os spans do APISIX à semconv (mesclado na linha de comando) |
| `data/` | fila em disco (estado de execução, ignorado pelo git). Precisa ser gravável pelo usuário `10001` (no Linux, `chmod o+rwx data`) |

Limites: `SMARKEE_TELEMETRY_ROUTER_CPUS` (0,5) e `SMARKEE_TELEMETRY_ROUTER_MEMORY` (256M). Cuidado: ao recriar um telemeter, o IP muda e o roteador pode usar o antigo até o cache de DNS expirar; reiniciar o roteador resolve.
