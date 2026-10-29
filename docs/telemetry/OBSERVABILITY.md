# Observabilidade

> **Arquitetura de coleta** (peças, roteamento, filas, Kubernetes): [`OBSERVABILITY-ARCHITECTURE.md`](OBSERVABILITY-ARCHITECTURE.md).
>
> **Escopo:** contrato de **logs** emitidos pelos componentes da plataforma (`features/*`) e, na seção 11, o **span do gateway**. Métricas, traces dos componentes e auditoria ainda não estão definidos aqui.
>
> **Papel:** fonte de verdade do formato, dos campos e das proibições dos logs. O contrato executável é o schema [`schemas/observability/log-record.v1.schema.json`](../../schemas/observability/log-record.v1.schema.json). As decisões que o originaram são a [`0045`](../../.decisions/0045-contrato-de-logs-opentelemetry.md) e a [`0046`](../../.decisions/0046-codigo-identico-gerado-de-fonte-unica.md). A segurança do que pode ou não ser registrado vem de [`RESOURCE-CONTROL-SECURITY.md`](../loop/RESOURCE-CONTROL-SECURITY.md) (§13) e de [`SCHEMA.md`](../data/SCHEMA.md) (`sensitivity`).
>
> **Status:** todas as 9 features (`core.account`, `bsm.account`, `sum.service` e `ipm.{organization,user,serviceaccount,permission,role,group}`) seguem o contrato. Em dev a coleta roda em Kubernetes via `OpenTelemetry Operator` (seção 7, [`OBSERVABILITY-ARCHITECTURE.md`](OBSERVABILITY-ARCHITECTURE.md) e decisão [`0102`](../../.decisions/0102-kubernetes-kind-argocd-vault-e-operadores.md): `telemetry-agent` DaemonSet → `telemetry-router` → `telemetry-sink` e `<módulo>-<tipo>-telemeter`), gravando em arquivos com rotação (10 MB), separados em infra e app (ver [`IMPLEMENTATION-STATUS.md`](../platform/IMPLEMENTATION-STATUS.md)).

# 1. Princípio

