# 0051 — `telemetry-agent`: coleta de logs e métricas de contêiner em dev

- **Data:** 2026-10-17
- **Status:** Aceita e implementada em desenvolvimento (`infrastructure/dev/telemetry-agent`). stg e prd são direção a definir.
- **Origem:** decisão 0045 (contrato de logs), seção 7 de `docs/OBSERVABILITY.md`, e a decisão 0050 (`telemetry-gateway`).

## Contexto

Os 18 componentes escrevem uma linha JSON por registro no stdout (decisão 0045), mas ninguém as lia: o destino para a telemetria (`telemetry-gateway`) já existia e só recebia os spans do gateway. Era preciso coletar os logs dos componentes e as métricas dos contêineres e levá-los ao `telemetry-gateway`, que por ora os grava em arquivos (exporter `file`, com rotação).

A stack de observabilidade do desenvolvedor (`lgtm-stack-otel/otel-agent`) já faz essa coleta para o projeto dela, com `host_metrics`, `docker_stats` e `file_log`, e serviu de base.

## Decisão

- **Serviço `telemetry-agent`** em `infrastructure/dev`, com o Collector contrib `0.163.1` (a mesma imagem do `telemetry-gateway`), na rede `internal`, sem porta no host, enviando OTLP/gRPC a `telemetry-gateway.smarkee.internal:4317` (`TELEMETRY_GATEWAY_ENDPOINT`).
- **Métricas:** `docker_stats` (somente CPU, memória e rede, a política enxuta do otel-agent), só dos contêineres `*.smarkee.internal`. Sem `host_metrics`: isso exigiria montar o sistema de arquivos do host, e o pedido é por dados do Docker.
- **Logs:** `file_log` sobre `/var/lib/docker/containers/*/*-json.log` com a posição guardada em volume (`file_storage`). O pipeline do contrato 0045 §7 foi refeito com ajustes descobertos na verificação (abaixo). Tudo que não tem `service.namespace = smarkee` (outros projetos do host, texto puro, JSON de terceiros) é descartado no próprio agente.
- **Hardening:** `cap_drop: [ALL]` e `no-new-privileges`. Roda como root, só para ler os arquivos de log (0600 do root) e o socket do Docker.

## Justificativa

- **Corretude:** a verificação com um contêiner de teste mostrou que mexer no `Resource` e no escopo no `transform` altera o do lote inteiro (o `file_log` os agrupa por arquivo): uma linha de outro namespace fez uma linha boa herdar a identidade errada e ser descartada, e um contêiner reiniciado, que mantém o arquivo de log com outro `service.instance.id`, teria as linhas antigas rotuladas com a instância nova. Por isso o `Resource` (8 chaves, o conjunto fechado do schema) e o escopo (`scope_name`) são movidos por registro no `file_log`. Também: `parse_ints` (senão `code.line.number` vira `double`) e `on_error: send_quiet`.
- **Simplicidade:** a imagem oficial, uma configuração, nenhum código próprio; reaproveita o desenho do otel-agent do desenvolvedor.
- **Alternativas:** (a) deixar `docker compose logs` e nada mais: não leva métricas nem logs ao `telemetry-gateway`; (b) um driver de log do Docker que fale OTLP: não existe de forma estável; (c) cada componente enviar OTLP direto: contraria a decisão 0045 (o componente não depende do coletor).

## Consequências

- **Superfície:** o socket do Docker montado como leitura ainda dá acesso à API inteira do Docker, e o agente roda como root. Aceitável em dev; **não** se repete em stg e prd (lá, um DaemonSet lê os logs do nó, no formato CRI, sem o socket).
- **Cobertura de logs:** só os contêineres que usam o driver `json-file` e escrevem a linha do contrato. Os da plataforma (`broker`, `database`, `identity`, `gateway`, `mail`) usam o driver padrão do Docker Desktop, que o `file_log` não lê, e não escrevem o formato do contrato; ficam de fora. Suas métricas de contêiner entram.
- **Volume:** o `telemetry-gateway` grava tudo em arquivos de 5 MB com 3 rotacionados por sinal; com todos os níveis (INFO inclusive) o volume é alto, e a janela guardada é limitada. Medido em 2026-10-17, uma rodada completa (a jornada com a CLI real mais as três suítes de conformidade, 160 s) grava cerca de 0,42 MB de logs, 0,38 MB de métricas e 0,19 MB de traces; as métricas, cerca de 75 KB a cada 30 s (uns 9 MB por hora). Com 5 MB por arquivo e 3 rotacionados (até 20 MB por sinal), isso guarda dezenas de rodadas de logs e traces e cerca de 2 horas de métricas. O tamanho inicial de 1 MB guardava só duas rodadas, pouco para analisar com precisão. O otel-agent do desenvolvedor descarta INFO e DEBUG; aqui não, porque o objetivo é ler.
- **Sem laço:** o agente lê o próprio log e o do `telemetry-gateway`, mas são texto do Collector (não JSON com `service.namespace = smarkee`) e são descartados.
- **Riscos aceitos, a revisar:** o formato CRI (Kubernetes) não foi testado; o campo `container.id` vem do caminho do arquivo; o OTLP entre os coletores é sem TLS; `trace_id` e `span_id` foram testados só com uma linha sintética, pois os componentes ainda não os emitem.
