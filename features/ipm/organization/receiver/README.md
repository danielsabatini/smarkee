# ipm-organization-receiver

Receiver de `ipm.organization` (`ipm-organization-receiver`), componente autocontido (`.decisions/0015-componentes-por-papel-autocontidos.md`).

Autentica e autoriza o solicitante, valida o pedido, gera as identidades (`resourceId`, `operationId`, `requestDigest`) e publica `requested`. Lê o SSOT somente pelas views `ipm.organization_v1` e `ipm.organization_operation_v1`. Não escreve no SSOT nem no provedor de identidade.

`openapi.json` é o contrato descritivo do Receiver (gerado, versionado e conferido por teste): `uv run python -m ipm_organization_receiver.http.openapi > openapi.json`.

## Configuração

Variáveis de ambiente `IPM_ORGANIZATION_RECEIVER_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatórias, sem default: `IPM_ORGANIZATION_RECEIVER_DATABASE_PASSWORD`, `IPM_ORGANIZATION_RECEIVER_NATS_PASSWORD`, `IPM_ORGANIZATION_RECEIVER_AUTH_AUDIENCE`. Os demais valores e defaults estão em `src/ipm_organization_receiver/settings.py`.

## Desenvolvimento

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest        # os testes de integração exigem a stack de dev e são pulados sem ela
```

Imagem: `Dockerfile` (build com uv, execução sem privilégios). O contrato é verificado pelos testes e2e em `../tests/e2e`.
