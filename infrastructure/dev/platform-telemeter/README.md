# platform-telemeter

O **platform-telemeter** **processa e grava** a telemetria que **não é de nenhuma feature com telemeter próprio**: a **infra** (banco, messaging, Zitadel, gateway, mail e os próprios coletores) e o **app** das features que ainda não têm telemeter. Decisão [`0062`](../../../.decisions/0062-coleta-de-telemetria-em-duas-camadas.md).

## Função

1. **Recebe** OTLP gRPC (`4317`) do `telemetry-router`, só na rede `internal`.
2. **Separa infra de app** (decisão 0053): log de **app** é o que traz `smarkee.component.role`; métrica de **infra** é a de prefixo `container.`, `system.`, `process.` ou `k8s.`; o resto é de app.
3. **Grava**, até haver backend, em arquivos com rotação (10 MB, 3 rotacionados, no máximo 1 dia): `logs/{app,infra}/`, `metrics/{app,infra}/` e `traces/`.

## O que ele não faz

- **Não lê** logs de contêineres (isso é do `telemetry-agent`) e **não roteia** (isso é do `telemetry-router`).
- **Não recebe** os sinais de app das features que têm telemeter próprio (hoje `core/account`).
- **Não é multitenant** nem é exposto a clientes: é telemetria de **operador**.

## Arquivos

| Arquivo | Função |
|---|---|
| `config.yaml` | receptor OTLP, filtros infra x app, exportadores de arquivo e pipelines |
| `logs/`, `metrics/`, `traces/` | saída (dado de execução, ignorado pelo git; só o `.gitkeep` é versionado). Precisam ser graváveis pelo usuário `10001` (no Linux, `chmod -R o+rwx logs metrics traces`) |

Limites: `PLATFORM_TELEMETER_CPUS` (0,5) e `PLATFORM_TELEMETER_MEMORY` (384M). Para ver o que chega: `tail -f logs/app/logs.jsonl`.
