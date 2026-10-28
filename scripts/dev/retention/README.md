# Smarkee Dev Retention

Utilitário de retenção e expurgo de dados obsoletos das tabelas de outbox (`published_at IS NOT NULL`) e de idempotência (`created_at`) no SSOT PostgreSQL.

## Princípio de Menor Privilégio

O utilitário utiliza estritamente as credenciais de manutenção de cada módulo:
- `core_maintenance_login` para tabelas do schema `core`
- `bsm_maintenance_login` para tabelas do schema `bsm`
- `sum_service_maintenance_login` para tabelas do schema `sum`
- `ipm_maintenance_login` para tabelas do schema `ipm`

Nenhum usuário com privilégios de superusuário (`postgres`) ou privilégios de escrita nos recursos principais (`api_login`) é utilizado.

## Uso

```bash
# Simulação dry-run (padrão de 24h)
uv run smarkee-dev-retention

# Simulação com janela customizada (ex: 7 dias)
uv run smarkee-dev-retention --older-than 7d

# Expurgo imediato em dev de tudo que já foi publicado (0s)
uv run smarkee-dev-retention --older-than 0s --apply

# Filtragem por módulo ou tipo
uv run smarkee-dev-retention --module ipm --type permission --apply
```
