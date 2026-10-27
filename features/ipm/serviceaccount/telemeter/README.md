# ipm.serviceaccount: telemeter

O **telemeter** de `ipm.serviceaccount` **processa e grava a telemetria de aplicação** desta feature (logs e spans), para que a feature seja dona da sua observabilidade de app. Decisão [`0062`](../../../../.decisions/0062-coleta-de-telemetria-em-duas-camadas.md); a arquitetura inteira, com os diagramas, está em [`OBSERVABILITY-ARCHITECTURE.md`](../../../../docs/telemetry/OBSERVABILITY-ARCHITECTURE.md).

Ele **não é um dos quatro papéis do loop** (Receiver, Manager, Publisher e Controller): nenhum componente depende dele. É um papel de **observabilidade**, ao lado deles na pasta da feature (pasta `telemeter/`, contêiner `ipm-serviceaccount-telemeter`).

## O que ele faz

1. **Recebe** por OTLP (gRPC, porta `4317`, só na rede `internal`) os sinais de **app** de `ipm.serviceaccount`, que o **`telemetry-router`** entrega: os **logs** pelo Resource (`smarkee.module = ipm` e `smarkee.resource.type = user`) e os **spans** do gateway de borda pelo `apisix.service_name = ipm-serviceaccount-receiver`.
2. **Aplica a política de app da feature** (hoje só os limites de memória e o agrupamento em lotes).
3. **Grava**, até haver backend, em arquivos com rotação (10 MB, 3 rotacionados, no máximo 1 dia): `telemeter/logs/` e `telemeter/traces/`. Como só chega sinal de app, não há subpasta `app`.

## O que ele não faz

- **Não lê** logs de contêineres nem usa o socket do Docker (isso é do `telemetry-agent`): roda **sem privilégios**.
- **Não roteia** (isso é do `telemetry-router`) e **não recebe infra** (isso é do `platform-telemeter`).
- **Não é auditoria** (a telemetria pode perder dado) e **não separa clientes** (a separação por dono é o contexto de negócio dos logs, decisão 0061).

## Arquivos

| Arquivo | Função |
|---|---|
| `config.yaml` | Configuração do OpenTelemetry Collector (contrib). **Idêntica à dos telemeters das outras features**; o teste `tests/telemetry` falha se divergirem |
| `logs/`, `traces/` | Saída (`*.jsonl` e rotacionados), dado de execução ignorado pelo git; só o `.gitkeep` é versionado. Precisam ser graváveis pelo usuário `10001` (no Linux, `chmod o+rwx telemeter/logs telemeter/traces`) |

O serviço está em `../compose.yaml` (`ipm-serviceaccount-telemeter`). Limites: `IPM_SERVICEACCOUNT_TELEMETER_CPUS` (padrão 0,25) e `IPM_SERVICEACCOUNT_TELEMETER_MEMORY` (padrão 192M). Se ele cair, o `telemetry-router` guarda os sinais em fila em disco e reenvia; se ele não existir, o que era dele se perde depois da fila. Ao recriá-lo, reinicie o roteador (cache de DNS). O mapeamento para Kubernetes e a evolução (política própria, métricas derivadas, backend, SDK) estão em [`core/account/telemeter/README.md`](../../../core/account/telemeter/README.md) e no documento de arquitetura.
