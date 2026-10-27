# ipm-organization-receiver

Receiver de `ipm.organization` (`ipm-organization-receiver`), um dos quatro papéis da imagem única `ipm-organization` (decisões 0063 e 0096), com processo e contêiner próprios. Veja o [README da feature](../../../README.md).

Autentica e autoriza o solicitante, valida o pedido, gera as identidades (`resourceId`, `operationId`, `requestDigest`) e publica `requested`. Lê o SSOT somente pelas views `ipm.organization_v1` e `ipm.organization_operation_v1`. Não escreve no SSOT nem no provedor de identidade.

`openapi.json` (na raiz da feature) é o contrato descritivo do Receiver (gerado, versionado e conferido por teste): `uv run python -m ipm_organization.receiver.http.openapi > openapi.json` (na raiz da feature).

## Configuração

Variáveis de ambiente `IPM_ORGANIZATION_RECEIVER_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatórias, sem default: `IPM_ORGANIZATION_RECEIVER_DATABASE_PASSWORD`, `IPM_ORGANIZATION_RECEIVER_MESSAGING_PASSWORD`, `IPM_ORGANIZATION_RECEIVER_AUTH_AUDIENCE`. Os demais valores e defaults estão em `src/ipm_organization/receiver/settings.py`.

## Desenvolvimento

```bash
# Na raiz da feature (features/ipm/organization), que é o projeto único:
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/receiver  # os testes de integração exigem a stack de dev e são pulados sem ela
```

Imagem: o `Dockerfile` da feature (imagem única; este papel roda com `command: ipm-organization-receiver`). O contrato é verificado pelos testes e2e em `../../../tests/e2e`.
