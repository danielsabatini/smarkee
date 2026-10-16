# Observabilidade

> **Escopo:** contrato de **logs** emitidos pelos componentes da plataforma (`features/*`). Métricas, traces e auditoria ainda não estão definidos aqui.
>
> **Papel:** fonte de verdade do formato, dos campos e das proibições dos logs. O contrato executável é o schema [`schemas/observability/log-record.v1.schema.json`](../schemas/observability/log-record.v1.schema.json). As decisões que o originaram são a [`0045`](../.decisions/0045-contrato-de-logs-opentelemetry.md) e a [`0046`](../.decisions/0046-codigo-identico-gerado-de-fonte-unica.md). A segurança do que pode ou não ser registrado vem de [`RESOURCE-CONTROL-SECURITY.md`](RESOURCE-CONTROL-SECURITY.md) (§13) e de [`SCHEMA.md`](SCHEMA.md) (`sensitivity`).
>
> **Status:** os 18 componentes (`core.account`, `ipm.organization` e `sum.service`) seguem o contrato. A coleta (seção 7) ainda não existe: hoje o log fica no stdout (ver [`IMPLEMENTATION-STATUS.md`](IMPLEMENTATION-STATUS.md)).

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
| `trace_id`, `span_id`, `trace_flags` | `TraceId`, `SpanId`, `TraceFlags` | Opcionais; **omitidos** enquanto não houver traces. `span_id` só com `trace_id`. |
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

- O stdout é capturado pelo runtime do contêiner. **Alguém precisa lê-lo**: em Kubernetes, um OpenTelemetry Collector em DaemonSet com o `filelog receiver` lendo os arquivos de log dos pods; em dev, `docker compose logs` basta e o coletor é opcional.
- O coletor interpreta a linha (JSON), converte `timestamp`, `severity_*`, `trace_id` e `span_id` para os campos do LogRecord, move `resource` e `attributes` para seus lugares e define `ObservedTimestamp`.
- O componente nunca depende do coletor nem do destino: se eles caírem, o log continua no stdout.
- **Requisitos verificados em 2026-10-16** (Collector `otel/opentelemetry-collector-contrib:0.162.0`, receiver `file_log`, linhas reais do formatter em Docker):
  - o contêiner precisa usar o driver de log **`json-file`**. O padrão do Docker Desktop é `local`, que grava `container.log` em formato próprio e **não** é lido pelo `file_log`. Os `compose.yaml` das features configuram `json-file` (rotação de 10 MB e 3 arquivos) nos 18 componentes;
  - o Collector precisa ler `/var/lib/docker/containers` como root (os arquivos são 0600 do root);
  - o pipeline que funcionou: operador `container` (formato `docker`), `json_parser` com `timestamp` (`%Y-%m-%dT%H:%M:%S.%fZ`) e `severity` (de `severity_text`), `move` de `attributes.body` para `body` e, no processador `transform` (OTTL), `scope.name`, `Resource`, `event_name` (campo `EventName`) e `attributes` movidos para seus lugares. O `move` do operador não aceita a raiz (`resource` ou `attributes`) como destino;
  - o resultado foi um LogRecord com `Timestamp`, `ObservedTimestamp`, `SeverityNumber` e `SeverityText`, `Body`, `EventName`, escopo, `Resource` e atributos corretos, e sem `exception.message`. O Collector acrescenta `log.iostream` e `log.file.name`.
  - Em Kubernetes o formato do arquivo é o do CRI (containerd), e não o do Docker; o operador `container` com `format: containerd` ou `cri-o` cobre isso, mas **não foi testado**.
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
