# 0062 — Coleta de telemetria: agente lê, roteador roteia, telemeters gravam

- **Data:** 2026-10-19
- **Status:** Aceita; **implementada nas três features** (`core/account`, `ipm/organization` e `sum/service`, cada uma com `features/<módulo>/<tipo>/telemeter`); uma feature nova sem telemeter cai no `platform-telemeter`. Estende as decisões 0050, 0051, 0053, 0059 e 0061.
- **Origem:** proposta do responsável: cada feature ter o seu coletor para os logs, métricas e traces dos seus contêineres de aplicação, separado do coletor de infra; o roteamento por rota dos traces; e um roteador que só roteia.

## Contexto

O `telemetry-agent` e o `telemetry-gateway` atendiam infra e apps juntos, separados só por pasta de saída; o `telemetry-gateway` ainda acumulava três funções (entrada, roteamento e gravação). As features são autônomas por papel (decisão 0015), mas a observabilidade de app de todas caía no mesmo lugar, com a mesma política. Pelas medições de 2026-10-18, a telemetria da plataforma também não separa dono, e o agente é a única peça privilegiada (root e socket do Docker, lacuna de dev declarada). Além disso, "gateway" já designa o APISIX neste repositório, e "collector" é o termo genérico do binário de todas as peças.

## Decisão

- **Quatro peças, um verbo cada** (todas são o OpenTelemetry Collector contrib, com configs diferentes; o nome diz o papel):

  | Peça | Papel |
  |---|---|
  | **`telemetry-agent`** | **lê** os dados (Docker em dev, nós do Kubernetes em stg e prd) e os envia ao roteador; é a única peça privilegiada |
  | **`telemetry-router`** | **roteia** cada sinal ao telemeter dono e **não grava em nenhum backend** |
  | **`platform-telemeter`** | **processa e grava** a **infra** (sem dono) e o app que nenhum telemeter de feature reivindica |
  | **`<módulo>-<tipo>-telemeter`** | **processa e grava** os sinais de **app** de uma feature, sem privilégios; **não é papel do loop** |

- **Nomes** (escolhidos pelo responsável): `telemeter` para quem grava, por dono (cada feature e a plataforma); `telemetry-router` substitui o antigo `telemetry-gateway`, cujo nome colidia com o gateway de API (APISIX). A suíte de conformidade passa a morar em **`tests/telemetry`**, ao lado de `tests/e2e`: é teste black-box que cruza gateway, features e infra, e `scripts/` guarda ferramentas de operação (não testes).
- **O agente não conhece as features.** O roteador usa o conector `routing` e o que os sinais já trazem: **logs** pelo Resource (`smarkee.module` e `smarkee.resource.type`, contrato 0045); **spans** pelo atributo `apisix.service_name` (o ADC define um serviço por feature). As **métricas** vão todas ao `platform-telemeter` (as de contêiner são de infra). O que não casa vai ao `platform-telemeter`. O APISIX **não** muda: o endereço do coletor do plugin `opentelemetry` é global (metadado do plugin) e não por rota, então o roteamento por rota é feito no roteador.
- **A normalização dos spans** à semconv (decisão 0050) acontece no roteador, antes de rotear, para cada telemeter receber o span conforme.
- **Leitura e processamento separados.** Um agente completo por feature multiplicaria o leitor privilegiado (no Docker, cada um leria os logs de todos os contêineres; no Kubernetes, o `hostPath` dos logs do nó não se restringe por namespace). O telemeter só recebe OTLP.
- **Nomeação e lugar do telemeter da feature:** pasta `features/<módulo>/<tipo>/telemeter/` e contêiner `<módulo>-<tipo>-telemeter`, definido no `compose.yaml` da feature, como os papéis. Saída em `telemeter/logs/` e `telemeter/traces/` (só sinal de app, então sem subpasta `app`).
- **Filas:** `sending_queue` em disco (`file_storage`) e `retry_on_failure` explícitos do agente ao roteador (decisão 0059) e do roteador a cada telemeter. Cheia, descarta o dado novo sem bloquear; telemeter ausente, perde o que era dele depois da fila.
- **Auditor:** fora desta decisão. Não é um coletor: a auditoria vem de fatos de negócio duráveis (outbox e NATS), e não da leitura de logs.

