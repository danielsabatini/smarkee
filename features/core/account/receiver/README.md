# core-account-receiver

Receiver de `core.account` (`core-account-receiver`), componente autocontido (`.decisions/0015-componentes-por-papel-autocontidos.md`).

Autentica e autoriza o solicitante, valida o pedido, gera as identidades (`resourceId`, `operationId`, `requestDigest`) e publica `requested`. Lê o SSOT somente pelas views `core.account_v1` e `core.account_operation_v1`. Não escreve no SSOT nem no provedor de identidade.

`openapi.json` é o contrato descritivo da API HTTP do Receiver (gerado, versionado e conferido por teste): `uv run python -m core_account_receiver.http.openapi > openapi.json`.

## Estrutura (decisão 0017)

```text
src/core_account_receiver/
  domain/      regras puras: Principal e roles, limite de taxa, digest e identidade da Operation, views, erros
  http/        FastAPI (app), portas dos adaptadores (ports.py) e OpenAPI
  auth/        validação do token (JWKS)
  store/       leitura das views do SSOT
  transport/   publicação de `requested` no NATS
  main.py
```

`tests/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador. Saúde (decisão 0018): `GET /health/live`, `/health/ready` (inclui o NATS) e `/health/startup`, só pela rede interna; o gateway publica apenas `/v1/core/accounts`.

## Configuração

Variáveis de ambiente `CORE_ACCOUNT_RECEIVER_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatórias, sem default: `CORE_ACCOUNT_RECEIVER_DATABASE_PASSWORD`, `CORE_ACCOUNT_RECEIVER_NATS_PASSWORD`, `CORE_ACCOUNT_RECEIVER_AUTH_AUDIENCE`. Os demais valores e defaults estão em `src/core_account_receiver/settings.py`.

## Desenvolvimento

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest        # os testes de integração exigem a stack de dev e são pulados sem ela
```

Imagem: `Dockerfile` (build com uv, execução sem privilégios). O contrato é verificado pelos testes e2e em `../tests/e2e`.
