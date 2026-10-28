# sum-service-api

API de `sum.service` (`sum-service-api`), um dos três papéis da imagem única `sum-service` (decisões 0033, 0063, 0096, 0098 e 0100), com processo e contêiner próprios. Veja o [README da feature](../../../README.md) e o [fluxo de dados](../../../docs/SUM-SERVICE-DATA-FLOW.md).

Recebe requisições HTTP da porta de borda (via gateway), autentica (Zitadel, JWKS), autoriza por permissão `sum.<serviço>.<ação>` e admite a escrita de forma síncrona numa transação do SSOT, gravando a ligação e o `desired` no outbox. Não há Operation:

- `POST /v1/sum/services` liga um serviço e responde `201` com o `Resource`;
- `DELETE /v1/sum/services/{resourceId}?resourceVersion=…` desliga e responde `202` com o `Resource`;
- `GET` lista e lê as ligações do solicitante (de outro dono é `404`).

O recurso é o par dono + serviço: ligar de novo um par desligado reaproveita o recurso, com uma geração nova; ligar o par já ligado é `409 AlreadyEnabled`. Serviço fora do catálogo é `409 ServiceNotAvailable`.

As pré-condições usam **projeções locais** do Stream `DESIRED`, mantidas por `transport/attached_projection.py` (a API não chama outras APIs, decisão 0100): ligar exige uma Billing Account do dono (`bsm.account`, decisão 0082) e desligar `ipm` exige que o dono não tenha Organizations (`ipm.organization`, decisão 0040). Antes da primeira sincronização das projeções a API responde `503 ProjectionSyncPending`.

`openapi.json` (na raiz da feature) é o contrato descritivo da API (gerado, versionado e conferido por teste): `uv run python -m sum_service.api.http.openapi > openapi.json` (na raiz da feature).

## Estrutura

```text
src/sum_service/api/
  auth/        validação do token (JWKS)
  domain/      regras puras: admissão, ligação, anexos, requisições, visão (Resource)
  http/        rotas, admissão, OpenAPI e saúde
  store/       único código com SQL da API (repositório e admissão)
  transport/   projeções do DESIRED (Organizations e Billing Accounts)
  settings.py
  main.py
```

## Comandos

Todos executados a partir de `features/sum/service`:

```shell
uv run sum-service-api           # sobe a API (lê config.toml / variáveis de ambiente)
uv run sum-service-api --help    # exibe opções e variáveis aceitas
uv run sum-service-api --dry-run # valida configuração e conectividade sem subir o serviço
```

## Testes

```shell
uv run pytest tests/api       # testes unitários, de contrato e de integração da API
```

## Deploy

Imagem: o `Dockerfile` da feature (imagem única; este papel roda com `command: sum-service-api`). O contrato é verificado pelos testes e2e em `../../../tests/e2e`.
