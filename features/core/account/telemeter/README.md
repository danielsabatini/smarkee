# core.account: telemeter

O **telemeter** de `core.account` **processa e grava a telemetria de aplicação** desta feature (logs e spans). Ele existe para que a feature seja dona da sua observabilidade de app: o que recebe, a política que aplica e para onde entrega. Decisão [`0062`](../../../../.decisions/0062-coleta-de-telemetria-em-duas-camadas.md).

Ele **não é um dos seis papéis do loop** (Receiver, Manager, Publisher, Reconciler, Observer e Executor): não participa de nenhum fluxo de negócio e nenhum componente depende dele. É um papel de **observabilidade**, ao lado deles na pasta da feature, com a mesma convenção de nome (pasta `telemeter/`, contêiner `core-account-telemeter`).

## O que ele faz

1. **Recebe** por OTLP (gRPC, porta `4317`, só na rede `internal`) os sinais de **app** de `core.account`. Quem entrega é o **`telemetry-router`**, que roteia os **logs** pelo Resource (`smarkee.module = core` e `smarkee.resource.type = account`) e os **spans** do gateway de borda pelo `apisix.service_name = core-account-receiver`.
2. **Aplica a política de app da feature.** Hoje só os limites de memória e o agrupamento em lotes; é aqui que entram, quando houver necessidade, filtros, redação, amostragem ou métricas derivadas **só desta feature**.
3. **Grava** o resultado. Hoje, arquivos com rotação (10 MB, 3 rotacionados, no máximo 1 dia): `telemeter/logs/` (logs de app) e `telemeter/traces/` (spans das rotas desta feature). Como só chega sinal de app, não há subpasta `app`. Quando houver backend ou fila, a mudança é trocar o exportador deste arquivo.

## O que ele não faz

- **Não lê logs de contêineres** nem usa o socket do Docker: isso é do `telemetry-agent`. Por isso roda **sem privilégios**.
- **Não roteia**: quem decide o destino de cada sinal é o `telemetry-router`.
- **Não recebe telemetria de infra** (banco, messaging, Zitadel, gateway): ela fica no `platform-telemeter`, sem dono.
- **Não é auditoria.** A telemetria pode perder dado (a fila descarta quando cheia, a rotação apaga em cerca de 1 dia). A auditoria é outro produto, alimentado pelos fatos de negócio duráveis.
- **Não separa clientes.** "Por feature" não é "por cliente": a separação por dono é o contexto de negócio dos logs (`user.id`, `smarkee.owner.id`, decisão 0061).

## Onde ele fica na arquitetura

```text
contêineres (Docker)  ou  nós (Kubernetes)
        │  logs JSON, métricas de contêiner
        ▼
telemetry-agent ───────────  LÊ · um por nó · privilégio declarado
        │  OTLP
        ▼
telemetry-router ──────────  ROTEIA · não grava em backend · (spans do APISIX entram aqui também)
        │  logs: por módulo e tipo · spans: por apisix.service_name
        ├──────▶  core-account-telemeter   GRAVA  ─▶  telemeter/logs/  telemeter/traces/   (esta feature)
        ├──────▶  (ipm-organization-telemeter, sum-service-telemeter: quando houver necessidade)
        └──────▶  platform-telemeter       GRAVA  ─▶  infra e o app sem telemeter próprio
```

- **Fila entre o roteador e este telemeter:** o `telemetry-router` envia com fila **em disco** e retry explícitos. Se este telemeter cair (ou o roteador reiniciar durante a queda), nada se perde dentro do limite da fila. Medido em dev: 150 de 150 registros, sem duplicatas, com o telemeter fora do ar por 60 s e o roteador recriado no meio.
- **Se este telemeter não existir** (a feature não foi implantada), o que era dele se perde depois da fila. A plataforma não depende da feature, mas o roteamento aponta para ela.
- **Um trace atravessa features.** O cadastro de uma conta passa também pelo `sum`; os logs de cada feature vão ao telemeter do seu dono (ou ao `platform-telemeter`), e o `trace_id` é a chave para juntá-los.

## Em Kubernetes (stg e prd)

| Dev (Docker) | Kubernetes |
|---|---|
| `telemetry-agent` lê `/var/lib/docker/containers` como root, com o socket do Docker | DaemonSet que lê `/var/log/pods` (CRI) e descobre namespace e pod pela API, sem root nem socket |
| `core-account-telemeter` é um contêiner do compose da feature | Deployment no **namespace da feature**, com NetworkPolicy aceitando só o `telemetry-router`, cota e RBAC próprios |
| `config.yaml` | o **mesmo** `config.yaml` (só recebe e exporta) |

## Arquivos

| Arquivo | Função |
|---|---|
| `config.yaml` | Configuração do OpenTelemetry Collector (distribuição contrib): receptor OTLP, limites, lotes e os exportadores de arquivo (logs e spans) |
| `logs/`, `traces/` | Saída (`*.jsonl` e rotacionados), dado de execução ignorado pelo git; só o `.gitkeep` é versionado. As pastas precisam ser graváveis pelo usuário `10001` (no Linux, `chmod o+rwx telemeter/logs telemeter/traces`; no Docker Desktop já são) |

O serviço está em `../compose.yaml` (`core-account-telemeter`). Limites: `CORE_ACCOUNT_TELEMETER_CPUS` (padrão 0,25) e `CORE_ACCOUNT_TELEMETER_MEMORY` (padrão 192M).

## Como evoluir (decisão 0058: do simples ao avançado, sem descartar)

| Passo | O que acrescenta | O que permanece |
|---|---|---|
| Política própria da feature | processadores neste `config.yaml` | o receptor, o roteamento e o contrato |
| Métricas de app derivadas dos logs | conector `count` neste `config.yaml` | tudo acima |
| Backend ou fila | trocar o exportador de arquivo | o resto |
| Os componentes enviarem OTLP direto (SDK) | o telemeter passa a receber direto dos apps; o agente de nó fica só com a infra | a config do telemeter |
