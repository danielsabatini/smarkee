# ipm.group: telemeter

O **telemeter** de `ipm.group` **processa e grava a telemetria de aplicação** desta feature (logs e spans), para que a feature seja dona da sua observabilidade de app. Decisão [`0062`](../../../../.decisions/0062-coleta-de-telemetria-em-duas-camadas.md); a arquitetura inteira, com os diagramas, está em [`OBSERVABILITY-ARCHITECTURE.md`](../../../../docs/OBSERVABILITY-ARCHITECTURE.md).

Ele **não é um dos seis papéis do loop** (Receiver, Manager, Publisher, Reconciler, Observer e Executor): nenhum componente depende dele. É um papel de **observabilidade**, ao lado deles na pasta da feature (pasta `telemeter/`, contêiner `ipm-group-telemeter`).

## O que ele faz

1. **Recebe** por OTLP (gRPC, porta `4317`, só na rede `internal`) os sinais de **app** de `ipm.group`, que o **`telemetry-router`** entrega: os **logs** pelo Resource (`smarkee.module = ipm` e `smarkee.resource.type = group`) e os **spans** do gateway de borda pelo `apisix.service_name = ipm-group-receiver`.
2. **Aplica a política de app da feature** (hoje só os limites de memória e o agrupamento em lotes).
3. **Grava**, até haver backend, em arquivos com rotação na própria pasta (`logs/current.jsonl` e `traces/current.jsonl`, ignorados pelo git). Quando houver backend, só a seção `exporters:` de `collector.yaml` muda.

## Por que os logs já chegam prontos

Os seis papéis de `ipm.group` emitem cada linha de log em JSON com `smarkee.*` no topo (`common/logging_config.py`); o **`telemetry-agent`** da plataforma faz o parse desse JSON na coleta, move `smarkee.module`, `smarkee.resource.type`, `smarkee.role` e `service.name` para o **Resource**, preenche `trace_id`, `span_id` e `severity` e entrega tudo ao **`telemetry-router`**. Aqui o sinal já chega estruturado.
