# Memória Operacional do Projeto (AI Context)

Conforme `AGENTS.md` (§35): este arquivo contém **apenas o resumo do estado operacional atual** necessário para continuar o trabalho.
- **Histórico detalhado de execução:** `.journal/2026-10-25.md`, `.journal/2026-10-24.md` e `.journal/2026-10-19.md` (locais, não versionados — consultar sob demanda).
- **Regras, contratos e decisões:** `AGENTS.md`, `docs/` e `.decisions/`.

## Estado operacional atual
- **Branch `dev` (`origin/dev`):** features `core/account`, `sum/service`, `bsm/account` (decisão `0082`), `ipm/organization`, `ipm/user`, `ipm/permission`, `ipm/role` e `ipm/group` (decisões `0083`, `0084`, `0085`, `0088`) operacionais no Compose; comandos `sk ipm permission`, `sk ipm role`, `sk ipm group` e suporte a `roles`/`groups` em `sk ipm user` implementados e verificados.
- **Banco `platform` (decisões `0086`, `0088`):** Executor e Observer de `ipm/role` e `ipm/group` usam o banco `platform` (plano de dados multi-tenant, tabelas `ipm.role`, `ipm.role_permission`, `ipm.group`, `ipm.group_role`) fora do SSOT; ativo no dev.
- **Banco `ssot` (decisão `0087`):** o SSOT passou de `smarkee` para `ssot` (banco e dono), aplicado no dev, verificado e commitado (`0a36f6e`). Backups anteriores a isto não restauram pela ferramenta.
- **Identidade (`infrastructure/dev/identity`):** chaves das service accounts do Zitadel persistem no volume Docker `identity-bootstrap`.
- **Ambiente local OpenCode:** `~/.config/opencode/opencode.json` carrega `AGENTS.md` e `MEMORY.md` globalmente; `.opencode/opencode.json` do projeto é local e ignorado pelo git.

## Próximos passos imediatos
1. Operation `failed` no limite/prazo e `superseded` na substituída (contrato aditivo).
2. Higiene operacional: isolar testes de integração para não publicar no loop em execução; limpeza reconhecer usuário removido; lint pendente (`backup/model.py`); supressão de logs repetitivos por recurso; trace novo por tentativa com link (quando houver spans).

## Pendências antes de `stg`/`prd`
- `pinned_client`; controle de versão das migrações (`*-migrate` reaplicam tudo); allowlist de caminhos do Zitadel; substituir papéis de instância dos executors; validar `restore/reset --apply` do backup no dev ativo; regras de namespace do OpenBao (decisão `0006`) e validação das ACLs/Streams de `docs/NATS.md`.

## Armadilhas operacionais ativas
- Em ambiente existente, aplicar como `postgres` `platform.sql`, `ipm.sql` e `telemetry.sql` (o `initdb.d` só roda em volume novo); o MCP `postgresql` não cobre o `platform`: use `docker exec database.smarkee.internal psql -U postgres -d platform`.
- O `scripts/dev/cleanup` cobre Roles (`test.role*`/`test.chaos*`) e Grupos (`test-group-*`/`test-loop-*`/`test-chaos-*`) de teste no SSOT e no `platform`.
- Recriar um Receiver exige reiniciar o gateway (cache de DNS); recriar um telemeter exige reiniciar o `telemetry-router`.
- `docker compose up --build` numa feature falha ao reconstruir `*-migrate` (`apk` sem rede); usar `docker compose build <feature>-observer` e `up -d --no-build <papéis>`.
- Resíduo de testes: `scripts/dev/cleanup`; sinais em disco: `scripts/dev/telemetry-reset --apply`.
