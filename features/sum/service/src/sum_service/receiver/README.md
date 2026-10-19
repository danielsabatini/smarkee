# sum-service-receiver

Receiver de `sum.service` (`sum-service-receiver`), um dos seis papéis da imagem única `sum-service` (decisão 0063; decisões 0015 e 0033), com processo e contêiner próprios. Veja o [README da feature](../../../README.md). É a API
`/v1/sum/services`: autentica o solicitante, confere a role da ação, publica o `requested` e responde. Não
decide nada: a decisão (catálogo, unicidade, versão) é do Manager.

O contrato descritivo da API é [`openapi.json`](openapi.json) (gerado, versionado e conferido por teste):
`uv run python -m sum_service.receiver.http.openapi > openapi.json` (na raiz da feature). A aplicação não expõe `/docs`, `/redoc` nem
`/openapi.json`.

## Rotas

| Rota | Efeito | Role |
|---|---|---|
| `POST /v1/sum/services` `{"service": "ipm"}` | liga o serviço (`202`, com `resourceId` e `operationId`) | `sum.<serviço>.enable` |
| `GET /v1/sum/services` | lista as ligações do solicitante cujo serviço ele pode ler (`limit` de 1 a 200) | `sum.<serviço>.get` |
| `GET /v1/sum/services/{resourceId}` | lê a ligação (`200`, ou `404` se não for dele) | `sum.<serviço>.get` |
| `DELETE /v1/sum/services/{resourceId}?resourceVersion=` | desliga (`202`) | `sum.<serviço>.disable` |
| `GET /v1/sum/services/{resourceId}/operations/{operationId}` | acompanha a Operation (só quem pediu) | dono |

O corpo do `POST` é o `ServiceCreateRequest`: só `service`; qualquer outro campo é recusado. O dono é sempre o `sub` do
token.

Erros, no formato `api-error`: `400` entrada inválida (sem repetir o valor enviado), `401` token ausente ou inválido, `403`
sem a role, `404` inexistente ou de outro dono, `409` serviço já ligado ou versão desatualizada, `422` reuso da
`Idempotency-Key`, `500` erro interno (`InternalError`, sem detalhe) e `503` recusa do transporte, com `Retry-After: 5`.

`Idempotency-Key` (1 a 128 caracteres): a mesma chave com o mesmo corpo devolve a operação já aceita; com outro corpo,
`422`. Logo depois do `202`, a leitura pode dar `404` até o Manager gravar a ligação e a Operation.

## Verificação do token

Assinatura pelas chaves do JWKS, `iss`, `exp` e `aud` (o projeto de roles do SUM, `roles-sum`). As roles vêm do
claim `urn:zitadel:iam:org:project:<roles-sum>:roles`: o cliente precisa pedir o escopo
`urn:zitadel:iam:org:projects:roles`. Token de outro projeto é `401` (`tests/unit/test_auth.py`).

## Estado

- Testado com dependências simuladas (`tests/unit/test_api.py`), a verificação de token (`tests/unit/test_auth.py`), o
  contrato (`tests/contract/`: modelos gerados e OpenAPI) e o repositório contra o banco de dev (`tests/integration/`).
- As respostas de sucesso e de erro são validadas contra os modelos do contrato (`test_api.py`, e no e2e contra os schemas).
- No ar no dev (Compose), atrás do gateway, verificado pela suíte e2e (`../../../tests/e2e`).
- Verificação de e-mail do solicitante: não decidida para o SUM (a Account exige).

## Configuração

`SUM_SERVICE_RECEIVER_<SEÇÃO>_<CAMPO>`. Obrigatórias: `AUTH_AUDIENCE` (ID do `roles-sum`),
`MESSAGING_PASSWORD` e `DATABASE_PASSWORD` (papel `sum_service_receiver_login`, só leitura das views).

## Testes

```bash
uv run pytest tests/receiver
uv run ruff check . && uv run pyright
```

O teste de integração do repositório pede `SUM_SERVICE_RECEIVER_TEST_DATABASE_URL` (papel do Receiver) e
`SUM_SERVICE_RECEIVER_TEST_MANAGER_URL` (papel do Manager, que grava e apaga a linha de teste).
