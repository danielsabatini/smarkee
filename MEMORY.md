# Memória Operacional do Projeto (AI Context)

Conforme `AGENTS.md` (§35): este arquivo contém **apenas o resumo do estado operacional atual** necessário para continuar o trabalho.
- **Histórico detalhado de execução:** `.journal/2026-10-30.md`, `.journal/2026-10-29.md`, `.journal/2026-10-28.md`, `.journal/2026-10-27.md`, `.journal/2026-10-26.md`, `.journal/2026-10-25.md`, `.journal/2026-10-24.md` e `.journal/2026-10-19.md` (locais, não versionados — consultar sob demanda).
- **Regras, contratos e decisões:** `AGENTS.md`, `docs/` e `.decisions/`.

## Estado operacional atual
- **Cluster Kubernetes de desenvolvimento (`kind` + `ArgoCD` + `Kustomize` + `vault`, decisões `0102` e `0103`):**
  - Cluster `kind` `smarkee` (`v1.37.0`) com container registry local `smarkee-registry` (`localhost:5001`, CNCF Distribution `registry:3.1.2`), 17 namespaces e DNS padrão `<service>.<namespace>.svc.cluster.local`.
  - Operadores oficiais em execução nos namespaces padronizados (`<papel>-operator`, `AGENTS.md` §15.1): `ArgoCD` (`gitops-operator`), `CloudNativePG` (`database-operator`, `v1.30.1`), `NACK` (`messaging-operator`, `v0.25.0`), `OpenTelemetry Operator` (`telemetry-operator`, `v0.162.0` com collector `0.164.0`), `cert-manager` e `trust-manager` (`cert-manager-operator`, `v1.21.3` e `v0.26.0`), e `External Secrets Operator` (`external-secrets-operator`, `v2.13.0`).
  - Serviço `vault` (`openbao/openbao:2.7.2` no namespace `vault`, credenciais de unseal em `.workspace/vault-init.json` restritas a break-glass) expondo os 3 Kubernetes Services (`svm`, `ekm`, `clm`) mapeados aos mounts `/svm` (`kv-v2`), `/ekm` (`transit`) e `/clm` (`pki`), com namespaces `core/` e `operator/` espelhados nas organizações do Zitadel (`identity_org_id`).
  - **Autenticação e RBAC Unificados Zitadel ↔ OpenBao (decisões `0103` e `0104`):**
    - Uso operacional de `root_token` eliminado. Operadores humanos autenticam na Web UI (`http://127.0.0.1:8200/ui/`) e CLI (`bao login -method=oidc`) via OIDC federado com a aplicação `vault` (`operator/clients`).
    - Decisão `0104`: Ação `.admin` abolida como permissão atômica, substituída por `.operate` (`<módulo>.<tipo>.operate`), reservando sufixos `Admin` e `Viewer` estritamente a Roles compostas (`ipm.role` e roles OIDC).
    - Módulo do cofre padronizado com permissões de plano de controle `vault.platform.{create,delete,get,list,update,operate}` e roles compostas `vault.platformAdmin` / `vault.platformViewer`.
    - 24 External Identity Groups criados no OpenBao (`vault.platform.*`, `svm.secret.*`, `ekm.key.*`, `clm.certificate.*`) com Group Aliases associados ao accessor do `auth/oidc`, mapeados dinamicamente via `groups_claim="roles"` emitida pela Action `flatRoles` do Zitadel (Complement Token flow 2, triggers 4 e 5).
    - Catálogo do Zitadel e SSOT migrados com permissões `.operate` e `vault.platform.*`, com drivers e APIs atualizados para rotear e validar `.operate` com retrocompatibilidade a `.admin`.
    - Verificações 100% verdes: `./scripts/dev/check` (15 componentes), `tests/telemetry` (`20 passed`) e `infrastructure/dev/identity/conformance` (`25 passed`, incluindo testes dedicados de External Identity Groups, OIDC roles e action flatRoles com validação E2E via browser do login OIDC no OpenBao).
  - Serviços de plataforma (`database`, `messaging`, `mail`, `telemetry`, `identity`, `gateway`) e todas as 9 features gerenciados via GitOps pelo ArgoCD (`smarkee-root`, 18 `Application`s `Synced` e `Healthy`).
  - Telemetria central renomeada para `telemetry-sink` (`infrastructure/dev/telemetry-sink`), `telemetry-agent` em modo `DaemonSet` (lendo `/var/log/pods` e `kubeletstats`, sem `docker.sock`).
  - Documentação da plataforma Kubernetes dividida em escopos estritos: arquitetura e topologia em `docs/infrastructure/k8s/INFRASTRUCTURE.md` e manual de operação diária, dev loops, utilitários e troubleshooting em `docs/infrastructure/k8s/OPERATION.md`.