Todo log da plataforma representa um **LogRecord do OpenTelemetry** ([Logs Data Model](https://opentelemetry.io/docs/specs/otel/logs/data-model/), estável), com atributos nomeados pelas [convenções semânticas](https://opentelemetry.io/docs/specs/semconv/). Um único formato vale para todos os componentes, de todos os módulos e papéis.

O componente escreve **uma linha JSON por registro no stdout**. Não usa o SDK de logs do OpenTelemetry para Python (em desenvolvimento) e não envia o log a nenhum destino: quem lê o stdout e entrega ao destino é o coletor (seção 7).

A linha é a representação, em JSON, dos campos do LogRecord. A conversão para o LogRecord é mecânica e feita pelo coletor.

# 2. Linha de log

```json
{
  "timestamp": "2026-10-16T14:03:22.123456Z",
  "severity_number": 17,
  "severity_text": "ERROR",
  "body": "task failed",
  "event_name": "smarkee.task.failed",
  "scope": {"name": "core_account_controller.main"},
  "resource": {
    "service.name": "core-account-controller",
    "service.namespace": "smarkee",
    "service.version": "0.1.0",
    "service.instance.id": "0199c8b2-6f0e-7a31-9d0c-1f6b5c2a8e44",
    "deployment.environment.name": "development",
    "smarkee.module": "core",
    "smarkee.resource.type": "account",
    "smarkee.component.role": "manager"
  },
  "attributes": {
    "error.type": "ConnectionError",
    "exception.type": "ConnectionError",
    "code.file.path": "core_account_controller/transport/messaging.py",
    "code.line.number": 88,
    "code.function.name": "core_account_controller.transport.nats.connect",
    "smarkee.task.name": "consumer"
  }
}
```

| Campo da linha | Campo do LogRecord | Regra |
|---|---|---|
| `timestamp` | `Timestamp` | Instante do evento, RFC 3339 em UTC, com `Z` e microssegundos. |
| (ausente) | `ObservedTimestamp` | Definido pelo coletor ao observar a linha. O componente não o emite. |
| `severity_number` | `SeverityNumber` | Conforme a seção 3. |
| `severity_text` | `SeverityText` | Conforme a seção 3. |
| `body` | `Body` | Texto **estável**, em inglês, sem valores variáveis (nada de interpolação). O que varia vai em `attributes`. |
| `event_name` | `EventName` | Opcional. Presente quando o registro é uma ocorrência nomeada. Formato `smarkee.<assunto>.<ocorrência>`, minúsculas, sem valores dinâmicos. |
| `trace_id`, `span_id`, `trace_flags` | `TraceId`, `SpanId`, `TraceFlags` | Opcionais. Os componentes emitem `trace_id` e `trace_flags` quando a requisição ou a mensagem em tratamento traz um `traceparent` (seção 12, decisão 0055); **não** emitem `span_id`, pois não criam spans. `span_id` só com `trace_id`. |
| `scope.name` | `InstrumentationScope` | Nome do logger. |
| `resource` | `Resource` | Seção 4. Idêntico em todas as linhas do processo. |
| `attributes` | `Attributes` | Seção 5. Chaves em inglês, em minúsculas, com pontos. |

Campos opcionais sem valor são **omitidos**, e não gravados como `null`.

# 3. Severidade

| Nível Python | `severity_number` | `severity_text` |
|---|---|---|
| `DEBUG` | 5 | `DEBUG` |
| `INFO` | 9 | `INFO` |
| `WARNING` | 13 | `WARN` |
| `ERROR` | 17 | `ERROR` |
| `CRITICAL` | 21 | `FATAL` |

`ERROR` ou superior indica falha. Uma exceção esperada e tratada (por exemplo, uma mensagem inválida descartada de propósito) é `WARN`, e não `ERROR`.

**Nível configurável por processo** (decisão 0078): a seção `log` de todo papel tem `level` (padrão `INFO`), para o código do próprio papel, e `dependencies_level` (padrão `WARNING`), para as bibliotecas (`httpx`, `httpcore`, `uvicorn`, `nats`, `psycopg`, `asyncio`). Com o padrão, o `HTTP Request: ...` de cada chamada do cliente HTTP não aparece. Os dois seguem a precedência de toda configuração (decisão 0067): por exemplo, `SUM_SERVICE_OBSERVER_LOG_LEVEL=DEBUG` no ambiente, `[tool.sum.service.observer.log] level = "DEBUG"` no `config.toml` ou `--log.level DEBUG` na linha de comando. Na partida, cada papel registra `configuration loaded`, com o resumo de cada seção da configuração sem os segredos (`smarkee.config.digest`): a mesma seção com resumos diferentes em papéis da mesma feature indica configuração divergente.

# 4. Resource: quem emitiu

Atributos do componente, fixos durante o processo. Vêm de configuração explícita, nunca de opção de linha de comando.

| Atributo | Valor | Origem |
|---|---|---|
| `service.name` | `<módulo>-<tipo>-<papel>` (por exemplo, `core-account-controller`) | Derivado do nome do pacote Python (`<módulo>_<tipo>_<papel>`), o que mantém o arquivo idêntico em todos os componentes. |
| `service.namespace` | `smarkee` | Fixo. |
| `service.version` | Versão do pacote do componente | Metadados do pacote; omitido se o pacote não estiver instalado. |
| `service.instance.id` | UUID gerado na partida | Gerado no processo. |
| `deployment.environment.name` | `development`, `staging` ou `production` | Variável `SMARKEE_ENVIRONMENT` com `dev`, `stg` ou `prd` (valores *well-known* da semconv). Ausente ou desconhecida: o atributo é omitido. O Compose de cada feature define `dev` por padrão. |
| `smarkee.module`, `smarkee.resource.type`, `smarkee.component.role` | `core`, `account`, `manager` | Fixo no componente (cada projeto trata um só tipo de recurso). |

Atributos de infraestrutura (`k8s.*`, `container.*`, `host.*`) são acrescentados **pelo coletor**, e não pelo componente.

# 5. Atributos

## 5.1 Da semconv

| Atributo | Uso |
|---|---|
| `error.type` | Classe do erro quando o registro descreve uma falha. Nome qualificado pelo módulo (`<módulo>.<Classe>`), exceto nas classes *builtin* (`ValueError`). Baixa cardinalidade. |
| `exception.type` | Classe da exceção capturada, no mesmo formato. |
| `code.file.path`, `code.line.number`, `code.function.name` | Local onde a exceção foi levantada (último quadro da pilha). |
| `user.id` | O ator autenticado (o solicitante, `requestedBy`): identificador opaco e pseudonimizado, nunca e-mail nem nome; o schema valida o formato. Vem do **contexto de negócio** (seção 13). Quem não é autenticado não tem `user.id`. |
| `messaging.system` | `nats` (valor próprio: a semconv não define um valor para NATS). |
| `messaging.destination.name` | Subject, quando o registro é de uma mensagem. |
| `messaging.message.id` | `messageId` do envelope. |
| `messaging.consumer.group.name` | Nome do consumer durável do JetStream. |

O código de produção **não** monta `error.type`, `exception.type` e `code.*` à mão: ao registrar uma exceção, passa `exc_info=error` ao logger, e o formatter emite os quatro atributos sem a mensagem nem a pilha.

Os atributos `messaging.*` e `user.*` estão em estágio *development* na semconv; podem ser renomeados. A revisão da versão da semconv é uma tarefa explícita (seção 9).

## 5.2 Próprios da plataforma

Tudo o que a semconv não cobre usa o prefixo `smarkee.`.

| Atributo | Significado |
|---|---|
| `smarkee.resource.id` | `resourceId` do recurso tratado. Vem do contexto de negócio (seção 13) quando o evento não o informa. |
| `smarkee.organization.id` | Identificador da Organization: no `ipm.organization` é o próprio `resourceId`. Omitido quando o recurso não é uma Organization. |
| `smarkee.owner.id` | Dono do recurso (`ownerAccountId`), quando a mensagem o traz. Omitido nos demais. |
| `smarkee.actor.type` | Tipo do ator: `user`, `anonymous`, `service` ou `system`. Baixa cardinalidade; é o único dado do ator permitido em métrica (seção 13). |
| `smarkee.correlation.id` | `correlationId` do envelope. |
| `smarkee.causation.id` | `causationId` do envelope. |
| `smarkee.operation.id` | `operationId`. |
| `smarkee.action.id` | `actionId`. |
| `smarkee.task.name` | Tarefa interna do processo (consumer, servidor de saúde, publicação). |
| `smarkee.outcome` | Desfecho curto e de baixa cardinalidade (por exemplo, `accepted`, `rejected`). |
| `smarkee.reason` | Motivo de um desfecho ou de uma rejeição. Só texto de erro de **domínio próprio**, construído sem valores (nomes de campos, nome da operação); nunca `str(error)` de uma biblioteca (seção 6). |
| `smarkee.operation.name` | Operação do recurso (`create`, `update`, `delete`) ou, nas mensagens de estado e fatos, a operação do envelope (por exemplo, `changed`). |
| `smarkee.observation.presence` | `presence` da observação (`present`, `absent`, `unknown`). |
| `smarkee.result.type` | Tipo do resultado tratado (`completed`, `failed`). |
| `smarkee.desired.generation` | Geração do `desired`. |
| `smarkee.delivery.attempt` | Tentativa de entrega ou de processamento (a partir de 1). |
| `smarkee.partition`, `smarkee.partition.count` | Partição do processo (`índice/total`) e total de partições. |
| `smarkee.instance.name` | Nome da instância de Observer ou Reconciler (estado em memória). |
| `smarkee.outbox.sequence`, `smarkee.failure.permanent` | Linha do outbox e se a falha de publicação é permanente. |
| `smarkee.account.id`, `smarkee.links.removed` | Conta removida e quantidade de ligações apagadas (`sum.service`). |
| `smarkee.links.changed` | Ligações que ganharam uma geração nova no rollout do catálogo (`sum.service`, decisão 0079). |
| `smarkee.config.missing_variables` | Nomes (nunca valores) das variáveis obrigatórias ausentes. |
| `smarkee.drift.fields` | Nomes (nunca valores) dos campos gerenciados em que o `observed` diverge do `desired`, na decisão do Reconciler (decisão 0078). |
| `smarkee.action.ineffective_count` | Ações seguidas da geração atual que concluíram sem a observação causada convergir (decisão 0078). |
| `smarkee.progress.deadline_seconds` | Prazo de progresso da geração (`progressDeadline`), no aviso de prazo esgotado (decisão 0078). |
| `smarkee.config.digest` | Resumo (SHA-256, 12 caracteres) da configuração do papel sem os segredos, no log de partida: papéis da mesma feature com digests diferentes rodam com configurações diferentes (decisão 0078). |

Um atributo novo segue a mesma regra: prefixo `smarkee.`, em inglês, sem colidir com a semconv, e sem tipo ou significado genérico (`AGENTS.md` §15).

# 6. Proibido

- **Mensagem de exceção** (`exception.message`) e `str(error)` de exceção de biblioteca ou de driver. Ela pode conter valores de colunas (a violação de unicidade, por exemplo, traz o e-mail). Só o tipo e o local são registrados. A única exceção é o texto das exceções de domínio do próprio projeto (`PermanentMessageError`, `CatalogError`), escrito sem valores, que pode ir em `smarkee.reason`; ao criar uma exceção de domínio nova, mantenha essa propriedade. Na semconv, `exception.message` é exigido apenas quando `exception.type` não está definido; como `exception.type` é sempre emitido, a regra é compatível.
- **Pilha de chamadas completa** (`exception.stacktrace`). A forma textual da pilha termina com a mensagem da exceção; por isso ela não é emitida. O local do último quadro (`code.*`) cobre o diagnóstico. Reavaliar apenas com uma pilha montada sem a mensagem.
- Campo `confidential` de qualquer contrato (`SCHEMA.md`), segredo, credencial e token, em qualquer atributo ou no `body`.
- Dado pessoal em `body` e em atributos de identificação. Identificadores opacos (`resourceId`, `requestedBy`) são permitidos; e-mail, nome e sobrenome, não.
- Valor variável no `body`.

# 7. Coleta

```text
componente → stdout (JSON) → runtime do contêiner → coletor → destino
```

- O stdout é capturado pelo runtime do contêiner (`containerd`). **Alguém precisa lê-lo**: no cluster Kubernetes (`kind` em dev, e também em stg e prd — decisão [`0102`](../../.decisions/0102-kubernetes-kind-argocd-vault-e-operadores.md)), o `telemetry-agent` gerenciado pelo `OpenTelemetry Operator` em modo `DaemonSet` lê `/var/log/pods/*/*/*.log` (formato CRI `containerd`) com o `filelog receiver` e `kubectl logs` continua valendo.
- O coletor interpreta a linha (JSON), converte `timestamp`, `severity_*`, `trace_id` e `span_id` para os campos do LogRecord, move `resource` e `attributes` para seus lugares e define `ObservedTimestamp`.
- O componente nunca depende do coletor nem do destino: se eles caírem, o log continua no stdout.
- **Coleta em Kubernetes verificada em 2026-10-29** (`OpenTelemetry Operator` `v0.162.0`, Collector `otel/opentelemetry-collector-contrib:0.164.0`, `infrastructure/k8s/platform/telemetry/base/telemetry-agent.yaml`, suíte `tests/telemetry` 20/20):
  - `filelog/app` lê `/var/log/pods/*/*/*.log` usando o operador `container` (`format: containerd`, `add_metadata_from_filepath: true`), `router` descartando linhas que não começam com `{`, `json_parser` (`parse_ints: true`, `on_error: drop_quiet`) com `timestamp` (`%Y-%m-%dT%H:%M:%S.%fZ`), `severity` (`severity_text`), `trace_id`, `span_id` e `trace_flags`, e `move` das 8 chaves de `resource` e de `scope.name` no próprio `filelog`;
  - `filelog/infra` lê os logs dos namespaces de infraestrutura (`database`, `messaging`, `identity`, `gateway`, `mail`, `telemetry`, `vault`), atribui `service.name` pelo namespace, extrai severidade (logfmt/JSON, NATS, PostgreSQL, nginx, Collector), retém apenas `WARN` ou superior e aplica redação de dados sensíveis (`missing translation` e `<redacted-email>`);
  - Além dos logs, o `telemetry-agent` coleta métricas de infraestrutura: nós e pods (`kubeletstats`, sem `docker.sock`), banco de dados (`postgresql` e `sql_query/outbox` com o papel `telemetry_login`, `pg_read_all_stats` e `telemetry.outbox_stats()`, sem acesso aos dados das tabelas), identidade (`prometheus/infra` em `identity.identity.svc.cluster.local:8080/debug/metrics`) e mensageria (`prometheus/infra` em `messaging.messaging.svc.cluster.local:7777/metrics`), normalizadas à semconv em `transform/infra_metrics`.
  - **Fila e retry do agente ao `telemetry-router` (decisão 0059):** explícitos. A fila fica em disco (`sending_queue.storage: file_storage`, 1000 lotes, sem bloquear a leitura quando cheia) e o retry vai até 10 minutos.
  - **Para onde vai (decisões 0062 e 0102):** o agente envia tudo ao `telemetry-router`, que **só roteia** (não grava em backend): os logs de **app** vão pelo Resource (módulo e tipo) e os spans por `apisix.service_name` ao telemeter dono (`<módulo>-<tipo>-telemeter`); todo o resto vai ao `telemetry-sink`, que é o destino da plataforma. Ver [`OBSERVABILITY-ARCHITECTURE.md`](OBSERVABILITY-ARCHITECTURE.md).
  - **Healthchecks** (`/health/*`, `/healthz`, `/readyz`, `/livez` e o healthcheck da Admin API do APISIX) são descartados no agente.
- O destino (armazenamento, consulta, retenção) não faz parte deste documento.

# 8. Conformidade

- Cada feature mantém o seu próprio `common/logging_config.py` (decisões [`0015`](../../.decisions/0015-componentes-por-papel-autocontidos.md) e 0063): não há biblioteca de log compartilhada. As cópias são **idênticas** (a identidade vem do nome do pacote), assim como o `tests/common/unit/test_logging.py` de cada feature, exceto pelo nome do pacote.
- **A fonte única** está em `templates/feature/files/`. `python templates/feature/sync.py` regrava as cópias e `--check` as confere (decisão 0046). Alterar o formatter é alterar a fonte, sincronizar e rodar a suíte de cada componente. Um teste em `schemas/tests` falha se uma cópia divergir.
- **O schema da linha** (`schemas/observability/log-record.v1.schema.json`) é o contrato verificável. Ele fecha os atributos aos nomes da semconv listados nele e ao namespace `smarkee.*`, e proíbe `exception.message` e `exception.stacktrace`. Atributo novo da semconv entra no schema, e atributo `smarkee.*` já é aceito pelo padrão.
- O teste de cada componente verifica: que a linha emitida cumpre o schema; o mapeamento de severidade; `EventName`; a omissão de valores nulos; que a mensagem da exceção não aparece; o `Resource` derivado do pacote; e, por análise estática do código-fonte, que **toda chave de `extra` dos loggers é um atributo que o schema aceita** ou `event_name`.
- **Teste de ponta a ponta da telemetria:** `tests/telemetry` (decisão 0059) faz um cadastro pelo gateway e confere nos arquivos: o mesmo `trace_id` do span do gateway em Receiver, Manager, Publisher, Reconciler e Executor; `traceparent` forjado ignorado; spans sem `args`, `http.target` e `url.full` e com `url.query` redigida; logs de infra sem e-mail nem código de verificação; e a redação do agente, por um contêiner sintético.
- A CLI `sk` não emite logs neste formato: o que ela mostra ao usuário é saída de interface, em inglês (decisão `0035`).

# 9. Versão de referência

As páginas oficiais consultadas em 2026-10-16 não exibem um número de versão da semconv; as ligações internas apontam para a versão 1.59.0 da especificação. Na hora de implementar, confirmar nomes e estágios contra a versão vigente e registrar a versão aqui.

# 10. Pendências

- `event_name` ainda não é usado por nenhum componente; definir os eventos nomeados ao precisar deles.
- Confirmar nomes e estágios dos atributos contra a versão vigente da semconv (seção 9).
- Coleta (seção 7): o `WARN` `decrypt access token` do Zitadel acabou com o token opaco das contas de serviço (decisão 0054).
- Métricas de aplicação (`metrics/app` está vazio): definir o que medir (taxa e erro por componente, atraso dos consumers do NATS, duração do loop, tamanho do outbox) e como emitir.
- Traces distribuídos, fase 2: spans de verdade nos componentes (exigiria o SDK do OpenTelemetry em cada um, uma dependência a aprovar), propagar também nas chamadas HTTP entre módulos (a API do `sum` ao `ipm`) e dar um trace próprio à observação periódica.
- Traces do gateway (seção 11): a verificação de conformidade com a semconv (41 regras, feita à mão em 2026-10-17) ainda não é teste versionado; o teste versionado de hoje (`tests/telemetry`) cobre a correlação do `trace_id` e a ausência de dados sensíveis, não as 41 regras.

# 11. Traces do gateway

Decisão [`0050`](../../.decisions/0050-traces-do-gateway-opentelemetry.md). Vale só para o **span de servidor do gateway** (APISIX); os traces dos componentes do loop ainda não estão definidos.

**Caminho:** plugin `opentelemetry` do APISIX → OTLP/HTTP → **`telemetry-router`** (`infrastructure/dev/telemetry-router`, que só roteia; ver [`OBSERVABILITY-ARCHITECTURE.md`](OBSERVABILITY-ARCHITECTURE.md)) → o telemeter dono do span (`core-account-telemeter` para a rota de `core/account`; `telemetry-sink` para as demais) → arquivos (exporter `file`, rotação em 10 MB; ainda não há backend). O plugin é aplicado a todas as rotas por uma regra global (`infrastructure/dev/gateway/bootstrap/adc.yaml`) e o destino vem de `SMARKEE_GATEWAY_TELEMETRY_ADDRESS`. Como o plugin emite nomes depreciados e nomeia atributos pelo nome da variável do nginx, o **roteador ajusta os spans** (antes de rotear) com o processador de [`infrastructure/dev/telemetry-router/gateway-semconv.yaml`](../../infrastructure/dev/telemetry-router/gateway-semconv.yaml), colocado logo depois do `memory_limiter` e antes de qualquer exporter (em outro coletor, antes do service graph e do tail sampling). O processador só age em spans do gateway. As pipelines de métricas e de logs também existem. Cada sinal vai para a sua pasta de `infrastructure/dev/telemetry-sink` (e, para `core/account`, de `features/core/account/telemeter`): `logs/{app,infra}`, `metrics/{app,infra}` e `traces/` (decisão 0053), em arquivos de uma linha OTLP JSON por lote (`jq` lê); o ativo é `<sinal>.jsonl`, e ao chegar a 10 MB é renomeado `<sinal>-<data>-size.jsonl` (ficam 3, por até 1 dia). A separação infra x app é do `telemetry-sink`: **logs de app** são os que trazem `smarkee.component.role` (contrato 0045); os demais, dos contêineres da plataforma, são **infra**. **Métricas de infra** são as de prefixo `container.`, `system.`, `process.`, `k8s.` e `postgresql.`, e as dos serviços da plataforma (`database`, `identity`, `messaging`, `gateway`); as demais, de **app** (hoje só as sintéticas de teste: nenhum componente emite métrica própria ainda). Um registro único maior que 10 MB é rejeitado pelo exporter (erro no log do coletor; o receptor ainda responde 200), por isso o `batch` limita os lotes a 200 itens. Tamanho medido em 2026-10-17: uma rodada completa (jornada com a CLI real e as três suítes de conformidade, 160 s) grava cerca de 0,42 MB de logs, 0,38 MB de métricas e 0,19 MB de traces, e as métricas crescem uns 75 KB a cada 30 s (~9 MB/h); 10 MB por arquivo, com 3 rotacionados, guardam mais de cem rodadas e cerca de 4 horas de métricas.

**Resource** (seção 4): `service.name = gateway`, `service.namespace = smarkee`, `service.version` (a do APISIX), `deployment.environment.name`; `service.instance.id` e `host.name` vêm do nome do contêiner, pelo coletor.

**Span** (semconv HTTP v1.44.0, [span de servidor](https://opentelemetry.io/docs/specs/semconv/http/http-spans/#http-server-span)):

| Item | Valor |
|---|---|
| Tipo e nome | `SERVER`; `{método} {http.route}`, ou só `{método}` sem rota; método fora da lista conhecida vira `_OTHER` (nome `HTTP ...`) |
| Obrigatórios | `http.request.method`, `url.path`, `url.scheme`; `http.response.status_code`, `http.route` (só se a rota casou), `error.type` (nos 5xx, o código), `url.query` (quando há), `server.port` (quando o `Host` traz porta) |
| Recomendados | `server.address`, `client.address`, `network.peer.address`, `network.peer.port`, `network.protocol.version`, `user_agent.original` |
| Próprios | `apisix.route_id`, `apisix.route_name`, `apisix.service_id`, `apisix.service_name`, `apisix.response_source` |
| Status | Não definido em 1xx a 4xx; `Error` nos 5xx, sem descrição |
| Depreciados | Nenhum (`http.method`, `http.scheme`, `http.target`, `http.user_agent`, `http.status_code` e `net.host.name` são removidos) |

**Privacidade e confiança:**
- `url.query` mantém as chaves e troca **todos os valores** por `REDACTED` (a query do OIDC carrega `code`, `state` e `code_challenge`); `http.target`, que a trazia por inteiro, é removido.
- `server.address`, `client.address` e `url.scheme` **não** usam `X-Forwarded-*` enviados pelo cliente: o gateway é a borda. Atrás de um balanceador (stg e prd), o IP real vem do plugin `real-ip` (decisão 0054).
- `client.address` e `network.peer.address` guardam o IP, que é dado pessoal. **Decidido em 2026-10-18 (decisão 0059): o IP fica nos spans.** Em stg e prd, a retenção curta do backend e a base legal do tratamento precisam ser definidas antes de o dado ser guardado.

**Propagação:** o gateway **inicia um trace novo** em cada requisição (decisão 0054): uma regra global `proxy-rewrite` remove `traceparent` e `tracestate` do cliente antes do plugin `opentelemetry`, então o cliente não escolhe o `trace_id` nem a amostragem. O gateway repassa ao upstream um `traceparent` com o `span_id` do próprio span. A amostragem é `parent_base` com raiz `always_on`.

**Conformidade verificada em 2026-10-17** (APISIX 3.19.0, Collector contrib 0.162.0 e, de novo, 0.163.1, semconv v1.44.0, o fragmento do repositório): 41 regras aprovadas e nenhuma reprovada (21 obrigatórias, 2 "devem", 8 recomendadas, 6 de propagação e 4 do projeto), sobre 16 pedidos (sucesso, 4xx, 5xx, rota inexistente, método desconhecido, `Host` com porta, cabeçalhos `X-Forwarded-*` forjados, `traceparent` amostrado e não amostrado, HEAD e HTTP/1.0). Com o **plugin sem ajustes** (amostrador `always_on`, sem as variáveis extras e sem o processador) a mesma bateria reprova 7 regras obrigatórias, 1 "deve", 7 recomendadas, 1 de propagação e 1 do projeto. A verificação usou um coletor descartável e um validador que **não estão versionados**. Não cobre HTTP/2 e HTTP/3, WebSocket, gRPC, nem o comportamento atrás de balanceador.

**Limites conhecidos:**
- Só existe o span de servidor: sem o span de cliente da chamada ao upstream, o service graph não desenha a aresta gateway → componente.
- O escopo de instrumentação mantém o nome `opentelemetry-lua`; a versão é a do serviço.
- Com o coletor parado, o gateway registra um `[error] request failed: connection refused` por lote de spans, sem afetar as requisições.

# 12. Contexto de trace nos componentes

Decisão [`0055`](../../.decisions/0055-contexto-de-trace-nos-componentes.md). Os componentes **repassam** o `traceparent` W3C e o gravam nos logs; não criam spans nem usam o SDK do OpenTelemetry.

**Caminho:** gateway (inicia o trace, seção 11) → Receiver (header HTTP) → NATS (header `traceparent`, ao lado de `Nats-Msg-Id`, fora do envelope) → Manager (consome e grava a coluna `traceparent` do outbox) → Publisher (lê a coluna e publica o header) → Reconciler (guarda o contexto do `desired` e o aplica à `action`) → Executor (consome a `action`, repassa o contexto ao `completed`/`failed`) → Manager (resultado) → Publisher. O Observer **não** propaga: suas observações são periódicas e não nascem de um pedido.

**Regras:**

- Só se aceita `traceparent` versão `00`, em minúsculas, com `trace_id` e `span_id` não nulos; qualquer outro valor é descartado, nunca repassado nem registrado.
- O contexto vale só para a mensagem ou requisição em tratamento: cada consumidor o associa ao contexto da tarefa e o limpa ao terminar, para que logs entre mensagens não herdem o `trace_id` anterior.
- O Reconciler guarda o contexto no estado do recurso (a `action` sai de uma mensagem `observed`, que não tem contexto, ou da reavaliação periódica).
- Cada hop emite um evento de log por unidade de trabalho (`request published`, `message handled`, `outbox message published`, `action published`, `action handled`), com `trace_id`; sem eles o contexto não apareceria, pois os componentes quase não logam no fluxo normal.

**Verificado em 2026-10-18:** um cadastro e as operações da jornada mostraram o mesmo `trace_id` do span do gateway nos logs de todos os papéis do `core/account`, do `ipm/organization` e do `sum/service`; um `traceparent` forjado pelo cliente não chegou aos componentes.

# 13. Contexto de negócio nos logs dos apps

Decisão [`0061`](../../.decisions/0061-contexto-de-negocio-nos-logs-dos-apps.md). Os logs dos **apps** (os 18 contêineres das três features) carregam **quem pediu, qual recurso, qual ação, o dono e a organização**, para o drill-down. A **infra** continua sem dono: atende vários clientes. Isto **não** é auditoria (a auditoria é outro produto, com garantias de completude e retenção que a telemetria não tem).

**Atributos** (do contexto da requisição ou da mensagem em tratamento; o que o evento informa explicitamente prevalece):

| Atributo | De onde vem | Quando falta |
|---|---|---|
| `user.id` | `principal` validado do Receiver; `requestedBy` do envelope nos demais papéis | omitido |
| `smarkee.actor.type` | `user` (id opaco válido), `anonymous` (escrita anônima), `system` (mensagem sem solicitante: as `observed`, os fatos `updated`, o Observer e a reavaliação periódica) | omitido |
| `smarkee.resource.id` | o `resourceId` da requisição ou da mensagem | omitido |
| `smarkee.operation.name` | rota (`create`, `update`, `delete`) ou `operation` do envelope | omitido |
| `smarkee.owner.id` | `data.ownerAccountId`, quando a mensagem o traz | omitido |
| `smarkee.organization.id` | o `resourceId`, quando o recurso é uma Organization | omitido |

**Regras:**

- **Desconhecido é omitido**, e não escrito como `unknown` (padrão OpenTelemetry). A exceção é o tipo do ator, de baixa cardinalidade, que é sempre explícito quando há contexto.
- **Só identificador opaco**: o formato de `user.id`, `smarkee.owner.id` e demais ids não admite `@` nem `.`; um valor fora do formato (por exemplo, um e-mail) é descartado e nunca registrado. O schema e o teste de conformidade vigiam.
- **O ator vem só do dado validado** (o token que o Receiver verificou; o `requestedBy` do envelope), nunca de um valor enviado pelo cliente.
- **`anonymous` quer dizer não autenticado**, e não anonimizado. O id do ator é **pseudonimizado** (o `sub`, um UUID opaco). Um hash com chave (HMAC) é um passo posterior e aditivo, útil se o backend for de terceiros.
- **Em métricas**, o id do ator, do recurso e da organização **não** podem ser atributo (cardinalidade ilimitada); só o tipo do ator e dimensões de baixa cardinalidade. O drill-down é métrica → trace → logs.
- **Quem executou** não precisa de atributo novo: o `service.name` do Resource (`<módulo>-<tipo>-<papel>`) é o nome da conta de serviço do Zitadel.

**Como funciona:** o `logging_config.py` (a fonte única, decisão 0046) mantém um contexto por requisição ou mensagem. O Receiver o preenche na autenticação e ao publicar; Manager, Reconciler e Executor o preenchem a partir do envelope, no mesmo ponto em que já ligam o `traceparent`; o Publisher, a partir da linha do outbox. `bind_traceparent` inicia um contexto novo e é o que os consumidores usam para limpar (`finally`); o Reconciler guarda e restaura o contexto ao reavaliar.

**Limites declarados:** o span do gateway e as métricas ainda não têm este contexto (etapas seguintes do plano). Nas mensagens de estado, a ação do envelope é `changed`; a ação original (`create`) aparece nos hops que a carregam. O fato `updated` não traz `requestedBy`, então fica `system`. O dono só aparece onde a mensagem o traz. **Verificado em 2026-10-19** com três donos e cinco organizações: 99% dos logs de app com tipo de ator, `user.id` por conta e `smarkee.organization.id` por organização, e nenhum `user.id` com formato de e-mail.

# 14. Arquitetura de coleta

A arquitetura (as peças `telemetry-agent`, `telemetry-router`, `telemetry-sink` e `<módulo>-<tipo>-telemeter`, o roteamento de cada sinal, as filas e falhas, a segurança, o mapeamento para Kubernetes e como acrescentar uma feature) está em [`OBSERVABILITY-ARCHITECTURE.md`](OBSERVABILITY-ARCHITECTURE.md), com os diagramas. Decisão [`0062`](../../.decisions/0062-coleta-de-telemetria-em-duas-camadas.md).

Este documento fica com o **contrato** da telemetria: o formato dos logs, os atributos, a semconv, o contexto de negócio (seção 13) e o span do gateway (seção 11).
