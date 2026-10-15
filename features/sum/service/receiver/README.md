# sum-service-receiver

Receiver de `sum.service` (`sum-service-receiver`), componente autocontido (decisões 0015 e 0033). É a API
`/v1/sum/services`: autentica o solicitante, confere a role da ação, publica o `requested` e responde. Não
decide nada: a decisão (catálogo, unicidade, versão) é do Manager.

## Rotas

| Rota | Efeito | Role |
|---|---|---|
| `POST /v1/sum/services` `{"service": "ipm"}` | liga o serviço (`202`, com `resourceId` e `operationId`) | `sum.<serviço>.enable` |
| `GET /v1/sum/services` | lista as ligações do solicitante cujo serviço ele pode ler | `sum.<serviço>.get` |
| `GET /v1/sum/services/{resourceId}` | lê a ligação (`200`, ou `404` se não for dele) | `sum.<serviço>.get` |
| `DELETE /v1/sum/services/{resourceId}?resourceVersion=` | desliga (`202`) | `sum.<serviço>.disable` |
| `GET /v1/sum/services/{resourceId}/operations/{operationId}` | acompanha a Operation (só quem pediu) | dono |

`Idempotency-Key` (1 a 128 caracteres): a mesma chave com o mesmo corpo devolve a operação já aceita; com outro
corpo, `422`. Recusa do transporte ao publicar: `503` com `Retry-After: 5`.

## Verificação do token

Assinatura pelas chaves do JWKS, `iss`, `exp` e `aud` (o projeto de roles do SUM, `roles-sum`). As roles vêm do
claim `urn:zitadel:iam:org:project:<roles-sum>:roles`. Token de outro projeto é `401`
(`tests/unit/test_auth.py`).

## Estado

- Testado com dependências simuladas (`tests/unit/test_api.py`, 21 testes), a verificação de token
  (`tests/unit/test_auth.py`) e o repositório contra o banco de dev (`tests/integration/`, com as variáveis).
- Verificado no dev, com o processo no host, contra o banco, o NATS e o Zitadel reais: ligar, repetir com a
  mesma chave, `422` com outro corpo, ler, listar, acompanhar a operação, as três recusas de desligamento e o
  desligamento com a versão lida. A ligação terminou `absent`, geração 2, versão 2.
- Não verificado: o contêiner e a rota pelo gateway com o Receiver no ar (a rota `/v1/sum/services` existe no
  gateway e responde `503` sem o processo). Verificação de e-mail do solicitante: não decidida para o SUM.

## Configuração

`SUM_SERVICE_RECEIVER_<SEÇÃO>_<CAMPO>`. Obrigatórias: `AUTH_AUDIENCE` (ID do `roles-sum`),
`NATS_PASSWORD` e `DATABASE_PASSWORD` (papel `sum_service_receiver_login`, só leitura das views).

## Testes

```bash
uv run pytest
uv run ruff check . && uv run pyright
```
