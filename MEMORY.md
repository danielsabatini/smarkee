# Memória Operacional do Projeto (AI Context)

Conforme `AGENTS.md` (§35): este arquivo contém **apenas o resumo do estado operacional atual** necessário para continuar o trabalho.
- **Histórico detalhado de execução:** `.journal/2026-10-27.md`, `.journal/2026-10-26.md`, `.journal/2026-10-25.md`, `.journal/2026-10-24.md` e `.journal/2026-10-19.md` (locais, não versionados — consultar sob demanda).
- **Regras, contratos e decisões:** `AGENTS.md`, `docs/` e `.decisions/`.

## Estado operacional atual
- **Branch `dev` (`origin/dev`):** features `core/account`, `sum/service`, `bsm/account` (decisão `0082`), `ipm/organization`, `ipm/user`, `ipm/permission`, `ipm/role` e `ipm/group` e `ipm/serviceaccount` (decisão `0094`: identidade de máquina da Organization, chave privada gerada no cliente; `sk ipm serviceaccount` e `sk auth login --key-file`, validados ao vivo) (decisões `0083`, `0084`, `0085`, `0088`, `0092`: roles `custom` por Organization; `0091`: Operation `superseded`) operacionais no Compose; comandos `sk ipm permission`, `sk ipm role`, `sk ipm group` e suporte a `roles`/`groups` em `sk ipm user` implementados e verificados.
- **Banco `platform` (decisões `0086`, `0088`):** Executor e Observer de `ipm/role` e `ipm/group` usam o banco `platform` (plano de dados multi-tenant, tabelas `ipm.role`, `ipm.role_permission`, `ipm.group`, `ipm.group_role`) fora do SSOT; ativo no dev.
- **Banco `ssot` (decisão `0087`):** o SSOT passou de `smarkee` para `ssot` (banco e dono), aplicado no dev, verificado e commitado (`0a36f6e`). Backups anteriores a isto não restauram pela ferramenta.
- **Identidade (`infrastructure/dev/identity`):** chaves das service accounts do Zitadel persistem no volume Docker `identity-bootstrap`.
- **Ambiente local OpenCode:** `~/.config/opencode/opencode.json` carrega `AGENTS.md` e `MEMORY.md` globalmente; `.opencode/opencode.json` do projeto é local e ignorado pelo git.

## Próximos passos imediatos
00. **Plano de evolução ipm/* e loop** (`~/.opencode/plan/ipm-resource-control-loop-evolution.md`; ordem `S0 → S2 → S1 → S3 → S4 → S5 → S6`): S0 e S2 entregues e em `origin/dev` (`8b0ad46d`). Decisão `0096`: `ipm/organization|serviceaccount|user` têm só receiver, manager, publisher e controller (mais `migrate`/`consumer`); sem `action_result`; Manager sem DELETE no recurso. Próxima: S1 (`desired` puro e permissões efetivas no status). Pendências da S2: contas Zitadel `*-executor/observer` (lacuna em `IMPLEMENTATION-STATUS.md`), `test_structure.py` da identidade, diagramas `docs/{flow,architecture,state,database}` das 3 features, `reconciliation` no openapi/schema.
0. Os `list` da CLI `sk` mostram só `name | resourceId | phase | description` (padronizados; `--output json` mantém todos os campos). Commitado em `14ccbd9` (as opções `--output`/`--raw`, decisão `0093`, já estão em `origin/dev`, `0bdba35`). O scanner da CLI exige `-Dsonar.python.coverage.reportPaths=coverage.xml` (o `sonar-project.properties` não define); Quality Gate `smarkee-clients-cli` em OK.
0a. A UX da CLI `sk` é auditada pela skill `cli-ux` (matriz `references/clig-conformance.md`, lacunas em aberto listadas lá); lotes A e B e as etapas 1 a 3 entregues e em `origin/dev` (até `1474acb2`): timeout `api.timeoutSeconds`, `config unset`, `--public-key-file -`, progresso do `--wait`, `-q/--quiet` (decisão `0095`) e exemplos na ajuda de 8 comandos. Em aberto: `sk help <cmd>` (só se o responsável quiser; o `-h` já cobre), exemplos nos demais comandos, canal de suporte e modo de diagnóstico (traceback) para erro inesperado.
1. Higiene operacional: ruído de WARN `NotFound` em `ipm/user` e `trace_id` não propagado entre receivers (não pedidos); isolar testes de integração para não publicar no loop em execução; limpeza reconhecer usuário removido; supressão de logs repetitivos por recurso; trace novo por tentativa com link (quando houver spans).

- **Docs reorganizados por tema (commits `5527f4a` e `eef8c95`):** `docs/{loop,messaging,data,platform}/`, sem redirecionadores; todas as referências `docs/X.md` do repositório (inclusive arquivos gerados) foram migradas para os caminhos novos. Novo guia: `docs/cli/CLI-DEV-STG.md`.

## Pendências antes de `stg`/`prd`
- `pinned_client`; controle de versão das migrações (`*-migrate` reaplicam tudo); allowlist de caminhos do Zitadel; substituir papéis de instância dos executors; validar `restore/reset --apply` do backup no dev ativo; regras de namespace do OpenBao (decisão `0006`) e validação das ACLs/Streams de `docs/messaging/NATS.md`.

## Armadilhas operacionais ativas
- `ObservationStale` (decisão `0090`): um recurso `unknown` vai a `Failed` só na próxima observação após o prazo (até ~300 s + jitter); em `stg`/`prd` repetir `ORG_OWNER_VIEWER` na `operator` para o Observer de `ipm/permission`, os Grants/autorizações `ipm.group.*` e `ipm.role.*`, as migrações `*-operation-superseded` e `ipm/role` `0004-role-organization`, e `update grantable=true` de `ipm.role.get|list`.
- Em `stg`/`prd`, para `ipm/serviceaccount`: contas `ipm-serviceaccount-executor/observer`, papéis, Grants, autorizações, migrações, `update grantable=true` e rota do gateway (decisão `0094`). O `--key-file` de `sk auth login` não é chave de config.
- Em ambiente existente, aplicar como `postgres` `platform.sql`, `ipm.sql` e `telemetry.sql` (o `initdb.d` só roda em volume novo); o MCP `postgresql` não cobre o `platform`: use `docker exec database.smarkee.internal psql -U postgres -d platform`.
- O `scripts/dev/cleanup` cobre Roles (`test.role*`/`test.chaos*`) e Grupos (`test-group-*`/`test-loop-*`/`test-chaos-*`) de teste no SSOT e no `platform`.
- Recriar um Receiver exige reiniciar o gateway (cache de DNS); recriar um telemeter exige reiniciar o `telemetry-router`.
- `docker compose up --build` numa feature falha ao reconstruir `*-migrate` (`apk` sem rede); usar `docker compose build <feature>-observer` e `up -d --no-build <papéis>`.
- Resíduo de testes: `scripts/dev/cleanup`; sinais em disco: `scripts/dev/telemetry-reset --apply`.
