# ipm-organization-manager

Manager de `ipm.organization` (`ipm-organization-manager`), componente autocontido (`.decisions/0015-componentes-por-papel-autocontidos.md`).

Único escritor do SSOT do tipo: consome `requested`, aplica cada mensagem em uma unidade atômica (linha bloqueada, Operation única, `desired` no outbox) e confirma ao transporte depois do `COMMIT`. O código das migrações (`migrations/`) é deste projeto; a execução é uma etapa de implantação com o papel administrativo.

`uv run datamodel-codegen` regera `contracts/generated.py` a partir de `schemas/` (o teste de contrato falha se divergir).

## Configuração

Variáveis de ambiente `IPM_ORGANIZATION_MANAGER_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatórias, sem default: `IPM_ORGANIZATION_MANAGER_DATABASE_PASSWORD`, `IPM_ORGANIZATION_MANAGER_NATS_PASSWORD`. Os demais valores e defaults estão em `src/ipm_organization_manager/settings.py`.

## Desenvolvimento

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest        # os testes de integração exigem a stack de dev e são pulados sem ela
```

Imagem: `Dockerfile` (build com uv, execução sem privilégios). O contrato é verificado pela suíte black-box em `../conformance` (a ser movida para `tests/e2e`).
