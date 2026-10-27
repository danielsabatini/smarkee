# ipm-user-receiver

Receiver de `ipm.user` (`ipm-user-receiver`), um dos quatro papéis da imagem única `ipm-user` (decisões 0063 e 0096), com processo e contêiner próprios. Veja o [README da feature](../../../README.md).

Autentica e autoriza o solicitante, valida o pedido, gera as identidades (`resourceId`, `operationId`, `requestDigest`) e publica `requested`. Lê o SSOT somente pelas views `ipm.user_v1` e `ipm.user_operation_v1`. Não escreve no SSOT nem no provedor de identidade.

Escopo por Organization (decisão 0077): o operador (`ipm.user.admin`) age em qualquer uma; um usuário da Organization é reconhecido pelo próprio registro no SSOT do tipo; o dono (root) é confirmado pelo Receiver da Organization, com o token de quem pede (`transport/organizations.py`, decisão 0040). As roles pedidas precisam estar no catálogo `grantableRole` do contrato (decisão 0081) e, sem `ipm.user.bind`, entre as do próprio solicitante (`domain/access.py`). A cota de usuários por Organization é `api.user_quota`. Todo usuário lê o próprio registro sem role (`GET /v1/ipm/users/{sub}`): é por ele que o Receiver da Organization reconhece os usuários dela.

`openapi.json` (na raiz da feature) é o contrato descritivo do Receiver (gerado, versionado e conferido por teste): `uv run python -m ipm_user.receiver.http.openapi > openapi.json` (na raiz da feature).

## Configuração

Variáveis de ambiente `IPM_USER_RECEIVER_<SEÇÃO>_<CAMPO>` e o `config.toml` da feature. Obrigatórias, sem default: `IPM_USER_RECEIVER_DATABASE_PASSWORD`, `IPM_USER_RECEIVER_MESSAGING_PASSWORD`, `IPM_USER_RECEIVER_AUTH_AUDIENCE`. Todos os campos estão em [`docs/CONFIGURATION.md`](../../../docs/CONFIGURATION.md).

## Desenvolvimento

```bash
# Na raiz da feature (features/ipm/user), que é o projeto único:
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/receiver  # os testes de integração exigem a stack de dev e são pulados sem ela
```

Imagem: o `Dockerfile` da feature (imagem única; este papel roda com `command: ipm-user-receiver`). O contrato é verificado pelos testes e2e em `../../../tests/e2e`.
