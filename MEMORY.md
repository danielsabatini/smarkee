# Memória Operacional do Projeto (AI Context)

Conforme `AGENTS.md` (§35): este arquivo contém **apenas o resumo do estado operacional atual** necessário para continuar o trabalho.
- **Histórico detalhado de execução:** `.journal/2026-10-25.md`, `.journal/2026-10-24.md` e `.journal/2026-10-19.md` (locais, não versionados — consultar sob demanda).
- **Regras, contratos e decisões:** `AGENTS.md`, `docs/` e `.decisions/`.

## Estado operacional atual
- **Branch `dev` (`origin/dev`):** features `core/account`, `sum/service`, `bsm/account` (decisão `0082`), `ipm/organization`, `ipm/user`, `ipm/permission` e `ipm/role` (decisões `0083` e `0084`) operacionais no Compose; comandos `sk ipm permission`, `sk ipm role` e ajuste exclusivo de `roles` em `sk ipm user` implementados e verificados (decisão `0085`).
- **Banco `platform` (decisão `0086`):** Executor e Observer de `ipm/role` usam o banco `platform` (plano de dados multi-tenant, fora do SSOT) no lugar do volume `ipm-role-state`; ativo no dev. Ainda **sem commit**. Os próximos (`ipm/user`, `ipm/group`) devem acrescentar tabelas no mesmo banco.
- **Identidade (`infrastructure/dev/identity`):** chaves das service accounts do Zitadel persistem no volume Docker `identity-bootstrap`.
- **Ambiente local OpenCode:** `~/.config/opencode/opencode.json` carrega `AGENTS.md` e `MEMORY.md` globalmente; `.opencode/opencode.json` do projeto é local e ignorado pelo git.

## Próximos passos imediatos
1. Implementação de `ipm/group` (grupos de usuários da Organization no SSOT da Smarkee com concessão de roles — decisão `0085`).
2. Operation `failed` no limite/prazo e `superseded` na substituída (contrato aditivo).
2. Higiene operacional: isolar testes de integração para não publicar no loop em execução; limpeza reconhecer usuário removido; lint pendente (`cleanup/main.py`, `backup/model.py`); supressão de logs repetitivos por recurso; trace novo por tentativa com link (quando houver spans).

## Pendências antes de `stg`/`prd`
- `pinned_client`; controle de versão das migrações (`*-migrate` reaplicam tudo); allowlist de caminhos do Zitadel; substituir papéis de instância dos executors; validar `restore/reset --apply` do backup no dev ativo; regras de namespace do OpenBao (decisão `0006`) e validação das ACLs/Streams de `docs/NATS.md`.

## Armadilhas operacionais ativas
- Em ambiente existente, aplicar como `postgres` `platform.sql`, `ipm.sql` e `telemetry.sql` (o `initdb.d` só roda em volume novo); o MCP `postgresql` só vê `smarkee`, use `docker exec ... psql -d platform`.
- O `scripts/dev/cleanup` cobre Roles de teste (`test.role*`/`test.chaos*`) no SSOT e no `platform`.
- Recriar um Receiver exige reiniciar o gateway (cache de DNS); recriar um telemeter exige reiniciar o `telemetry-router`.
- `docker compose up --build` numa feature falha ao reconstruir `*-migrate` (`apk` sem rede); usar `docker compose build <feature>-observer` e `up -d --no-build <papéis>`.
- Resíduo de testes: `scripts/dev/cleanup`; sinais em disco: `scripts/dev/telemetry-reset --apply`.
