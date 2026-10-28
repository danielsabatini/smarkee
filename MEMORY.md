# Memória Operacional do Projeto (AI Context)

Conforme `AGENTS.md` (§35): este arquivo contém **apenas o resumo do estado operacional atual** necessário para continuar o trabalho.
- **Histórico detalhado de execução:** `.journal/2026-10-28.md`, `.journal/2026-10-27.md`, `.journal/2026-10-26.md`, `.journal/2026-10-25.md`, `.journal/2026-10-24.md` e `.journal/2026-10-19.md` (locais, não versionados — consultar sob demanda).
- **Regras, contratos e decisões:** `AGENTS.md`, `docs/` e `.decisions/`.

## Estado operacional atual
- **Branch `dev`:** o plano `ipm/*` e desmonte do loop legado (decisões `0098`, `0099`, `0100` e etapa S6):
  - `bsm/account` migrada (S6.1) para `internal-state` (`api` + `publisher`): zero chamadas HTTP mútuas com `ipm/organization` via projeções no stream `DESIRED` (`BillingAccountProjection` em `ipm/organization` e `OrganizationUsageProjection` em `bsm/account`), CLI `sk` adaptada para `SyncResourceFlow`.
  - `ipm/serviceaccount|user|organization|permission` têm `api`, `publisher`, `controller`; `ipm/role|group` e `bsm/account` têm só `api` e `publisher`; banco `platform` extinto (`0099`).
  - `core/account` (S6.2) e `sum/service` (S6.3) migradas para `api` + `publisher` + `controller`; template/`FEATURE-BOOTSTRAP`/agent `feature`/skills limpos do loop de 7 papéis.
  - Ativação operacional no dev concluída: contêineres legados de 7 papéis removidos, novas imagens construídas, service accounts `core-account-controller` e `sum-service-controller` provisionadas no Zitadel com chaves no volume `identity-bootstrap`, rotas do gateway sincronizadas (ADC), suíte de conformidade de identidade 100% verde (21/21) e suítes e2e reais de `core/account` e `sum/service` validadas. Check local `./scripts/dev/check` 100% verde.
- **Banco `ssot`** (decisão `0087`) é o único banco de recursos; o banco `platform` foi extinto (decisão `0099`; dump prévio em `.workspace/platform-before-drop.dump`).
- **Identidade (`infrastructure/dev/identity`):** chaves das service accounts do Zitadel persistem no volume Docker `identity-bootstrap`.
- **Ambiente local OpenCode:** `~/.config/opencode/opencode.json` carrega `AGENTS.md` e `MEMORY.md` globalmente.

## Próximos passos imediatos
00. **Plano de evolução ipm/* e loop** (`~/.opencode/plan/ipm-resource-control-loop-evolution.md`; ordem `S0 → S2 → S1 → S3 → S4 → S5 → S6`):
  - S6 totalmente concluída no código, nos contêineres e nos testes.
  - Documentação de fluxo de dados (`*-DATA-FLOW.md`) e diagramas (`architecture/`, `database/`, `state/`, `flow/`) de todos os componentes (`ipm/role`, `ipm/group`, `ipm/organization`, `ipm/permission`, `ipm/user`, `ipm/serviceaccount`, `bsm/account` e `core/account`) 100% atualizados para os modelos vigentes (`internal-state` e `external-reconciled`), com eliminação de artefatos mortos.
  - Lacuna de identidade Zitadel fechada: as 12 contas legadas de `*-executor` e `*-observer` foram expurgadas do Zitadel no dev e do volume `identity-bootstrap`, `.env` limpo e suíte de conformidade de identidade 100% verde (21/21).
  - Backlog de UX da CLI `sk`: canal de suporte, modo de diagnóstico técnico `SK_DEBUG`/`SK_TRACEBACK` para erros inesperados e cobertura de `examples=` na ajuda (`--help`) de todos os comandos concluídos.
  - Pendência restante: Console desatualizado (fase própria).
0. Os `list` da CLI `sk` mostram só `name | resourceId | phase | description` (padronizados; `--output json` mantém todos os campos). Commitado em `14ccbd9` (as opções `--output`/`--raw`, decisão `0093`, já estão em `origin/dev`, `0bdba35`). O scanner da CLI exige `-Dsonar.python.coverage.reportPaths=coverage.xml` (o `sonar-project.properties` não define); Quality Gate `smarkee-clients-cli` em OK.
1. Higiene operacional: ruído de WARN `NotFound` em `ipm/user` e `trace_id` não propagado entre receivers (não pedidos); isolar testes de integração para não publicar no loop em execução; limpeza reconhecer usuário removido; supressão de logs repetitivos por recurso; trace novo por tentativa com link (quando houver spans).

- **Docs reorganizados por tema (commits `5527f4a` e `eef8c95`):** `docs/{loop,messaging,data,platform}/`, sem redirecionadores; todas as referências `docs/X.md` do repositório (inclusive arquivos gerados) foram migradas para os caminhos novos. Novo guia: `docs/cli/CLI-DEV-STG.md`.

## Pendências antes de `stg`/`prd`
- `pinned_client`; controle de versão das migrações (`*-migrate` reaplicam tudo); allowlist de caminhos do Zitadel; substituir papéis de instância dos executors; validar `restore/reset --apply` do backup no dev ativo; regras de namespace do OpenBao (decisão `0006`) e validação das ACLs/Streams de `docs/messaging/NATS.md`.

## Armadilhas operacionais ativas
- `ObservationStale` (decisão `0090`): um recurso `unknown` vai a `Failed` só na próxima observação após o prazo (até ~300 s + jitter); em `stg`/`prd` repetir `ORG_OWNER_VIEWER` na `operator` para o Observer de `ipm/permission`, os Grants/autorizações `ipm.group.*` e `ipm.role.*`, as migrações `*-operation-superseded` e `ipm/role` `0004-role-organization`, e `update grantable=true` de `ipm.role.get|list`.
- Em `stg`/`prd`, para `ipm/serviceaccount`: contas `ipm-serviceaccount-executor/observer`, papéis, Grants, autorizações, migrações, `update grantable=true` e rota do gateway (decisão `0094`). O `--key-file` de `sk auth login` não é chave de config.
- Em ambiente existente, aplicar como `postgres` `ipm.sql` e `telemetry.sql` (o `initdb.d` só roda em volume novo).
- O `scripts/dev/cleanup` cobre Roles (`test.role*`/`test.chaos*`) e Grupos (`test-group-*`/`test-loop-*`/`test-chaos-*`) de teste no SSOT.
- Recriar um Receiver exige reiniciar o gateway (cache de DNS); recriar um telemeter exige reiniciar o `telemetry-router`.
- `docker compose up --build` numa feature falha ao reconstruir `*-migrate` (`apk` sem rede); usar `docker compose build <feature>-observer` e `up -d --no-build <papéis>`.
- Resíduo de testes: `scripts/dev/cleanup`; sinais em disco: `scripts/dev/telemetry-reset --apply`.
