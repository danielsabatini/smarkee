# 0053 — Telemetria separada em infra e app, logs da plataforma, limites de recursos e rotas do Zitadel

- **Data:** 2026-10-17
- **Status:** Aceita e implementada em desenvolvimento. Estende as decisões 0050 e 0051.
- **Origem:** a avaliação de observabilidade de 2026-10-17, feita sobre dados reais de uma rodada completa (jornada com a CLI real e as três suítes de conformidade) e de 1 h 49 min de métricas.

## Contexto

A avaliação mostrou que a coleta era confiável, mas pouco útil para analisar: 74% dos logs retidos eram `GET /health/ready` de um único serviço; os contêineres da plataforma (`broker`, `database`, `identity`, `gateway`...) não tinham logs coletados; infra e aplicação estavam misturadas; os arquivos de 5 MB guardavam pouco; nenhum contêiner tinha limite (todos mostravam 19,5 GiB, o total do host); e o `http.route` de todo o Zitadel era `/*`.

## Decisão

- **Separação em infra e app, feita pelo `telemetry-gateway`.** Quatro pipelines a partir do mesmo receptor OTLP, cada uma com um `filter`:
  - **logs de app:** os que trazem `smarkee.component.role` (obrigatório no contrato 0045); **logs de infra:** os demais;
  - **métricas de infra:** nome com prefixo `container.`, `system.`, `process.` ou `k8s.`; **métricas de app:** o resto (ainda nenhuma: os componentes não emitem métricas próprias);
  - **traces:** um só destino (todo span é de aplicação).
- **Arquivos** em `infrastructure/dev/telemetry-gateway/logs/{app,infra}`, `metrics/{app,infra}` e `traces/`, com rotação em **10 MB** (3 rotacionados, 1 dia), até 40 MB por arquivo de sinal.
- **Healthchecks descartados no `telemetry-agent`**, antes de saírem dele: `GET|HEAD /health/{live,ready,startup}`, `/healthz`, `/readyz`, `/livez` e a linha do healthcheck da Admin API do APISIX.
- **Logs da plataforma coletados.** Os contêineres de longa duração da plataforma (`broker`, `database`, `identity`, `identity-login`, `gateway`, `gateway-etcd`, `mail`, `telemetry-gateway`, `telemetry-agent`) passam ao driver `json-file` com rotação e as labels `com.docker.compose.service` (vira `service.name`) e `smarkee.layer=infra` (gate: contêineres de outros projetos do host, mesmo com a label do compose, ficam sem identidade e são descartados). A severidade é extraída por cinco padrões (logfmt e JSON, NATS, PostgreSQL, nginx e o formato do Collector). **Política enxuta inicial para infra:** só `WARN` ou acima (ou sem nível reconhecido), sem as linhas de acesso do nginx; os logs de aplicação ficam inteiros. O agente não encaminha os próprios logs.
- **Limites de recursos** (`deploy.resources.limits`, com variáveis de ambiente e padrão): componentes das features 0,5 CPU e 256 MiB (`<MÓDULO>_<TIPO>_COMPONENT_CPUS` e `_MEMORY`); `database` e `identity` 1,0 CPU e 512 MiB; `identity-login` 0,5 CPU e 512 MiB; `gateway` 1,0 CPU e 384 MiB; `gateway-etcd`, `broker` 0,5 CPU e 256 MiB; `mail` 0,25 CPU e 256 MiB; os dois coletores 0,5 CPU e 384 MiB (o `memory_limiter` de 256 MiB fica abaixo do limite do contêiner). Os valores saem do consumo medido (pico de memória × ~2).
- **Rotas do Zitadel nomeadas por função**, para o `http.route` dos spans ser informativo: `identity-oidc` (`/.well-known/*`, `/oauth/v2/*`, `/oidc/v1/*`), `identity-login-v1` (`/ui/login*`), `identity-console` (`/ui/console*`), além da `identity-login` (`/ui/v2/login*`). A rota `identity` (`/*`) continua como retaguarda, para nada deixar de funcionar; o `proxy-rewrite` do `x-zitadel-public-host` passou ao serviço.

## Justificativa

- **Corretude e análise:** sem o ruído, o log de app passou de 74% de healthcheck para 0%; infra e app separados deixam cada arquivo com um assunto; 10 MB guardam mais de cem rodadas e cerca de 4 horas de métricas (medido: ~9 MB/h).
- **Segurança:** o gate por label evita ingerir contêineres de outros projetos; os limites impedem que um componente consuma o host inteiro.
- **Simplicidade:** nenhuma ferramenta nova; a separação é configuração do coletor.

## Verificação (2026-10-17)

- Dados sintéticos de log de app e de infra e de métrica `container.*` e de aplicação foram para o arquivo certo, e só para ele.
- Depois de recriar a plataforma e os 18 componentes: jornada com a CLI real **12 de 12** e conformância 8, 7 e 8 aprovadas, sob os limites. Os 27 contêineres têm o limite em vigor (`docker inspect`). Pior uso de memória: **36%** do limite (`identity`, 186 de 512 MiB); nenhum OOM nem reinício.
- Healthchecks: **0** nos logs de app (eram 2251 de 3037). Logs de infra com `service.name` de `database`, `broker`, `mail`, `gateway`, `gateway-etcd`, `identity` e `identity-login`; nenhum serviço de fora.
- Spans do Zitadel com `http.route` `/.well-known/*`, `/oauth/v2/*`, `/oidc/v1/*` e `/ui/login/*`; nenhum caiu em `/*`.

## Consequências

- **Throttling de CPU nos componentes é causado pelo healthcheck.** Cada `python -c` do healthcheck (a cada 10 s) estoura a cota de 50 ms de um período de 100 ms e leva 2 períodos de throttling: 3 execuções × 2 = 6 por 30 s, medido, com o contêiner usando só 0,01 núcleo. Atrasa apenas o próprio healthcheck. Manter 0,5 CPU como teto real; subir para 1,0 elimina o efeito, se incomodar.
- **Ruído de infra ainda alto, e benigno:** 78% dos 843 registros de infra são `WARN` do Zitadel: `token verifier repo: decrypt access token` (466; ele tenta decifrar como opaco um token que é JWT antes de verificá-lo como JWT) e `Usuário não pôde ser encontrado` (194; os Observers consultando usuários que não existem). Mantidos por ora; filtrar por mensagem ou baixar o nível de log do Zitadel é decisão pendente. O etcd também registra, na partida, 103 `failed to publish local member to cluster through raft`.
- `metrics/app` fica vazio até os componentes emitirem métricas próprias.
- Os contêineres da plataforma foram recriados (driver de log e limites); os dados estão em volumes.
- Os padrões de healthcheck e de severidade são heurísticas sobre o texto dos logs de cada software; uma troca de versão pode exigir ajuste.
- Os limites são de dev; stg e prd definem os próprios (requests e limits do Kubernetes).
