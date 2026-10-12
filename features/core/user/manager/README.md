# core-user-manager

Manager de `core.user` (`srv-core-user-manager`), componente autocontido (`.decisions/0015-componentes-por-papel-autocontidos.md`).

Único escritor do SSOT do tipo (só insere no outbox; quem o publica é o Publisher): consome `requested`, aplica cada mensagem em uma unidade atômica (linha bloqueada, Operation única, `desired` no outbox) e confirma ao transporte depois do `COMMIT`. O código das migrações (`migrations/`) é deste projeto; a execução é uma etapa de implantação com o papel administrativo.

`uv run datamodel-codegen` regera `contracts/generated.py` a partir de `schemas/` (o teste de contrato falha se divergir).

## Estrutura

```text
src/core_user_manager/
  domain/      regras do User, puras (política, convergência, resultado de ação)
  handlers/    uma unidade atômica por mensagem; portas do SSOT em ports.py
  store/       único código com SQL do SSOT (PostgresStore)
  transport/   adaptadores NATS (consumers de requested, observed e resultados)
  http/        servidor de saúde (decisão 0018)
  main.py
```

A dependência vai em um sentido só (`main → handlers → domain`); `tests/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Saúde

`GET /health/live`, `/health/ready` e `/health/startup` na porta `8000` (`CORE_USER_MANAGER_HEALTH_PORT`). A liveness não consulta dependências; a readiness inclui o NATS.

## Configuração

Variáveis de ambiente `CORE_USER_MANAGER_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatórias, sem default: `CORE_USER_MANAGER_DATABASE_PASSWORD`, `CORE_USER_MANAGER_NATS_PASSWORD`. Os demais valores e defaults estão em `src/core_user_manager/settings.py`.

## Desenvolvimento

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest        # os testes de integração exigem a stack de dev e são pulados sem ela
```

Imagem: `Dockerfile` (build com uv, execução sem privilégios). O contrato é verificado pelos testes e2e em `../tests/e2e`. A publicação do outbox é do Publisher (`../publisher`).
