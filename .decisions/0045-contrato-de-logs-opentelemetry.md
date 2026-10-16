# 0045 — Contrato de logs da plataforma, 100% OpenTelemetry

- **Data:** 2026-10-16
- **Status:** Aceita e implementada nos 18 componentes (`core.account`, `ipm.organization` e `sum.service`). O contrato está em [`docs/OBSERVABILITY.md`](../docs/OBSERVABILITY.md). Complementa a segurança de logs de `docs/RESOURCE-CONTROL-SECURITY.md` §13 e não altera a 0015.

## Contexto

Os componentes de `core.account`, `ipm.organization` e `sum.service` já emitem logs estruturados em JSON no stdout, mas com chaves próprias (`time`, `level`, `logger`, `message`) e atributos soltos (`resource_id`, `error_type`, `task`). Cada componente tem sua cópia do formatter (consequência da 0015). Antes de o ambiente crescer (stg e prd em Kubernetes), a plataforma precisa de **um único contrato de log**, seguido por todos, baseado no OpenTelemetry (modelo de dados de logs e convenções semânticas).

Restrição que deve continuar valendo: a mensagem de exceção não entra no log, porque pode conter valores de colunas (por exemplo, o e-mail na violação de unicidade).

## Decisão

- **Cada log é um LogRecord do OpenTelemetry**, escrito como **uma linha JSON no stdout**, com os campos do modelo de dados e atributos com os nomes da semconv. Atributos que a semconv não cobre usam o prefixo `smarkee.`.
- **O formatter continua sendo código próprio de cada componente**, sem o SDK de logs do OpenTelemetry para Python e sem dependência nova.
- **O componente não envia o log a nenhum destino.** O stdout é lido por um coletor (OpenTelemetry Collector, `filelog receiver`), que converte a linha em LogRecord e entrega ao destino.
- **Exceção deliberada à semconv:** `exception.message` e `exception.stacktrace` não são emitidos (por segurança). `exception.type` e o local do último quadro (`code.*`) são suficientes para o diagnóstico. A semconv só exige `exception.message` quando `exception.type` não está definido, então a regra é compatível.
- O detalhe do contrato (campos, severidade, atributos, proibições, coleta e conformidade) pertence a `docs/OBSERVABILITY.md`; este registro não o repete.

## Justificativa

Comparação pelos pilares do projeto:

| Opção | Segurança | Simplicidade | Robustez | Disponibilidade |
|---|---|---|---|---|
| A. SDK OTel para Python enviando OTLP direto ao coletor | O SDK registra a exceção com `exception.message` por padrão, o que conflita com a regra acima | Dependências novas (`AGENTS.md` §21) | Logs do SDK do Python em *development*; o `LoggingHandler` foi movido para o pacote contrib e está deprecado no SDK, com quebras previstas | Perde log se o coletor cair |
| **B. JSON no stdout com o modelo de dados e a semconv, formatter próprio (adotada)** | Controle total do que sai | Evolui o formatter que já existe, sem dependência | O contrato é a especificação estável (modelo de dados de logs), e não um SDK instável | Desacoplado do coletor e do destino |
| C. OTLP/JSON em stdout pelo exporter de arquivo do SDK | Igual à A | Dependência nova | O receiver de arquivo OTLP/JSON lê arquivo, e a linha chega embrulhada pelo runtime do contêiner; exigiria desembrulhar no coletor. **Não verificado.** | Desacoplado |

Como o contrato é o modelo de dados mais a semconv, trocar o emissor depois (para A ou C) não muda o que o coletor e o destino recebem.

## Consequências

- **Quebra de contrato dos logs** (ainda sem release): chaves e atributos mudam (`time` → `timestamp`, `level` → `severity_*`, `message` → `body`, `error_type` → `error.type`/`exception.type`, `resource_id` → `smarkee.resource.id`). Não há consumidor externo dos logs hoje.
- Os componentes migraram: `logging_config.py` idêntico em todos (identidade pelo nome do pacote), chaves de `extra` renomeadas para atributos, `exc_info=error` no lugar de `error_type`, e `test_logging.py` com análise estática das chaves. Não há código comum (a 0015 se mantém). `SMARKEE_ENVIRONMENT` é a única variável nova, definida nos Compose das features.
- Os atributos `messaging.*` e `user.*` estão em *development* na semconv e podem ser renomeados; o documento registra a versão de referência e a revisão.
- A CLI `sk` fica fora do contrato (saída de interface, decisão 0035).

## Gatilhos para reavaliar

- O Logs SDK do Python se tornar estável e permitir omitir `exception.message` e a pilha por configuração: reavaliar A (ou C).
- Validação do `filelog receiver` com linhas reais mostrar que o mapeamento exige mudança de formato.

## Fora do escopo desta decisão

O destino dos sinais (logs, métricas, traces e auditoria) e a retenção. A direção definida com o usuário é: sinal → stream NATS (**instância separada** do NATS do loop) ← ClickHouse (curto prazo) → armazenamento de objetos (longo prazo). Ela será registrada em decisões próprias (pipeline de telemetria, com prova de conceito do engine NATS do ClickHouse; e auditoria, com requisitos próprios de perda, imutabilidade e retenção). Nada nelas altera este contrato.
