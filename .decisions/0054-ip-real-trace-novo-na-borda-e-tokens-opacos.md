# 0054 — IP real do cliente, trace novo na borda e tokens opacos nas contas de serviço

- **Data:** 2026-10-18
- **Status:** Aceita e implementada em desenvolvimento. Estende as decisões 0050, 0052 e 0053.
- **Origem:** itens em aberto da avaliação de observabilidade de 2026-10-17, ordenados por segurança → simplicidade → robustez → resiliência.

## Contexto

- O gateway enxerga como cliente o IP do último salto (em dev, o NAT do Docker, `172.27.0.1`). Atrás de um balanceador em stg/prd, todos os clientes pareceriam um só: o `limit-count` do cadastro (por IP) limitaria todos juntos e os spans trariam o IP do balanceador.
- O `traceparent` e o `tracestate` que o cliente envia eram repassados ao `opentelemetry` (sampler `parent_base`): um cliente externo escolheria o `trace_id` e a decisão de amostragem dos nossos traces.
- As contas de serviço dos componentes usavam token JWT. O Zitadel tenta decifrar como opaco todo token que chega e registra um `WARN` (`token verifier repo: decrypt access token`) a cada chamada autenticada: era a maior parte do ruído de infra.

## Decisão

- **IP real pelo plugin `real-ip`** (regra global, prioridade 23000), lendo `X-Forwarded-For` com `recursive: true` e confiando somente em `APISIX_TRUSTED_PROXIES`: **um IP ou um CIDR** (o APISIX recebe uma única string). **Em dev fica vazio** (vira `127.0.0.1`, isto é, não confia em ninguém), porque o NAT do Docker não deixa recuperar o IP real e confiar nele permitiria forjar o `X-Forwarded-For` para fugir do limite do cadastro. Em stg/prd define-se o CIDR do balanceador. O IP do salto direto continua nos atributos `realip_remote_addr` e `realip_remote_port` do span.
- **A borda inicia um trace novo.** Regra global `proxy-rewrite` (prioridade 20000, depois do `real-ip` e antes do `opentelemetry`) remove `traceparent` e `tracestate` da requisição. O trace nasce no gateway; o que o cliente enviar é ignorado.
- **Tokens opacos (Bearer) nas seis contas de serviço dos componentes** (`*-executor` e `*-observer`). O `platform-bootstrap` continua JWT: é usado só no provisionamento. A suíte de conformidade do Zitadel passa a verificar o tipo (ausência de `machine.accessTokenType` na API v2 significa Bearer).

## Justificativa

- **Segurança:** o cliente não controla o `trace_id` nem a amostragem; a confiança em `X-Forwarded-For` é explícita e restrita; o padrão em dev é o mais seguro.
- **Simplicidade:** dois plugins nativos e uma variável de ambiente; sem filtrar `WARN` no coletor, que esconderia problema real.
- **Robustez:** o rate limit por IP passa a valer por cliente real atrás de um balanceador.

## Verificação (2026-10-18)

- `traceparent`, `tracestate` e `X-Forwarded-For` forjados foram ignorados nas rotas da API, do Zitadel e em rota sem correspondência. Com o par confiável, `client.address` ficou com o IP real, o salto direto foi preservado e o limite do cadastro passou a contar por IP real.
- Jornada com a CLI real 12 de 12; conformância 8, 7 e 8; conformância do Zitadel 20 de 20 (com o teste novo).
- Cinco chamadas com token Bearer geraram 0 `WARN` de `decrypt access token` (com JWT, 1 por chamada).

## Consequências

- Em stg/prd, `APISIX_TRUSTED_PROXIES` precisa ser definida; se vier errada, ou o IP fica o do balanceador (vazio) ou, pior, confia-se em quem não deve (CIDR largo demais).
- **Achado:** os `WARN` "Usuário não pôde ser encontrado" eram os Observers consultando, a cada ciclo, usuários já removidos: no stream DESIRED o último estado do recurso é retido (`lifecycle: absent`) e continua sendo observado. Não há limpeza dessas lápides; fica como pendência.
- Mudar o tipo de token da conta é um passo manual do provisionamento (README de infra), não um script versionado.
