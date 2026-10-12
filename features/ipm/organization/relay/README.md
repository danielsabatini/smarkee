# ipm-organization-relay

> **Desenho anterior (decisão 0019).** O relay passa a se chamar **Publisher**, o sexto papel, em projeto próprio, com a estrutura e a saúde do `features/core/user/publisher` (modelo). Este README descreve o código atual até a migração; o Publisher do User descreve o alvo.

Relay de `ipm.organization` (`ipm-organization-relay`), componente autocontido (`.decisions/0015-componentes-por-papel-autocontidos.md`).

Publica no transporte, em ordem e de forma sequencial, o que o Manager registrou no outbox do tipo. Uma instância ativa por vez (trava consultiva de sessão).

## Configuração

Variáveis de ambiente `IPM_ORGANIZATION_RELAY_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatórias, sem default: `IPM_ORGANIZATION_RELAY_DATABASE_PASSWORD`, `IPM_ORGANIZATION_RELAY_NATS_PASSWORD`. Os demais valores e defaults estão em `src/ipm_organization_relay/settings.py`.

## Desenvolvimento

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest        # os testes de integração exigem a stack de dev e são pulados sem ela
```

Imagem: `Dockerfile` (build com uv, execução sem privilégios). O contrato é verificado pela suíte black-box em `../conformance` (a ser movida para `tests/e2e`).