- **Branch `dev`:** padronização de Subjects NATS (4 tokens), consolidação dos Streams JetStream e política de retenção no SSOT (decisão `0101`):
  - Subjects NATS unificados em 4 tokens: `desired.<mod>.<type>.<id>` e `updated.<mod>.<type>.<id>`.
  - Schema de envelope (`message-envelope.v1.schema.json`): `emitter` restrito a `["api", "controller"]`, `messageType` restrito a `["desired", "updated"]` e `operation` mantido como `"changed"`.
  - Streams JetStream consolidados via CRDs `Stream` do NACK: `DESIRED` (`desired.>`, `allow_direct: true`), `UPDATED` (`updated.>`, `allow_direct: true`) e `AUDIT` (`audit.>`, `sources: [DESIRED, UPDATED]`, `deny_delete: true`).
  - Utilitário de retenção (`scripts/dev/retention`, `smarkee-dev-retention`): expurgo de `<tipo>_outbox` e `<tipo>_idempotency` via papéis `*_maintenance_login` (menor privilégio) com janela configurável (`--older-than`, padrão 24h) e modo simulação (`--apply`).
- **Plano `ipm/*` e desmonte do loop legado (decisões `0098`, `0099`, `0100` e etapa S6):**
  - `bsm/account`, `ipm/role` e `ipm/group` são `internal-state` (`api` + `publisher`); `core/account`, `sum/service` e `ipm/{organization,user,serviceaccount,permission}` são `external-reconciled` (`api` + `publisher` + `controller`).
  - Banco `ssot` (decisão `0087`) é o único banco de recursos; o banco `platform` foi extinto (decisão `0099`).
- **Utilitários de dev (`scripts/dev/`):**
  - `./scripts/dev/cluster-up`: provisiona idempotentemente `kind`, `smarkee-registry`, CoreDNS, namespaces, operadores, `vault-bootstrap` e `smarkee-root` no ArgoCD.
  - `./scripts/dev/build-push`: constrói imagens das features, envia para `localhost:5001` e atualiza no `containerd` do nó `kind` (`crictl pull`).
  - `scripts/dev/cleanup`, `scripts/dev/retention` e `scripts/dev/telemetry-reset`: 100% adaptados ao cluster Kubernetes e `telemetry-sink`.

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
- `pinned_client`; controle de versão das migrações (`*-migrate` reaplicam tudo); allowlist de caminhos do Zitadel; substituir papéis de instância dos executors; regras de namespace do OpenBao (decisão `0006`) e validação das ACLs/Streams de `docs/messaging/NATS.md`.

## Armadilhas operacionais ativas
- `ObservationStale` (decisão `0090`): um recurso `unknown` vai a `Failed` só na próxima observação após o prazo (até ~300 s + jitter); em `stg`/`prd` repetir `ORG_OWNER_VIEWER` na `operator` para o Observer de `ipm/permission`, os Grants/autorizações `ipm.group.*` e `ipm.role.*`, as migrações `*-operation-superseded` e `ipm/role` `0004-role-organization`, e `update grantable=true` de `ipm.role.get|list`.
- Em `stg`/`prd`, para `ipm/serviceaccount`: contas `ipm-serviceaccount-executor/observer`, papéis, Grants, autorizações, migrações, `update grantable=true` e rota do gateway (decisão `0094`). O `--key-file` de `sk auth login` não é chave de config.
- Em ambiente existente, aplicar como `postgres` `ipm.sql` e `telemetry.sql` (o `initdb.d` só roda em volume novo).
- O `scripts/dev/cleanup` cobre universalmente recursos `test-*` (`test-<contexto>-<hash>@example.com`, `test-org-*`, `test-bsm-*`, `test.role.*`, `test-group-*`) e retroativamente os prefixos legados.
- Recriar um Receiver exige reiniciar o gateway (cache de DNS); recriar um telemeter exige reiniciar o `telemetry-router`.
- `docker compose up --build` numa feature falha ao reconstruir `*-migrate` (`apk` sem rede); usar `docker compose build <feature>-observer` e `up -d --no-build <papéis>`.
- Resíduo de testes: `scripts/dev/cleanup`; sinais em disco: `scripts/dev/telemetry-reset --apply`.
