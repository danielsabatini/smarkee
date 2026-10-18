# Observabilidade

> **Escopo:** contrato de **logs** emitidos pelos componentes da plataforma (`features/*`) e, na seção 11, o **span do gateway**. Métricas, traces dos componentes e auditoria ainda não estão definidos aqui.
>
> **Papel:** fonte de verdade do formato, dos campos e das proibições dos logs. O contrato executável é o schema [`schemas/observability/log-record.v1.schema.json`](../schemas/observability/log-record.v1.schema.json). As decisões que o originaram são a [`0045`](../.decisions/0045-contrato-de-logs-opentelemetry.md) e a [`0046`](../.decisions/0046-codigo-identico-gerado-de-fonte-unica.md). A segurança do que pode ou não ser registrado vem de [`RESOURCE-CONTROL-SECURITY.md`](RESOURCE-CONTROL-SECURITY.md) (§13) e de [`SCHEMA.md`](SCHEMA.md) (`sensitivity`).
>
> **Status:** os 18 componentes (`core.account`, `ipm.organization` e `sum.service`) seguem o contrato. Em dev a coleta existe (seção 7: `telemetry-agent` → `telemetry-gateway`), mas o destino ainda só grava em arquivos com rotação (10 MB), separados em infra e app; não há armazenamento persistente (ver [`IMPLEMENTATION-STATUS.md`](IMPLEMENTATION-STATUS.md)).

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
  "scope": {"name": "core_account_manager.main"},
  "resource": {
    "service.name": "core-account-manager",
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
    "code.file.path": "core_account_manager/transport/nats.py",
    "code.line.number": 88,
    "code.function.name": "core_account_manager.transport.nats.connect",
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

# 4. Resource: quem emitiu

Atributos do componente, fixos durante o processo. Vêm de configuração explícita, nunca de opção de linha de comando.

| Atributo | Valor | Origem |
|---|---|---|
| `service.name` | `<módulo>-<tipo>-<papel>` (por exemplo, `core-account-manager`) | Derivado do nome do pacote Python (`<módulo>_<tipo>_<papel>`), o que mantém o arquivo idêntico em todos os componentes. |
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

O código de produção **não** monta `error.type`, `exception.type` e `code.*` à mão: ao registrar uma exceção, passa `exc_info=error` ao logger, e o formatter emite os quatro atributos sem a mensagem nem a pilha.
| `user.id` | O solicitante (`requestedBy`), identificador opaco ou `anonymous`. |
| `messaging.system` | `nats` (valor próprio: a semconv não define um valor para NATS). |
| `messaging.destination.name` | Subject, quando o registro é de uma mensagem. |
| `messaging.message.id` | `messageId` do envelope. |
| `messaging.consumer.group.name` | Nome do consumer durável do JetStream. |

Os atributos `messaging.*` e `user.*` estão em estágio *development* na semconv; podem ser renomeados. A revisão da versão da semconv é uma tarefa explícita (seção 9).

## 5.2 Próprios da plataforma

Tudo o que a semconv não cobre usa o prefixo `smarkee.`.

| Atributo | Significado |
|---|---|
| `smarkee.resource.id` | `resourceId` do recurso tratado. |
| `smarkee.organization.id` | `organizationId`, quando existir no contexto. |
| `smarkee.correlation.id` | `correlationId` do envelope. |
| `smarkee.causation.id` | `causationId` do envelope. |
| `smarkee.operation.id` | `operationId`. |
| `smarkee.action.id` | `actionId`. |
| `smarkee.task.name` | Tarefa interna do processo (consumer, servidor de saúde, publicação). |
| `smarkee.outcome` | Desfecho curto e de baixa cardinalidade (por exemplo, `accepted`, `rejected`). |
| `smarkee.reason` | Motivo de um desfecho ou de uma rejeição. Só texto de erro de **domínio próprio**, construído sem valores (nomes de campos, nome da operação); nunca `str(error)` de uma biblioteca (seção 6). |
| `smarkee.operation.name` | Operação do recurso (`create`, `delete`, ...). |
| `smarkee.observation.presence` | `presence` da observação (`present`, `absent`, `unknown`). |
| `smarkee.result.type` | Tipo do resultado tratado (`completed`, `failed`). |
| `smarkee.desired.generation` | Geração do `desired`. |
| `smarkee.delivery.attempt` | Tentativa de entrega ou de processamento (a partir de 1). |
| `smarkee.partition`, `smarkee.partition.count` | Partição do processo (`índice/total`) e total de partições. |
| `smarkee.instance.name` | Nome da instância de Observer ou Reconciler (estado em memória). |
| `smarkee.outbox.sequence`, `smarkee.failure.permanent` | Linha do outbox e se a falha de publicação é permanente. |
| `smarkee.account.id`, `smarkee.links.removed` | Conta removida e quantidade de ligações apagadas (`sum.service`). |
| `smarkee.config.missing_variables` | Nomes (nunca valores) das variáveis obrigatórias ausentes. |

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

- O stdout é capturado pelo runtime do contêiner. **Alguém precisa lê-lo**: em Kubernetes, um OpenTelemetry Collector em DaemonSet com o `filelog receiver` lendo os arquivos de log dos pods; em dev, o `telemetry-agent` (decisão [`0051`](../.decisions/0051-telemetry-agent-coleta-em-dev.md)) lê os arquivos de log dos contêineres e `docker compose logs` continua valendo.
- O coletor interpreta a linha (JSON), converte `timestamp`, `severity_*`, `trace_id` e `span_id` para os campos do LogRecord, move `resource` e `attributes` para seus lugares e define `ObservedTimestamp`.
- O componente nunca depende do coletor nem do destino: se eles caírem, o log continua no stdout.
- **Requisitos verificados em 2026-10-16** (Collector `otel/opentelemetry-collector-contrib:0.162.0`, receiver `file_log`, linhas reais do formatter em Docker):
  - o contêiner precisa usar o driver de log **`json-file`**. O padrão do Docker Desktop é `local`, que grava `container.log` em formato próprio e **não** é lido pelo `file_log`. Os `compose.yaml` das features configuram `json-file` (rotação de 10 MB e 3 arquivos) nos 18 componentes;
  - o Collector precisa ler `/var/lib/docker/containers` como root (os arquivos são 0600 do root);
  - o pipeline que funcionou: operador `container` (formato `docker`), `json_parser` com `timestamp` (`%Y-%m-%dT%H:%M:%S.%fZ`) e `severity` (de `severity_text`), `move` de `attributes.body` para `body` e, no processador `transform` (OTTL), `scope.name`, `Resource`, `event_name` (campo `EventName`) e `attributes` movidos para seus lugares. O `move` do operador não aceita a raiz (`resource` ou `attributes`) como destino;
  - o resultado foi um LogRecord com `Timestamp`, `ObservedTimestamp`, `SeverityNumber` e `SeverityText`, `Body`, `EventName`, escopo, `Resource` e atributos corretos, e sem `exception.message`. O Collector acrescenta `log.iostream` e `log.file.name`.
  - Em Kubernetes o formato do arquivo é o do CRI (containerd), e não o do Docker; o operador `container` com `format: containerd` ou `cri-o` cobre isso, mas **não foi testado**.
- **Coleta em dev** (`infrastructure/dev/telemetry-agent`, Collector contrib 0.163.1, verificada em 2026-10-17 contra os 18 componentes reais e contra um contêiner de teste): o agente lê `/var/lib/docker/containers/*/*-json.log` e envia por OTLP/gRPC ao `telemetry-gateway`. Diferenças em relação ao pipeline acima, descobertas na verificação:
  - o `Resource` e o escopo têm de ser movidos **por registro, no próprio `file_log`** (`move` das 8 chaves de `resource`, que são o conjunto fechado do schema, e `scope_name` do `json_parser`), e não no `transform`: o `file_log` agrupa em um único `Resource` e um único escopo todas as linhas lidas do mesmo arquivo, e alterá-los no `transform` sobrescreve o do lote inteiro. Isso importa porque o contêiner reiniciado mantém o arquivo de log e passa a ter outro `service.instance.id`;
  - `parse_ints: true` no `json_parser`, senão `code.line.number` (inteiro na semconv) sai como `double`;
  - `on_error: send_quiet` no `json_parser`: uma linha que começa com `{` mas não é JSON segue como texto e é descartada no filtro;
  - o filtro descarta tudo que não tem `service.namespace = smarkee` (outros projetos do host, texto puro), antes de sair do agente;
  - a versão do escopo é zerada (o `file_log` coloca a do Collector);
  - `trace_id`, `span_id` e `trace_flags` já são mapeados para os campos do LogRecord (`trace_id` e `trace_flags` já saem dos componentes, seção 12).
  - Além dos logs, o agente envia as métricas de contêiner (`docker_stats`: CPU, memória, rede) dos contêineres `*.smarkee.internal`.
  - **Logs da plataforma (decisão 0053):** os contêineres de longa duração da plataforma usam o driver `json-file` com as labels `com.docker.compose.service` e `smarkee.layer=infra`; o agente usa a primeira como `service.name` e a segunda como gate. A severidade vem de cinco padrões (logfmt e JSON, NATS, PostgreSQL, nginx, Collector). Política enxuta: só `WARN` ou acima e sem as linhas de acesso do nginx; os logs de aplicação ficam inteiros.
  - **Healthchecks** (`/health/*`, `/healthz`, `/readyz`, `/livez` e o healthcheck da Admin API do APISIX) são descartados no agente. Eles eram 74% dos logs retidos.
- O destino (armazenamento, consulta, retenção) não faz parte deste documento.

# 8. Conformidade

- Cada componente mantém seu próprio `logging_config.py` (decisão [`0015`](../.decisions/0015-componentes-por-papel-autocontidos.md)): não há biblioteca de log compartilhada. As cópias são **idênticas** (a identidade vem do nome do pacote), assim como o `tests/unit/test_logging.py` de cada componente, exceto pelo nome do pacote.
- **A fonte única** está em `schemas/observability/python/`. `python schemas/observability/sync.py` regrava as cópias e `--check` as confere (decisão 0046). Alterar o formatter é alterar a fonte, sincronizar e rodar a suíte de cada componente. Um teste em `schemas/tests` falha se uma cópia divergir.
- **O schema da linha** (`schemas/observability/log-record.v1.schema.json`) é o contrato verificável. Ele fecha os atributos aos nomes da semconv listados nele e ao namespace `smarkee.*`, e proíbe `exception.message` e `exception.stacktrace`. Atributo novo da semconv entra no schema, e atributo `smarkee.*` já é aceito pelo padrão.
- O teste de cada componente verifica: que a linha emitida cumpre o schema; o mapeamento de severidade; `EventName`; a omissão de valores nulos; que a mensagem da exceção não aparece; o `Resource` derivado do pacote; e, por análise estática do código-fonte, que **toda chave de `extra` dos loggers é um atributo que o schema aceita** ou `event_name`.
- A CLI `sk` não emite logs neste formato: o que ela mostra ao usuário é saída de interface, em inglês (decisão `0035`).

# 9. Versão de referência

As páginas oficiais consultadas em 2026-10-16 não exibem um número de versão da semconv; as ligações internas apontam para a versão 1.59.0 da especificação. Na hora de implementar, confirmar nomes e estágios contra a versão vigente e registrar a versão aqui.

# 10. Pendências

- Validar o `file_log` em Kubernetes (formato CRI). Em Docker já foi validado (seção 7).
- `event_name` ainda não é usado por nenhum componente; definir os eventos nomeados ao precisar deles.
- Confirmar nomes e estágios dos atributos contra a versão vigente da semconv (seção 9).
- Coleta (seção 7): decidir o que fazer com os `WARN` benignos do Zitadel (`decrypt access token` e `Usuário não pôde ser encontrado`, 78% dos logs de infra): filtrar por mensagem ou baixar o nível de log do Zitadel.
- Métricas de aplicação (`metrics/app` está vazio): definir o que medir (taxa e erro por componente, atraso dos consumers do NATS, duração do loop, tamanho do outbox) e como emitir.
- Traces distribuídos, fase 2: spans de verdade nos componentes (exigiria o SDK do OpenTelemetry em cada um, uma dependência a aprovar), propagar também nas chamadas HTTP entre módulos (o Receiver do `sum` ao `ipm`) e dar um trace próprio à observação periódica.
- Coleta (seção 7): em stg e prd o agente é um DaemonSet que lê os logs do nó (formato CRI, não testado), sem o socket do Docker; o `telemetry-agent` de dev monta o socket do Docker e roda como root, o que não se repete lá.
- Traces do gateway (seção 11): promover a verificação de conformidade a teste versionado; decidir se o endereço IP do cliente fica nos spans.

# 11. Traces do gateway

Decisão [`0050`](../.decisions/0050-traces-do-gateway-opentelemetry.md). Vale só para o **span de servidor do gateway** (APISIX); os traces dos componentes do loop ainda não estão definidos.

**Caminho:** plugin `opentelemetry` do APISIX → OTLP/HTTP → **`telemetry-gateway`** (`infrastructure/dev/telemetry-gateway`) → arquivos (exporter `file`, rotação em 10 MB; ainda não há backend). O plugin é aplicado a todas as rotas por uma regra global (`infrastructure/dev/gateway/bootstrap/adc.yaml`) e o destino vem de `APISIX_OTEL_COLLECTOR_ADDRESS`. Como o plugin emite nomes depreciados e nomeia atributos pelo nome da variável do nginx, o **coletor ajusta os spans** com o processador de [`infrastructure/dev/telemetry-gateway/gateway-semconv.yaml`](../infrastructure/dev/telemetry-gateway/gateway-semconv.yaml), colocado logo depois do `memory_limiter` e antes de qualquer exporter (em outro coletor, antes do service graph e do tail sampling). O processador só age em spans do gateway. As pipelines de métricas e de logs também existem. Cada sinal vai para a sua pasta de `infrastructure/dev/telemetry-gateway`: `logs/{app,infra}`, `metrics/{app,infra}` e `traces/` (decisão 0053), em arquivos de uma linha OTLP JSON por lote (`jq` lê); o ativo é `<sinal>.jsonl`, e ao chegar a 10 MB é renomeado `<sinal>-<data>-size.jsonl` (ficam 3, por até 1 dia). A separação é do próprio coletor: **logs de app** são os que trazem `smarkee.component.role` (contrato 0045); os demais, dos contêineres da plataforma, são **infra**. **Métricas de infra** são as de prefixo `container.`, `system.`, `process.` e `k8s.`; as demais, de **app** (hoje só as sintéticas de teste: nenhum componente emite métrica própria ainda). Um registro único maior que 10 MB é rejeitado pelo exporter (erro no log do coletor; o receptor ainda responde 200), por isso o `batch` limita os lotes a 200 itens. Tamanho medido em 2026-10-17: uma rodada completa (jornada com a CLI real e as três suítes de conformidade, 160 s) grava cerca de 0,42 MB de logs, 0,38 MB de métricas e 0,19 MB de traces, e as métricas crescem uns 75 KB a cada 30 s (~9 MB/h); 10 MB por arquivo, com 3 rotacionados, guardam mais de cem rodadas e cerca de 4 horas de métricas.

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
- `server.address`, `client.address` e `url.scheme` **não** usam `X-Forwarded-*` enviados pelo cliente: o gateway é a borda. Atrás de um balanceador (stg e prd), o IP real exige o plugin `real-ip`.
- `client.address` e `network.peer.address` guardam o IP, que é dado pessoal: a decisão de mantê-lo está pendente (seção 10).

**Propagação:** o gateway **inicia um trace novo** em cada requisição (decisão 0054): uma regra global `proxy-rewrite` remove `traceparent` e `tracestate` do cliente antes do plugin `opentelemetry`, então o cliente não escolhe o `trace_id` nem a amostragem. O gateway repassa ao upstream um `traceparent` com o `span_id` do próprio span. A amostragem é `parent_base` com raiz `always_on`.

**Conformidade verificada em 2026-10-17** (APISIX 3.19.0, Collector contrib 0.162.0 e, de novo, 0.163.1, semconv v1.44.0, o fragmento do repositório): 41 regras aprovadas e nenhuma reprovada (21 obrigatórias, 2 "devem", 8 recomendadas, 6 de propagação e 4 do projeto), sobre 16 pedidos (sucesso, 4xx, 5xx, rota inexistente, método desconhecido, `Host` com porta, cabeçalhos `X-Forwarded-*` forjados, `traceparent` amostrado e não amostrado, HEAD e HTTP/1.0). Com o **plugin sem ajustes** (amostrador `always_on`, sem as variáveis extras e sem o processador) a mesma bateria reprova 7 regras obrigatórias, 1 "deve", 7 recomendadas, 1 de propagação e 1 do projeto. A verificação usou um coletor descartável e um validador que **não estão versionados**. Não cobre HTTP/2 e HTTP/3, WebSocket, gRPC, nem o comportamento atrás de balanceador.

**Limites conhecidos:**
- Só existe o span de servidor: sem o span de cliente da chamada ao upstream, o service graph não desenha a aresta gateway → componente.
- O escopo de instrumentação mantém o nome `opentelemetry-lua`; a versão é a do serviço.
- Com o coletor parado, o gateway registra um `[error] request failed: connection refused` por lote de spans, sem afetar as requisições.

# 12. Contexto de trace nos componentes

Decisão [`0055`](../.decisions/0055-contexto-de-trace-nos-componentes.md). Os componentes **repassam** o `traceparent` W3C e o gravam nos logs; não criam spans nem usam o SDK do OpenTelemetry.

**Caminho:** gateway (inicia o trace, seção 11) → Receiver (header HTTP) → NATS (header `traceparent`, ao lado de `Nats-Msg-Id`, fora do envelope) → Manager (consome e grava a coluna `traceparent` do outbox) → Publisher (lê a coluna e publica o header) → Reconciler (guarda o contexto do `desired` e o aplica à `action`) → Executor (consome a `action`, repassa o contexto ao `completed`/`failed`) → Manager (resultado) → Publisher. O Observer **não** propaga: suas observações são periódicas e não nascem de um pedido.

**Regras:**

- Só se aceita `traceparent` versão `00`, em minúsculas, com `trace_id` e `span_id` não nulos; qualquer outro valor é descartado, nunca repassado nem registrado.
- O contexto vale só para a mensagem ou requisição em tratamento: cada consumidor o associa ao contexto da tarefa e o limpa ao terminar, para que logs entre mensagens não herdem o `trace_id` anterior.
- O Reconciler guarda o contexto no estado do recurso (a `action` sai de uma mensagem `observed`, que não tem contexto, ou da reavaliação periódica).
- Cada hop emite um evento de log por unidade de trabalho (`request published`, `message handled`, `outbox message published`, `action published`, `action handled`), com `trace_id`; sem eles o contexto não apareceria, pois os componentes quase não logam no fluxo normal.

**Verificado em 2026-10-18:** um cadastro e as operações da jornada mostraram o mesmo `trace_id` do span do gateway nos logs de todos os papéis do `core/account`, do `ipm/organization` e do `sum/service`; um `traceparent` forjado pelo cliente não chegou aos componentes.
