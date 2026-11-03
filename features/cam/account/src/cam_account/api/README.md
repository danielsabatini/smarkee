# cam-account-api

API de `cam.account` (`cam-account-api`), um dos três papéis da imagem única `cam-account` (decisões 0063, 0096, 0098 e 0100), com processo e contêiner próprios. Veja o [README da feature](../../../README.md) e o [fluxo de dados](../../../docs/CAM-ACCOUNT-DATA-FLOW.md).

Recebe requisições HTTP da porta de borda (via gateway), autentica (Zitadel, JWKS), autoriza por permissão e admite a escrita de forma síncrona numa transação do SSOT, gravando o recurso e o `desired` no outbox. Não há Operation:

- `POST /v1/cam/accounts` (**anônimo**, auto-cadastro) responde `202` com `{resourceId}`, igual exista ou não o e-mail;
- `PATCH` responde `200` e `DELETE` responde `202`, ambos com o `Resource` completo.

A exclusão segura (decisões 0040 e 0100) usa **projeções locais** do Stream `DESIRED` (`ipm.organization`, `bsm.account` e `sum.service`, por `ownerAccountId`), mantidas por `transport/attached_projection.py`: a API não chama outras APIs.

`openapi.json` (na raiz da feature) é o contrato descritivo da API (gerado, versionado e conferido por teste): `uv run python -m cam_account.api.http.openapi > openapi.json` (na raiz da feature).

## Estrutura

```text
src/cam_account/api/
  auth/        validação do token (JWKS)
  domain/      regras puras: conta, admissão, anexos, limite de taxa, visão (Resource)
  http/        rotas, admissão, OpenAPI e saúde
  store/       único código com SQL da API (repositório e admissão)
  transport/   projeções do DESIRED para a exclusão segura
  settings.py
  main.py
```

## Comandos

Todos executados a partir de `features/cam/account`:

```shell
uv run cam-account-api           # sobe a API (lê config.toml / variáveis de ambiente)
uv run cam-account-api --help    # exibe opções e variáveis aceitas
uv run cam-account-api --dry-run # valida configuração e conectividade sem subir o serviço
```

## Testes

```shell
uv run pytest tests/api       # testes unitários, de contrato e de integração da API
```

## Deploy

Imagem: o `Dockerfile` da feature (imagem única; este papel roda com `command: cam-account-api`). O contrato é verificado pelos testes e2e em `../../../tests/e2e`.
