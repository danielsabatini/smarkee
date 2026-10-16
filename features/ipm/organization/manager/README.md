# ipm-organization-manager

Manager de `ipm.organization` (`ipm-organization-manager`), componente autocontido (`.decisions/0015-componentes-por-papel-autocontidos.md`).

Único escritor do SSOT do tipo (só insere no outbox; quem o publica é o Publisher): consome `requested`, `observed` e o resultado das ações (`completed` e `failed`) e aplica cada mensagem em uma unidade atômica (linha bloqueada, Operation única, `desired` no outbox), confirmando ao transporte depois do `COMMIT`. O código das migrações (`migrations/`) é deste projeto; a execução é uma etapa de implantação com o papel administrativo.

Regras próprias da Organization, aplicadas na mesma unidade atômica: o nome não pode ser reservado (`core`, `smarkee`, `platform`, `system`, `admin`, `zitadel`) nem repetido; a cota por dono (`ownerQuotaLimit`, decidida pelo Receiver; o operador não tem cota) é conferida sob trava consultiva por dono.

`uv run datamodel-codegen` regera `contracts/generated.py` a partir de `schemas/` (o teste de contrato falha se divergir).

## Estrutura

```text
src/ipm_organization_manager/
  domain/      regras da Organization, puras (política, convergência, resultado de ação)
  handlers/    uma unidade atômica por mensagem; portas do SSOT em ports.py
  store/       único código com SQL do SSOT (PostgresStore)
  transport/   adaptadores NATS (consumers de requested, observed e resultados)
  http/        servidor de saúde (decisão 0018)
  main.py
```

A dependência vai em um sentido só (`main → handlers → domain`); `tests/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Saúde

`GET /health/live`, `/health/ready` e `/health/startup` na porta `8000` (`IPM_ORGANIZATION_MANAGER_HEALTH_PORT`). A liveness não consulta dependências; a readiness inclui o NATS.

## Configuração

Variáveis de ambiente `IPM_ORGANIZATION_MANAGER_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatórias, sem default: `IPM_ORGANIZATION_MANAGER_DATABASE_PASSWORD`, `IPM_ORGANIZATION_MANAGER_NATS_PASSWORD`. Os demais valores e defaults estão em `src/ipm_organization_manager/settings.py`.

## Desenvolvimento

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest        # os testes de integração exigem a stack de dev e são pulados sem ela
```

Imagem: `Dockerfile` (build com uv, execução sem privilégios). O contrato é verificado pelos testes e2e em `../tests/e2e`. A publicação do outbox é do Publisher (`../publisher`).