## Justificativa

- **Segurança:** o leitor privilegiado continua único e declarado; o roteador e os telemeters rodam sem privilégios (`cap_drop: ALL`, `no-new-privileges`) e sem acesso a arquivos de outros contêineres.
- **Simplicidade e evolução aditiva (§2.6):** reaproveita o agente, o contrato e a semconv; o que era o `telemetry-gateway` foi **dividido** (a parte que roteia virou o roteador, a que grava virou o `platform-telemeter`), sem descartar nenhuma configuração. O custo é um contêiner a mais (cerca de 55 MiB) e um salto.
- **Responsabilidade única (§26):** cada peça tem um verbo; o roteador fica trivial e todo destino é um telemeter, sem exceção.
- **Robustez e resiliência:** o raio de explosão por feature é menor; as filas em disco cobrem a queda de um telemeter e o reinício do roteador.
- **Portabilidade:** as configs do roteador e dos telemeters valem igual em Docker e em Kubernetes; só o agente muda (DaemonSet), e cada telemeter vira um Deployment no namespace da feature, com NetworkPolicy, cota e RBAC próprios.

## Verificação (2026-10-19)

- Todas as configs validadas pelo próprio coletor (`otelcol validate`), com controle negativo (uma config quebrada falha).
- **Roteamento verificado nos três sinais:** os logs dos seis papéis de `core/account` e o span da rota `core-account-receiver` foram para o `core-account-telemeter`; os logs de `sum`, os spans de `ipm` e a infra (logs e métricas) ficaram no `platform-telemeter`; nenhum sinal de `core-account` caiu no `platform-telemeter` e nenhum de outra feature chegou ao `core-account-telemeter`.
- **Resiliência nos dois caminhos de uma vez** (app de `core` e infra): 150 registros sintéticos de cada, com os dois telemeters fora do ar por 60 s e o roteador recriado no meio da queda: **150 de 150, sem duplicatas**, nos dois.
- Suíte `tests/telemetry`: 9 testes (incluindo os de roteamento de logs e de spans).

## Consequências

- **Um trace atravessa features:** o cadastro de uma conta passa também pelo `sum`; os logs de cada feature vão ao telemeter do seu dono (ou ao `platform-telemeter`), e o `trace_id` os junta. A suíte `tests/telemetry` lê as duas fontes.
- **Telemeter ausente = perda:** a plataforma não depende da feature, mas o roteamento aponta para ela; em stg e prd o Deployment e a NetworkPolicy do telemeter fazem parte da implantação da feature.
- **Lacuna de dev declarada:** o OTLP entre as peças não tem TLS nem autenticação (condição de saída em `IMPLEMENTATION-STATUS.md`).
- **Cuidados operacionais** (já no README da infra): recriar um telemeter muda o IP dele e o roteador pode usar o antigo até o cache de DNS expirar (reiniciar o roteador resolve); a fila em disco do roteador usa um arquivo com trava, então **não** se deve manter dois contêineres na mesma pasta `data/`.
- **Renomeações:** as decisões 0050, 0051, 0053, 0058 e 0059 usam o nome antigo `telemetry-gateway` (hoje `telemetry-router` para o roteamento e `platform-telemeter` para a gravação) e os caminhos antigos (`infrastructure/dev/telemetry-gateway/...`, `.../conformance`). São registro histórico e não foram reescritas.
- **Hoje o telemeter da feature faz pouco** (limites e lotes, sobre logs e spans): o valor atual é a separação e a prova do desenho. Os passos seguintes (política da feature, métricas derivadas dos logs, backend ou fila, SDK) estão no README dele.
