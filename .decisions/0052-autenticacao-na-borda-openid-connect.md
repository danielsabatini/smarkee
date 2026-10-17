# 0052 — Autenticação do token na borda: plugin `openid-connect` do APISIX

- **Data:** 2026-10-17
- **Status:** Aceita e implementada em desenvolvimento (`infrastructure/dev/gateway`). Origem: a validação de JWT no gateway, adiada em 2026-10-16 (o `jwt` do Kong OSS não cobria) e desbloqueada pela decisão 0049.

## Contexto

Os Receivers validam o token (RS256 pelo JWKS do Zitadel, `iss`, `aud` = ID do projeto de roles do módulo, `exp`, `sub`) e decidem as roles. Pedidos sem token ou com token inválido chegavam até eles. Com o APISIX, o plugin `openid-connect` pode recusar esses pedidos já na porta de entrada, sem depender do código dos componentes.

## Decisão

- **Onde:** nas três rotas de API que exigem identidade: `core-account-receiver` (todos os métodos de `/v1/core/accounts`, exceto o `POST` anônimo, e `/v1/core/accounts/*`), `ipm-organization-receiver` e `sum-service-receiver`. **Continuam públicas** as rotas do Zitadel (`identity`, `identity-login`) e o cadastro (`core-account-register`, `POST /v1/core/accounts`, decisão 0014).
- **O que valida:** token `Bearer` (`bearer_only`), assinatura RS256 pelo JWKS do discovery do Zitadel (`use_jwks`; outros algoritmos, `none` e HS256 são recusados), emissor `http://ipm-dev.smarkee.com.br:8080`, expiração, e, por `claim_schema`, a presença de `sub`, `exp`, `iss` e `aud` e a **audiência do módulo** (`aud` string ou lista contendo o ID do projeto de roles). O gateway **só autentica**: roles e dono continuam nos Receivers, que repetem a validação (defesa em profundidade).
- **Audiência por variável:** `APISIX_AUTH_AUDIENCE_CORE_ACCOUNT`, `_IPM_ORGANIZATION` e `_SUM_SERVICE` em `gateway/.env`, iguais aos `*_AUTH_AUDIENCE` dos Receivers (o ID muda a cada instância do Zitadel). O padrão é `nao-configurada`, que não casa com nenhum token: a API **falha fechada**, e as rotas do Zitadel seguem no ar para que o ID possa ser obtido (por isso a variável não é obrigatória para subir).
- **Discovery pelo endereço público:** o Zitadel escolhe a instância pelo `Host`, e o issuer é `http://ipm-dev.smarkee.com.br:8080`. O `gateway` ganha o alias de rede `ipm-dev.smarkee.com.br` (dentro da rede aponta para ele mesmo) e atende também a porta `8080`, que encaminha ao Zitadel pela rota `identity`.
- **Cabeçalhos:** o plugin não acrescenta `X-Access-Token`, `X-ID-Token` nem `X-Userinfo` (desligados); o `Authorization` segue ao Receiver, e os cabeçalhos desse tipo enviados pelo cliente são removidos.
- **`401` no contrato:** o `401` do plugin vem sem corpo. Um `response-rewrite` condicionado a `status == 401` **e** à presença de `WWW-Authenticate` (que só o plugin envia) devolve o `ApiError` (`{"errorCode":"Unauthorized","message":"Token ausente ou inválido."}`, `application/json`) e fixa `WWW-Authenticate: Bearer realm="smarkee"`, sem `error_description`. O `401` do próprio Receiver passa intacto. O motivo detalhado fica só no log do gateway.
- **Cache do JWKS:** `jwk_expires_in: 3600`.

## Justificativa

- **Segurança:** pedido sem identidade válida não chega aos componentes; token de outro projeto da mesma instância é recusado na borda; a mensagem ao cliente não repete o que ele enviou nem falhas internas.
- **Simplicidade:** configuração declarativa no `adc.yaml`, sem código novo; a política de roles não é duplicada no gateway.
- **Contrato:** o `401` do gateway é indistinguível, para o cliente e para as suítes e2e, do `401` do Receiver (`test_missing_token_is_401_with_the_error_contract`).
- **Alternativas:** (a) validar também as roles no gateway por `claim_schema`: duplicaria a política dos Receivers; (b) introspecção no Zitadel: exige credencial de cliente no gateway e uma chamada por pedido; (c) usar `claim_validator.audience`: devolve `403` para audiência errada (o Receiver devolve `401`).

## Verificação (2026-10-17)

- Num APISIX 3.19.0 descartável com um IdP falso (mesmo formato de issuer com porta): 23 casos, entre eles sem token, `aud` como string e como lista, módulo errado, `aud`/`sub`/`exp` ausentes, expirado, `iss` errado ou sem porta, `kid` desconhecido ou trocado, chave fora do JWKS, HS256, `alg=none`, rota anônima, `401` do upstream preservado e cabeçalhos recebidos pelo upstream. Todos conforme o esperado, exceto `nbf` no futuro, que o plugin aceita (abaixo); a tolerância de ~10 s para `exp` é a mesma do Receiver.
- No dev real: a jornada e2e com a CLI real (`tests/e2e`: cadastro, ativação, `sk auth login`, SUM, Organization, renovação de sessão, remoção) passou **12 de 12** com os tokens de usuário validados pelo gateway; as suítes de conformidade das três features mantêm os resultados anteriores (8, 7 e 8 aprovados); um token real do Zitadel (service account) com a audiência errada foi recusado nas três rotas, **só** por `aud`; sem token e com token inválido, `401` no contrato nas três rotas; cadastro anônimo, Zitadel e login seguem públicos.
- Zitadel parado e gateway reiniciado a frio: `401` (falha fechada); o gateway se recupera sozinho cerca de 16 s depois que o Zitadel volta.

## Consequências

- **Diferenças em relação ao Receiver:** o gateway **não verifica `nbf`**; aceita um token expirado há até ~10 s (a mesma folga do Receiver). Os Receivers continuam sendo a validação completa.
- **Validação local:** token de usuário desativado ou com sessão encerrada vale até o `exp` (15 minutos). Uma chave retirada do JWKS deve valer por até 1 h (cache; não medido).
- **Busca de JWKS por `kid` desconhecido:** o plugin busca o JWKS a cada token com `kid` desconhecido, sem o intervalo mínimo de 30 s que o Receiver aplica. Quem não tem conta consegue gerar essa busca ao ritmo dos próprios pedidos; o Zitadel já é público pelo gateway, então o risco é aceito.
- **Dependência do Zitadel na partida:** com o Zitadel fora, as rotas autenticadas respondem `401` para todos até o discovery voltar.
- **Alias de rede:** todo contêiner da rede `internal` passa a resolver `ipm-dev.smarkee.com.br` para o gateway, e a porta interna `8080` precisa seguir igual à `ZITADEL_EXTERNALPORT`.
- **Configuração duplicada:** o ID de cada projeto agora está no `.env` do Receiver e no do gateway; a divergência faz o módulo rejeitar tudo (falha fechada, visível). A suíte `identity/conformance` ainda não confere o `gateway/.env`.
- **Discovery sem TLS:** o plugin avisa no log; em stg e prd, HTTPS.
- **Fora do escopo:** roles no gateway, limite de taxa nas rotas autenticadas, `real-ip` atrás de balanceador.
