# ipm-role-api

API de `ipm.role` (`ipm-role-api`), um dos dois papéis da imagem única `ipm-role` (decisões 0063 e 0098), com processo e contêiner próprios. Veja o [README da feature](../../../README.md).

Recebe requisições HTTP da porta de borda (via gateway), autentica (Zitadel), autoriza por permissão e admite a escrita de forma síncrona numa transação do SSOT, gravando o recurso e o `desired` no outbox. Não há Operation: `POST` responde `201`, `PATCH` responde `200` e `DELETE` responde `202`, todos com o `Resource` completo.

`openapi.json` (na raiz da feature) é o contrato descritivo da API (gerado, versionado e conferido por teste): `uv run python -m ipm_role.api.http.openapi > openapi.json` (na raiz da feature).

## Comandos

Todos executados a partir de `features/ipm/organization`:

```shell
uv run ipm-role-api           # sobe a API (lê config.toml / variáveis de ambiente)
uv run ipm-role-api --help    # exibe opções e variáveis aceitas
uv run ipm-role-api --dry-run # valida configuração e conectividade sem subir o serviço
```

## Testes

```shell
uv run pytest tests/api       # testes unitários e de integração da API
```

## Deploy

Imagem: o `Dockerfile` da feature (imagem única; este papel roda com `command: ipm-role-api`). O contrato é verificado pelos testes e2e em `../../../tests/e2e`.
