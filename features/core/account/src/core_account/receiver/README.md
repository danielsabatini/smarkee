# core-account-receiver

Receiver de `core.account` (`core-account-receiver`), um dos seis papéis da imagem única `core-account` (decisão 0063), com processo e contêiner próprios. Veja o [README da feature](../../../README.md).

Autentica e autoriza o solicitante, valida o pedido, gera as identidades (`resourceId`, `operationId`, `requestDigest`) e publica `requested`. Lê o SSOT somente pelas views `core.account_v1` e `core.account_operation_v1`. Não escreve no SSOT nem no provedor de identidade.

`openapi.json` (na raiz da feature) é o contrato descritivo da API HTTP do Receiver (gerado, versionado e conferido por teste): `uv run python -m core_account.receiver.http.openapi > openapi.json` (na raiz da feature).

## Estrutura (decisão 0017)

```text
src/core_account/receiver/
  domain/      regras puras: Principal e roles, limite de taxa, digest e identidade da Operation, views, erros
  http/        FastAPI (app), dependências, publicação do `requested` (submission.py), probes e OpenAPI
  auth/        validação do token (JWKS)
  store/       leitura das views do SSOT
  transport/   publicação de `requested` no NATS
  main.py
```

`tests/common/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador. Saúde (decisão 0018): `GET /health/live`, `/health/ready` (inclui o NATS) e `/health/startup`, só pela rede interna; o gateway publica apenas `/v1/core/accounts`.

## Configuração

Variáveis de ambiente `CORE_ACCOUNT_RECEIVER_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatórias, sem default: `CORE_ACCOUNT_RECEIVER_DATABASE_PASSWORD`, `CORE_ACCOUNT_RECEIVER_MESSAGING_PASSWORD`, `CORE_ACCOUNT_RECEIVER_AUTH_AUDIENCE`. Os demais valores e defaults estão em `src/core_account/receiver/settings.py`.

## Desenvolvimento

```bash
# Na raiz da feature (features/core/account), que é o projeto único:
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/receiver  # os testes de integração exigem a stack de dev e são pulados sem ela
```

Imagem: o `Dockerfile` da feature (imagem única; este papel roda com `command: core-account-receiver`). O contrato é verificado pelos testes e2e em `../../../tests/e2e`.
