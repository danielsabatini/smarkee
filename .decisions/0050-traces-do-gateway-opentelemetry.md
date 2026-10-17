# 0050 — Traces do gateway com o plugin `opentelemetry` e ajuste no coletor

- **Data:** 2026-10-17
- **Status:** Aceita e implementada em desenvolvimento. Cobre só o span de servidor do gateway; os traces dos componentes do loop continuam adiados.
- **Origem:** o adiamento do contrato de traces registrado em `MEMORY.md` (propagar `traceparent` antes de ligar o plugin) e a decisão 0049 (gateway no APISIX).

## Contexto

O plugin `opentelemetry` do APISIX 3.19.0 vem desabilitado e, ligado, não segue a semconv: emite os nomes HTTP depreciados junto com os novos (`http.method`, `http.target`, `net.host.name`...), grava `hostname` no `Resource`, não normaliza métodos desconhecidos para `_OTHER`, não preenche `error.type`, `server.*`, `client.*`, `network.*` nem `url.query`, escreve descrição no status dos 5xx e usa o amostrador `always_off` por padrão. O `http.target` carrega a query por inteira, onde o OIDC leva `code`, `state` e `code_challenge`. A configuração do plugin não corrige isso: o `additional_attributes` só acrescenta variáveis do nginx com o **nome da variável** como chave.

O destino dos traces é um coletor OTLP. Em dev é o `telemetry-gateway` (`infrastructure/dev`), que ainda não tem backend e grava tudo no stdout. A stack de observabilidade do desenvolvedor tem um otel-gateway (OTLP em 4318, tail sampling e Tempo) que recebe 100% dos spans e depende de atributos da semconv no service graph; ele é o destino futuro.

## Decisão

- **Plugin:** `opentelemetry` habilitado no `config.yaml` do gateway e aplicado a todas as rotas por uma regra global no `adc.yaml`. Declarar `plugins:` substitui a lista padrão do APISIX; a lista passa a ser a padrão da 3.19.0 (109 plugins) mais o `opentelemetry`.
- **Amostragem:** `parent_base` com raiz `always_on` em dev (segue o chamador; o coletor de destino faz a amostragem final). stg e prd definem a razão própria.
- **Variáveis extras** pedidas ao plugin: `http_host`, `remote_addr`, `remote_port`, `realip_remote_addr`, `realip_remote_port`, `server_protocol` e `args`.
- **Resource:** `service.name = gateway`, `service.namespace = smarkee`, `service.version` (a do APISIX), `deployment.environment.name` (decisão 0045, seção 4).
- **Destino:** `APISIX_OTEL_COLLECTOR_ADDRESS` (padrão `telemetry-gateway.smarkee.internal:4318`, na rede `internal`; para usar um coletor publicado no host, `host.docker.internal:4318`).
- **Conformidade no coletor, e não no gateway:** o fragmento `infrastructure/dev/telemetry-gateway/gateway-semconv.yaml` (processador `transform`, OTTL) renomeia, deriva e remove os atributos. O `telemetry-gateway` o mescla a `config.yaml` com um segundo `--config` e o usa na pipeline de traces, depois do `memory_limiter` e antes dos exporters (em outro coletor, antes do service graph e do tail sampling). Só age em spans do gateway (SDK `opentelemetry-lua`, `service.name = gateway`). **Não escrevo plugin Lua.**
- **Coletor do gateway (`telemetry-gateway`):** OpenTelemetry Collector contrib `0.163.1` (a imagem mais nova publicada em 2026-10-17), com receivers OTLP gRPC e HTTP só na rede `internal` (sem porta no host, para não colidir com a stack do desenvolvedor, que publica 4317 e 4318), `memory_limiter`, `batch` e o exporter `debug` (`detailed`) nas pipelines de métricas, logs e traces, até haver backend. Sem healthcheck do Compose (a imagem não tem shell); a extensão `health_check` responde em 13133.
- **Privacidade:** `url.query` mantém as chaves e redige todos os valores; `http.target` é removido. O gateway é a borda e não confia em `X-Forwarded-*` do cliente.

## Justificativa

- **Segurança:** a redação por padrão evita que códigos e tokens do OIDC cheguem ao armazenamento de traces; o span não usa cabeçalhos forjáveis.
- **Simplicidade:** a transformação fica num lugar só (o coletor), é declarativa e não exige código próprio no gateway; qualquer outro emissor Lua da mesma stack não é tocado.
- **Corretude:** verificado contra a semconv v1.44.0 (2026-10-17) com 41 regras: o plugin sem ajustes reprova 7 obrigatórias, 1 "deve", 7 recomendadas, 1 de propagação e 1 do projeto; com os ajustes, nenhuma. Detalhes e escopo da verificação em `docs/OBSERVABILITY.md` seção 11.
- **Alternativas:** (a) patch ou plugin Lua para emitir os nomes certos: vetado e frágil a cada atualização do APISIX; (b) deixar os nomes depreciados e a query como estão: reprova a semconv e vaza dados; (c) transformar no próprio gateway com `serverless-*`: não testada, e acoplada ao funcionamento interno do plugin.

## Consequências

- **Acoplamento:** a conformidade depende de o coletor de destino carregar o fragmento. Sem ele, os spans saem com os nomes depreciados, com `http.target` (query sem redação) e o `hostname` no `Resource`. É um pré-requisito de operação a verificar ao apontar o gateway para outro coletor (por exemplo, o otel-gateway da stack do desenvolvedor).
- **Desempenho e ruído:** o plugin é assíncrono (lotes); com o coletor parado, as requisições não sofrem (2 a 14 ms medidos), mas o gateway registra um `[error] request failed: connection refused` por lote.
- **Lista de plugins:** passa a ser versionada em `config.yaml`; ao atualizar o APISIX é preciso compará-la com a lista padrão da nova versão.
- **Riscos aceitos, a revisar:**
  - o endereço IP do cliente (`client.address`, `network.peer.address`) é dado pessoal e hoje vai nos spans (atributo recomendado da semconv); decidir se permanece, com base legal e retenção;
  - sem span de cliente para o upstream, o service graph não desenha a aresta gateway → componente; e os componentes ainda não extraem o `traceparent`, então o trace termina no gateway;
  - o `collector.address` do plugin é HTTP sem TLS (o APISIX avisa); em stg e prd, TLS e autenticação;
  - a verificação usou um coletor descartável e um validador não versionados; HTTP/2, HTTP/3, WebSocket e gRPC não foram cobertos;
  - o `service.version` do `adc.yaml` é manual e precisa acompanhar a imagem do APISIX.
- **Próximos passos fora desta decisão:** propagar o `traceparent` até o loop (extração nos Receivers, `trace_id` nos logs da decisão 0045), métricas `http.server.*`, e a validação de JWT no gateway.
