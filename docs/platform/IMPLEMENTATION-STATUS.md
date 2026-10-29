# Estado da implementação

> **Escopo:** compara, item a item, os checklists das especificações (`RESOURCE-CONTROL-LOOP.md`, `NATS.md`, `POSTGRESQL.md`, `SSOT.md` e `RESOURCE-CONTROL-SECURITY.md`) com o que existe hoje no repositório e no ambiente de desenvolvimento.
>
> **Papel:** relatório de conformidade, e não fonte de regras. As regras estão nas especificações; em conflito, elas prevalecem. Este documento muda quando a implementação muda.
>
> **Base da avaliação:** o tipo `core.account` (`features/core/account`), a primeira feature e o modelo das demais, verificado em desenvolvimento em 2026-10-11 (testes de cada projeto, `ruff`, `pyright`, testes e2e contra o Zitadel e o Mailpit reais e testes de resiliência). O tipo `ipm.organization` foi refeito a partir dele e verificado em 2026-10-16, com a mesma bateria.

Legenda: **Atende** (implementado e verificado); **Parcial** (implementado em parte ou sem verificação completa); **Pendente** (previsto e não implementado); **Alvo** (exigido só em stg e prd; não exercitado em dev).

# 1. Resumo

| Área | Situação |
|---|---|
| Loop completo da Account (API, Publisher e Controller; decisões 0096 e 0098) | Atende no código e nos testes unitários e de contrato (cadastro anônimo `202 {resourceId}`, exclusão segura por projeções do `DESIRED`, decisão 0100). Lacuna declarada: a suíte `tests/e2e` foi reescrita e ainda não foi executada contra a stack real; ver "Migração de `core/account` para stg e prd" abaixo |
| Contratos (JSON Schema, modelos gerados, OpenAPI) | Atende: 268 testes dos schemas; modelos regerados e conferidos por teste em cada projeto |
| Estrutura interna (`domain/` puro, camadas, saúde) | Atende nos seis papéis, com teste de isolamento do `domain/` em cada projeto |
| Resiliência | Parcial. **Código:** o outbox, a troca de instância do Publisher, a fila com backoff do Controller, a reconexão ilimitada ao NATS, o limite de entregas por mensagem (`max_deliver`) e o `check` do pool do banco estão implementados; os e2e com `E2E_CHAOS=1` (`test_chaos.py` de `core/account`, `ipm/organization`, `ipm/permission` e `sum/service`) derrubam contêineres do Publisher e do Controller, mas a queda do NATS e a do banco não têm teste automatizado. **Infraestrutura:** um nó, uma instância e sem PITR em dev, todos declarados na seção 7.1 |
| Segurança de transporte e identidade no barramento | **Alvo**: dev usa um só usuário NATS, sem TLS |
| Observabilidade | Parcial: logs estruturados e probes de saúde, spans do gateway e métricas de contêiner; o `traceparent` do gateway é propagado até os componentes e os logs trazem `trace_id` (decisão 0055) e o contexto de negócio (ator, recurso, ação, dono e organização, decisão 0061); sem spans nem métricas de aplicação, e o span do gateway ainda sem o contexto. Logs no formato OpenTelemetry (`OBSERVABILITY.md`, decisão 0045) nos 18 contêineres; em dev o `telemetry-agent` os coleta (com as métricas de contêiner) e os telemeters (`platform-telemeter` e o de cada feature) os gravam em arquivos com rotação, depois do `telemetry-router` (decisões 0051 e 0062); o destino persistente ainda não existe |
| Retenção, quarentena, backup e recuperação | Pendente |
| Organization (`ipm`) | Atende para o loop completo (Receiver, Manager, Publisher e, desde a decisão 0096, Controller, que substituiu Reconciler, Observer e Executor; migração `0007` dá o papel de banco do Controller e `0008` remove `action_result`), refeito a partir da Account (decisão 0038), com testes e2e contra a stack do dev e o Zitadel real: criar, renomear, desativar e reativar (`platformAccess`), remover e a queda de cada papel. O Controller escreve a organização e o preparo dela para os usuários (Project Grant de `roles-ipm` e papéis das contas do `ipm/user`, decisão 0081), e o Controller observa `desired.ipm.permission.>` via NATS para atualizar dinamicamente o `grantPermissions` sem exigir redeploy (decisão 0083). **Desde a decisão 0098 a escrita é síncrona:** o processo `api` (`ipm-organization-api`, papel de banco `ipm_organization_api`, migração `0009`) substitui Receiver e Manager, a Operation e o Stream `REQUESTED` do tipo deixam de existir e o `Resource` ganha `observedGeneration`. **Lacuna declarada (0098):** as contas Zitadel `ipm-organization-{executor,observer}` seguem sem processo; as variáveis `ipm-organization-receiver` dos peers (`organizations_url`) foram apontadas para `ipm-organization-api`; em `stg`/`prd` repetir a migração `0009`, o papel `ipm_organization_api`, a rota do gateway e remover o consumer `ipm-organization-manager-requested` |
| Catálogo de Permissões (`ipm.permission`) e de Roles (`ipm.role`) | Atende: contratos (`schemas/ipm/permission/` e `schemas/ipm/role/`), os papéis de `features/ipm/permission/` (desde a decisão 0098: `api`, `publisher` e `controller`) e de `features/ipm/role/` (`api` e `publisher`), migrações com sementes do catálogo inicial (`0001-permission.sql` e `0001-role.sql`), bootstrap do banco (`ipm.sql`), gateway (`/v1/ipm/permissions` e `/v1/ipm/roles`) e telemetria implementados e verificados (decisão 0083). `ipm.permission` gerencia as permissões atômicas (`<módulo>.<tipo>.<ação>`) nos projetos `roles-<módulo>` do Zitadel; `ipm.role` gerencia as Roles compostas no padrão Google Cloud IAM (`<módulo>.<tipo><Admin\|Viewer>`) exclusivamente na Smarkee: a definição no SSOT e o estado aplicado no banco `platform` (plano de dados multi-tenant, decisão 0086), sem criar projetos ou objetos adicionais no Zitadel. Desde a decisão `0092`, uma Organization cria Roles `custom` (permissões `ipm.role.create\|update\|delete\|bind`, só com permissões `grantable`, nome único por Organization, cota de 10, `409 ResourcesAttached` se em uso) e a CLI `sk ipm role` aceita `--organization-id` **Desde a decisão 0098 (S4), `ipm.role` tem só `api` e `publisher`:** o processo `api` (`ipm-role-api`, papel de banco `ipm_role_api`, migração `0005`) substitui Receiver e Manager; a Role nasce `Ready` com `observedGeneration = generation`, a Operation, o Stream `REQUESTED` e o plano de dados no banco `platform` deixam de existir para ela, e o `DELETE` remove a linha e publica o tombstone. **Lacunas declaradas:** Reconciler, Observer e Executor foram removidos; em `stg`/`prd` repetir a migração `0005`, o papel/login `ipm_role_api`, a rota do gateway e remover os consumers antigos; diagramas de `features/ipm/role/docs` ainda no modelo anterior. **Desde a decisão 0098, `ipm.permission` tem `api`, `publisher` e `controller`:** a `api` (`ipm-permission-api`, papel de banco `ipm_permission_api`, migração `0004`) substitui Receiver e Manager; a Operation, a view `ipm.permission_operation_v1` e o Stream `REQUESTED` do tipo deixam de existir, e o `Controller` (conta Zitadel `ipm-permission-controller`, que reúne os papéis do Executor e do Observer) aplica a role de projeto no `roles-<módulo>` (`admin` em `roles-operator`) e preenche `observedGeneration`. **Lacunas declaradas (permission):** as contas `ipm-permission-{executor,observer}` seguem sem processo; diagramas e `*-DATA-FLOW.md` de `features/ipm/permission/docs` ainda no modelo anterior; em `stg`/`prd` repetir a migração `0004`, os papéis `ipm_permission_api` e `ipm_permission_controller`, criar a conta do Controller (`PROJECT_OWNER` nos `roles-*` e `ORG_OWNER_VIEWER` em `core` e `operator`), a rota do gateway e remover o consumer `ipm-permission-manager-requested` |
| Grupo da Organization (`ipm.group`) | Atende: contratos (`schemas/ipm/group/`), os papéis `api` e `publisher` (`features/ipm/group/`), migrações (`0001-group.sql` a `0003-group-api.sql`), gateway (`/v1/ipm/groups`), telemetria e CLI (`sk ipm group`) implementados e verificados por testes unitários, de contrato e e2e contra a stack em execução (decisão 0088). Exige `ipm.group.bind` para atribuir ou alterar `roles` quando o solicitante é membro da Organization, nasce com `deletionProtection: false` e bloqueia `DELETE` com `409 ResourcesAttached` enquanto houver usuários (`ipm.user`) associados ao grupo. **Desde a decisão 0098 (S4), `ipm.group` tem só `api` e `publisher`:** o processo `api` (`ipm-group-api`, papel de banco `ipm_group_api`, migração `0003`) substitui Receiver e Manager; o Grupo nasce `Ready` com `observedGeneration = generation`, a Operation, o Stream `REQUESTED` e o plano de dados no banco `platform` deixam de existir para ele, e o `DELETE` remove a linha e publica o tombstone. **Lacunas declaradas:** Reconciler, Observer e Executor foram removidos (as contas Zitadel e os papéis de banco `ipm_group_{executor,observer}` ficam até a remoção do banco `platform`); em `stg`/`prd` repetir a migração `0003`, o papel/login `ipm_group_api`, a rota do gateway e remover os consumers antigos; diagramas de `features/ipm/group/docs` ainda no modelo anterior |
| Service account da Organization (`ipm.serviceaccount`) | Atende: contratos, os papéis do loop (`features/ipm/serviceaccount/`; desde a decisão 0096 o Controller substitui Observer, Reconciler e Executor, removidos; a `0003` apaga `action_result`), migração (`0002` dá o papel de banco do Controller), gateway (`/v1/ipm/serviceaccounts`), telemetria, reconhecimento do token de máquina nos Receivers de `ipm/user`, `ipm/group`, `ipm/role` e `ipm/organization` e CLI (`sk ipm serviceaccount`, `sk auth login --key-file`) implementados e verificados por testes unitários, de contrato, e2e e ao vivo no dev (decisão 0094). **Desde a decisão 0098 a escrita é síncrona:** o processo `api` (`ipm-serviceaccount-api`, papel de banco `ipm_serviceaccount_api`, migração `0005`) substitui Receiver e Manager, a Operation e o Stream `REQUESTED` do tipo deixam de existir e o `Resource` ganha `observedGeneration`. **Lacunas declaradas (0098):** as contas Zitadel `ipm-{user,serviceaccount,organization}-{executor,observer}` existem sem processo e as `ipm-serviceaccount-{receiver,manager}` deixaram de ser usadas; fecham-se antes do `stg`; em `stg`/`prd` repetir a migração `0005`, o papel `ipm_serviceaccount_api`, a rota do gateway e a conta da API A chave privada nasce no cliente (arquivo `0600`); só a pública trafega. Nasce com `deletionProtection: true`, até 3 chaves, cota provisória de 5 por Organization. Em `stg`/`prd` repetir contas `ipm-serviceaccount-controller` (e `executor/observer` enquanto existirem), `serviceaccountControllerAccountId` da Organization, papel de banco do Controller, papéis, Grants, autorizações, migrações, `update grantable=true` e a rota do gateway |
| Usuário da Organization (`ipm.user`) | Atende para o loop completo (Receiver, Manager, Publisher e, desde a decisão 0096, o Controller, que substituiu Reconciler, Observer e Executor, removidos; a migração `0004` dá o papel de banco do Controller e a `0005` apaga `action_result`) e a CLI `sk ipm user`, com suporte a permissões atômicas (`permissions`), Roles compostas (`roles`, decisão 0083) e Grupos da Organization (`groups`, decisão 0088), expandidos em permissões atômicas. Consome `desired.ipm.permission.>`, `desired.ipm.role.>` e `desired.ipm.group.>` em tempo real para validar catálogos e re-expandir permissões sem redeploy, e exige estritamente `ipm.user.bind` para atribuir ou alterar `permissions`, `roles` ou `groups` |
| Billing Account (`bsm.account`) | Atende: contratos (`schemas/bsm/account/`), os seis papéis do loop (`features/bsm/account/`), migração (`0001-account.sql`), bootstrap do banco (`bsm.sql`), gateway (`/v1/bsm/accounts`), projeto `roles-bsm` no Zitadel, telemetria e CLI (`sk bsm account`) implementados e verificados por testes unitários, de contrato, de integração e e2e contra a stack em execução (decisão 0082). O `bsm` é uma capacidade de nível de conta (`core.account`): as roles `bsm.account.*` vêm de `DEFAULT_PLATFORM_ROLES` no cadastro e o Manager provisiona a conta `"Free Tier"` quando `core.account` converge para `Ready`. Na fase P0, o Executor e o Observer operam sobre estado local em disco (`bsm-account-state`), como lacuna declarada até a integração com Gateway de Pagamentos na fase P3 (`docs/billing/BILLING.md`) |
| SUM (`sum.service`) | Atende com API síncrona, Publisher e Controller (S6.3, decisões 0096, 0098 e 0100) e a CLI `sk sum service`, com testes de unidade, contrato e integração; a suíte `tests/e2e` foi reescrita (ligar, desligar, catálogo, jornada com a CLI) e ainda não foi executada contra a stack real. Pendente: verificação de e-mail do solicitante (decisão aberta), retenção das linhas desligadas, kill switch e visão de operador (`features/sum/service/README.md`) |
| CLI | Parcial: `sk config`, `sk auth login` (inclui `--key-file`), `sk auth whoami`, `sk sum service`, `sk ipm organization`, `sk ipm permission`, `sk ipm role`, `sk ipm group`, `sk ipm serviceaccount`, `sk ipm user` e `sk bsm account` implementados e testados (a jornada e2e usa a CLI real contra o dev); `sk account create|get|delete` (cadastro, consulta e exclusão segura da conta). Pendente: o client ID de produção (`000000000000000000`) e o endereço de stg e prd, que ainda não existem |

# 2. `RESOURCE-CONTROL-LOOP.md`: checklist de implementação (seção 55), por papel (`core.account`)

## 2.1 Resource

| Item | Situação | Evidência |
|---|---|---|
| `resourceId` estável, `desired`, `observed`, `desiredGeneration`, lifecycle, conditions | Atende | `schemas/core/account/`, migração `0001-account.sql` e `0011-account-api.sql` |
| `observedGeneration` | Atende | Coluna `observed_generation` (migração `0008`), preenchida pelo Controller só com uma observação feita depois da geração; publicada no `updated` com `desiredGeneration` e na condition `Ready` (decisões 0072 e 0096) |
| Perfil (`internal-state` ou `external-reconciled`) definido e justificado | Atende | `external-reconciled`: reconciliação de contas contra o provedor de identidade Zitadel |

## 2.2 API

| Item | Situação | Evidência |
|---|---|---|
| Admite escrita síncrona, gravando recurso e `desired` (outbox) na mesma transação | Atende | `features/core/account/src/core_account/api/store/ssot.py` |
| Responde `201`/`200`/`202` com o `Resource`, sem Operation | Atende | endpoints da API HTTP (`api/http/`), decisão 0098 |
| Verifica `resourceVersion` sob `FOR UPDATE` e responde `409` quando diverge | Atende | `store/ssot.py` |
| Guarda `Idempotency-Key` com `requestDigest` na mesma transação e responde `422` ao reuso divergente | Atende | tabela `core.account_idempotency` e `api/domain/requests.py` |
| Verifica unicidade, cota e vínculos na mesma transação, sob trava consultiva por chave | Atende | travas consultivas por chave e índice único sobre e-mail desejado |
| Grava `requested_by` e `correlation_id` no recurso | Atende | colunas `requested_by` e `correlation_id` (migração `0011-account-api.sql`) |
| Responde `503` com `Retry-After` quando o banco está indisponível | Atende | middleware de resiliência e tratamento de conexão do banco |
| Não executa provider diretamente e não chama API de outro tipo (projeções locais do `DESIRED`) | Atende | zero chamadas mútuas HTTP; projeções assíncronas via NATS JetStream (decisão 0100) |
| Só fica pronta (`/health/ready`) após sincronizar projeções de que depende | Atende | verificação de sincronismo de projeções no probe de prontidão |
| Autenticação e autorização próprias | Atende | validação de JWKS e RBAC em `api/auth/` |

## 2.3 Controller

| Item | Situação | Evidência |
|---|---|---|
| Consome `DESIRED` (Informer) e enfileira na Workqueue com backoff com jitter | Atende | `controller/engine/informer.py` e `workqueue.py` |
| Reconcilia em ciclo atômico sob `FOR UPDATE` com estado, `updated` e conditions na mesma transação | Atende | `controller/store/ssot.py` |
| `decide(desired, observed)` é pura e devolve `None` com `observed` `unknown` | Atende | `controller/domain/decision.py` |
| Observação somente leitura, distinguindo `present`, `absent` e `unknown` | Atende | `controller/adapters/zitadel/reader.py`, conta `core-account-controller` (`ORG_OWNER_VIEWER`) |
| Reobserva depois de agir e só confirma a geração com reobservação convergida | Atende | ciclo do Controller (`observe` pós-ação antes de consolidar `Ready`) |
| Ação é idempotente e tem chave de correlação com o recurso externo | Atende | `userId = resourceId` no Zitadel |
| Limita taxa e concorrência contra o provider | Parcial | concorrência limitada por partição e semáforo; sem limitação explícita de taxa (429 do Zitadel é retentado) |
| Conta falhas por geração, marca `Failed` e suspende reconciliação ao atingir `failureLimit` (5) | Atende | `failure_count >= 5` grava `Failed`, `reconciliation = suspended` e `desired` suspenso no outbox |
| Mantém `Progressing` e `ObservationStale` e leva o recurso a `Failed` ao esgotar o prazo | Parcial | `Progressing` implementado; `ObservationStale` pendente |
| Condition `DriftLoop` para detecção de flapping em curto intervalo | Pendente | reservada na especificação do loop; lacuna declarada na seção 7.1 |
| Reavalia periodicamente, com jitter, os recursos `active` da sua partição | Atende | reavaliação periódica a cada 5 min com jitter |
| Reconcilia apenas recursos da sua partição | Atende | partição determinística `hash(resourceId) mod count` |
| Bloqueia remoção enquanto houver dependentes ativos (`DeletionBlockedByDependents`) | Atende | verificação de recursos dependentes antes da exclusão |
| Apaga registro e publica `updated` com `removed=true` só depois da ausência confirmada | Atende | `DELETE` físico sob `presence = absent` |
| Comparação entre `desired` e `observed` definida para o recurso | Atende | `controller/domain/drift.py` |
| Não decide o estado desejado | Atende | o Controller só age sobre o `desired` admitido pela API |

## 2.4 Componentes por papel

| Item | Situação | Evidência |
|---|---|---|
| Cada papel roda como processo e contêiner próprios; a feature é um projeto e uma imagem, sem um papel importar outro | Atende | `features/core/account/` (três papéis: `api`, `publisher`, `controller`), `test_role_isolation.py` |
| Esquema do tipo (migrações com outbox e idempotência) é da feature, executado como etapa de implantação | Atende | `features/core/account/migrations/`, serviço `core-account-migrate` |
| Publisher é papel próprio, com papel de banco e identidade de mensageria próprios | Atende | `core_account/publisher/`, papel de banco `core_account_publisher` |
| Retenção do outbox e da idempotência (`scripts/dev/retention`) | Atende | utilitário `scripts/dev/retention` com modo `--apply`, janela de 24h e credencial de manutenção |
| Contratos verificados por testes e2e black-box | Atende | `features/core/account/tests/e2e` e jornada completa `tests/e2e` |
| Estrutura interna com `domain/` puro que não importa adaptadores | Atende | teste `test_domain_isolation.py` em cada papel |

## 2.5 Mensagens

| Item | Situação | Evidência |
|---|---|---|
| Subject na gramática oficial de 4 tokens (`<messageType>.<module>.<resourceType>.<resourceId>`) | Atende | `desired.core.account.<id>` e `updated.core.account.<id>` (decisão 0101) |
| `messageType` é `desired` ou `updated`, e o `emitter` no envelope é `api` ou `controller` | Atende | envelope validado por schema e testes |
| `operation` é sempre `changed` | Atende | envelope fixado em `changed` para mensagens de estado e fatos |
| `messageId` único, `correlationId` preservado | Atende | UUIDv7 atribuído e propagado em todo o ciclo |
| Reentrega e ordering garantidos por `resourceId` | Atende | `sequence` no outbox e deduplicação JetStream via `Nats-Msg-Id` |

# 3. `NATS.md`: checklist operacional (seção 31)

| Item | Situação | Evidência ou observação |
|---|---|---|
| Subject, emissor e destinatário (não embutido) | Atende | emissores `receiver`, `manager`, `observer`, `reconciler`, `executor`; o Publisher publica no emissor `manager` |
| Um Stream por `messageType`, com a retenção da classe | Atende | `infrastructure/dev/messaging/bootstrap/` (seis Streams) |
| `desired` e `observed` com a operação `changed` | Atende | `desired.core.account.<id>` |
| `WorkQueue` com `DiscardNew` e consumers sem filtro sobreposto | Atende | `REQUESTED` e `ACTION`; no `ACTION`, um consumer por partição, de filtros disjuntos |
| Consumer de estado por instância (`DeliverLastPerSubject`, nome único, `inactive_threshold`) | Atende | Reconciler e Observer |
| Consumer de trabalho ou persistência durável e compartilhado | Atende | consumer do Controller no `DESIRED` (`<módulo>-<tipo>-controller`) e os das projeções locais (decisões 0096 e 0100) |
| Um único filtro por consumer, no nível `<módulo>.<tipo>` | Parcial | o do Executor adiciona o token da partição (`reconciler.action.core.account.<p>.>`), mais estreito, por decisão 0018 |
| Executor: consumer por partição, `max_ack_pending=1`, Direct Get do `desired` | Atende | |
| Executor com `pinned_client` | Alvo | em dev há uma só instância, sem `pinned_client` (`NATS.md` §7.5) |
| Nenhum serviço de runtime com purge ou administração de Stream | Alvo | em dev, todos usam o mesmo usuário NATS |
| Pull Consumer, ACK após o processamento, retry com backoff | Atende | consumers do Manager e do Executor |
| Quarentena de mensagens *poison* | Parcial | `max_deliver=20` no consumer de estado, espera crescente de 5 s a 60 s e `TERM` com log `ERROR` na última entrega (`NATS.md` §11); sem Stream de quarentena (lacuna na seção 7.1) |
| Replay considerado | Parcial | estado reconstruído por `DeliverLastPerSubject`; sem procedimento de replay |
| Idempotência | Atende | `operationId`, `actionId`, `observedAt` |
| TLS e autorização por menor privilégio | Alvo | dev: sem TLS e um só usuário |
| Secrets fora do repositório | Atende | `.env` e `service-account*.json` no `.gitignore` |
| Métricas e traces | Parcial | o `traceparent` segue do gateway pelo Receiver, NATS e outbox até os demais papéis, e os logs trazem `trace_id` (decisão 0055); sem spans nem métricas de aplicação |
| Streams e consumers gerenciados de forma controlada | Atende | `bootstrap/*.json` e serviço `<módulo>-<tipo>-consumer` |
| Versão do NATS pinada | Atende | `nats:2.15.1-alpine` |

# 4. `POSTGRESQL.md`: checklist (seção 20)

| Item | Situação | Evidência ou observação |
|---|---|---|
| Versão fixada | Atende | `postgres:18.6-alpine` |
| Banco `ssot` do proprietário `ssot`, sem privilégios de `PUBLIC` | Atende | `database/bootstrap/ssot.sql` |
| Três tabelas (`<tipo>`, `<tipo>_outbox`, `<tipo>_idempotency`) e view `<tipo>_v1` por recurso | Atende | migrações `0001-account.sql` e `0011-account-api.sql` |
| `CHECK` em `lifecycle`, `reconciliation`, `presence`, `phase`, identificadores e `jsonb` | Atende | `core.account` (todas as colunas de controle e de identificação) |
| `FOR UPDATE` na linha; `resource_version` na condição da API com `409 Conflict` | Atende | `store/ssot.py` |
| Geração só incrementa quando a especificação muda | Atende | `desired_generation` incrementado apenas sob alteração de `desired` |
| Deduplicação da admissão por `idempotency_key` e `request_digest` escopada ao solicitante | Atende | tabela `core.account_idempotency` e `api/domain/requests.py` |
| Publisher: uma instância ativa via trava consultiva, sequencial, sem marca-d'água e sem `SKIP LOCKED`; marca só após confirmação | Atende | `publisher/.../outbox/publication.py` |
| Matriz de privilégios igual à de segurança | Atende | papéis `core_account_{api,controller,publisher,maintenance}` configurados |
| API lê somente views; Controller apaga recurso só após ausência confirmada; nenhum papel de runtime tem `DELETE` no outbox ou idempotência | Atende | migração `0011-account-api.sql` e `database/bootstrap/core.sql` |
| Papéis de login com `search_path`, `lock_timeout`, `statement_timeout`, `idle_in_transaction_session_timeout` | Atende | `database/bootstrap/core.sql` |
| Identidade de manutenção e rotina de retenção operacional de 24h | Atende | utilitário `scripts/dev/retention`, imagem `smarkee-dev-retention` e papéis `*_maintenance_login` (decisão 0101) |
| TLS e proteção em repouso | Alvo | |
| Parâmetros e colunas `confidential` fora dos logs | Parcial | verificado por revisão (o log não registra mensagens de exceção nem valores); sem teste automatizado de varredura |
| PITR, teste de restauração e recuperação | Pendente | |
| Migrações expandir → migrar → contrair, por infraestrutura | Parcial | executadas por `core-account-migrate`, idempotentes; sem controle de versão (obrigatório antes de stg e prd) |

# 5. `SSOT.md`: checklist (seção 21)

| Item | Situação | Evidência |
|---|---|---|
| Dois escritores segregados (API e Controller); unidade atômica com outbox; acesso exclusivo por `FOR UPDATE` | Atende | `api/store/ssot.py` e `controller/store/ssot.py` |
| Rejeições de admissão tratadas síncronas na API (`409`, `422`, `404`) | Atende | respostas HTTP da API na requisição |
| Outbox na mesma unidade; ordem por recurso preservada | Atende | API, Controller e Publisher |
| Idempotência semântica de admissão (tabela de idempotência) e do ciclo de convergência | Atende | `core.account_idempotency` e reobservação factual no Controller |
| `desiredGeneration` e `resourceVersion` | Atende | |
| Dicionário de dados com sensibilidade e escritor | Atende | `SSOT.md` §8 e `x-sensitivity`/`x-writer` nos schemas |
| Privilégios mínimos por tipo | Atende | |
| Estrutura gerada de um modelo | Parcial | ver a seção 4 |
| Backup com recuperação a um ponto no tempo e teste de restauração | Pendente | |
| Sinais de observabilidade | Parcial | o atraso do outbox é consultável por SQL; sem métricas exportadas |
| Mensagens publicadas e idempotência removidas após retenção de 24h | Atende | utilitário `scripts/dev/retention` com modo `--apply` e janela configurável (decisão 0101) |

# 6. `RESOURCE-CONTROL-SECURITY.md`: checklist (seção 15)

| Item | Situação | Evidência ou observação |
|---|---|---|
| Identidade própria por serviço | Parcial | nomes `core-account-<papel>`, papéis de banco e contas do Zitadel próprios; no NATS, usuário único em dev |
| Permissões de publicação e consumo pela matriz, escopadas por `<módulo>.<tipo>` | Alvo | |
| Sem purge nem administração de Stream para serviços; limpeza de tombstones por identidade administrativa | Alvo / Pendente | |
| `resourceId` validado antes de compor o Subject | Atende | padrão do contrato e `CHECK`; API valida UUIDv7 |
| API sem credenciais do provedor externo nem conexão direta de publicação no NATS | Atende | a API só grava no SSOT |
| Publisher publica exclusivamente nos Subjects de 4 tokens do seu `<módulo>.<tipo>` | Atende | `desired.core.account.<id>` e `updated.core.account.<id>` |
| Controller possui credencial própria e isolada de menor privilégio para o provedor externo | Atende | conta de serviço Zitadel dedicada do Controller |
| Controller executa ciclo sob bloqueio de linha (`FOR UPDATE`) no SSOT | Atende | `controller/store/ssot.py` |
| Falhas de leitura do provedor externo são categorizadas estritamente como `unknown` e nunca como `absent` | Atende | `presence = unknown` em caso de erro/timeout/5xx |
| Remoção física no SSOT só ocorre após confirmação inequívoca de ausência no sistema externo | Atende | `DELETE` físico sob `presence = absent` comprovado |
| Limite de falhas consecutivas suspende reconciliação (`failureLimit = 5`) | Atende | `reconciliation = suspended` e `desired` suspenso no outbox |
| Nenhum segredo em mensagens, logs ou erros | Atende | credenciais nunca trafegam em mensagens |
| Ator acompanha a operação (`requestedBy`) | Atende | `requestedBy` em `desired` e `updated` |
| Isolamento por organization | Parcial | definido para a Organization (decisão 0010); a Account não tem organização |
| Eventos de segurança observáveis | Parcial | só em logs estruturados |

# 7. Lacunas conhecidas e desvios deliberados

| Tema | Situação | Referência |
|---|---|---|
| Organization (`features/ipm/organization`) | Papéis de instância `IAM_ORG_MANAGER` (Executor) e `IAM_OWNER_VIEWER` (Observer): mais largos que o necessário, por exceção deliberada (AGENTS §4.3, decisão 0060): ver 7.1. O nome `register` não é reservado (falha no Executor, `Rejected`) | `features/ipm/organization/README.md`, decisão 0038 |
| Usuário da Organization (`features/ipm/user`) | A lacuna da decisão 0077 (Grant e papéis por organização feitos pelo operador) está **fechada** pela decisão 0081: o loop da `ipm/organization` prepara cada Organization, e o catálogo é o enum `grantableRole` do contrato. **A lacuna das contas Zitadel legadas `*-executor/observer` está fechada no dev:** as 12 contas legadas foram expurgadas do Zitadel, suas chaves removidas do volume `identity-bootstrap`, as variáveis removidas dos `.env` e a suíte de conformidade de identidade valida exclusivamente as contas ativas de controller. A cota de 5 usuários por Organization é provisória | `features/ipm/user/README.md`, `.decisions/0081-organization-pronta-para-usuarios-pelo-loop.md` |
| CLI | `sk config`, `sk auth`, `sk sum service`, `sk ipm organization`, `sk ipm user` e `sk account create|get|delete` | `ROADMAP.md` |
| `pinned_client` no Executor | Alvo antes de stg e prd | `NATS.md` §7.5 |
| Partição do Observer | Na aplicação (`hash(resourceId) mod count`); o `DESIRED` não é particionado | decisão 0018 |
| Quarentena, `ObservationStale`, limite de remoções, retenção, métricas de aplicação e spans nos componentes | Pendentes | seções 2 a 6 |
| Ativação de ponta a ponta | Verificada em dev em 2026-10-12: a pessoa definiu a senha e confirmou o e-mail pelos links, e os reenvios pelo provedor funcionaram. Falta confirmar o `sk auth login` com esse usuário | `features/core/account/README.md` §4.7 |
| Configuração do Zitadel | Aplicada em dev por script temporário e não versionado; o mecanismo para stg e prd não está decidido | `infrastructure/dev/README.md` |
| Leitor tolerante | Implementado: os consumidores de mensagens internas (o Controller e as projeções locais da API) validam em modo tolerante, ignoram campos de `MINOR` mais novo e recusam `MAJOR` não suportado. A entrada de clientes e a publicação continuam estritas. Testes unitários em cada feature e caso no e2e (`schemaVersion` 1.1 com campo desconhecido) | `schemas/`, `common/contracts/base.py` de cada feature, `tests/common/unit/test_tolerant_reader.py` |
| Dados pessoais retidos | O `payload` do `desired` de criação (e-mail e nomes) permanece no outbox, e as Operations não são removidas, porque a retenção não existe; a limpeza do tombstone no `DESIRED` também não | `features/core/account/README.md` §11.6 |
| Catálogo do SUM (decisão 0079) | Atende: uma fonte só (o Controller), `managedRoles` no `desired` e rollout na partida do Controller quando o catálogo muda (`requested_by = system:catalog`), verificado em dev com a ligação real | `features/sum/service/README.md` |
| Recurso que não converge (decisão 0078) | Atende em parte: o Controller freia a ação sem efeito (backoff e aviso com os campos divergentes) e a condition `Progressing` com `progressDeadline` vale nas features com Controller. Sem Operation (decisão 0098), a falha por prazo aparece na fase `Failed` do recurso | `.decisions/0078-progresso-acao-sem-efeito-e-configuracao-visivel.md` |
| Retomada de `Failed` | A Account não tem `update`; a intervenção explícita não está definida | `features/core/account/README.md` §10 |
| Imagens em `docs/images/` | O infográfico do fluxo é do desenho antigo (Tenant, `api.*`); a arquitetura Kubernetes é uma proposta | `docs/images/README.md` |

## 7.1 Lacunas declaradas de dev e violações do piso (AGENTS §2.5)

Lacuna declarada: o que dev não tem, por que é aceitável em dev e a condição que a fecha **antes do stg**. Nada é promovido a stg com uma linha aberta aqui.

| Lacuna (dev) | Pilar | Por que é aceitável em dev | Condição de saída (antes do stg) |
|---|---|---|---|
| etcd do gateway sem autenticação nem TLS; a Admin API aceita a rede `internal` (com a chave) | Segurança, infraestrutura | rede interna do Compose, ambiente descartável | etcd com autenticação e TLS; Admin API fora da rede de carga (decisão 0049) |
| NATS com um só usuário e sem TLS | Segurança, infraestrutura | sem certificados em dev | identidade por serviço e TLS (`NATS.md`, seção 3 acima) |
| Senhas dos papéis montadas em `/run/secrets` a partir do `.env` (decisão 0070); não há cofre de segredos | Segurança, infraestrutura | o `.env` fica fora do git e a senha não aparece no ambiente do processo | cofre de segredos escolhido e senhas fornecidas por ele, sem valor trivial igual ao nome do papel (decisão 0070) |
| PostgreSQL sem TLS nem proteção em repouso | Segurança, infraestrutura | sem certificados nem cofre em dev | TLS e proteção em repouso (seção 4 acima) |
| HTTP sem TLS entre os componentes e o Zitadel ou o gateway (JWKS do Receiver, API do Zitadel no Observer e no Executor, consulta aos Receivers de outros módulos): os endereços padrão dos `settings` são `http://*.smarkee.internal` | Segurança, infraestrutura | rede `internal` do Compose, sem certificados | endereços `https://` por variável de ambiente nos manifestos de stg e prd, com certificado confiável; os padrões de dev ficam como estão |
| `telemetry-agent` roda como root e monta o socket do Docker (somente leitura) | Segurança, infraestrutura | é o modo de ler os logs dos contêineres no Compose; `cap_drop: ALL` e `no-new-privileges` reduzem o risco | DaemonSet que lê os logs do nó, sem o socket do Docker e sem root (`OBSERVABILITY.md` seção 10) |
| OTLP sem TLS nem autenticação entre APISIX, agente, `telemetry-router`, `platform-telemeter` e os telemeters das features | Segurança, infraestrutura | rede `internal` do Compose, sem certificados | TLS e autenticação no receptor OTLP |
| `telemetry-router`, `platform-telemeter` e os telemeters das features (`core-account`, `ipm-organization`, `ipm-user`, `sum-service`, `bsm-account`) únicos, sem backend: só arquivos com rotação em 10 MB (cerca de 4 h de métricas). As filas do agente e do roteador já são persistentes (decisões 0059 e 0062) | Resiliência, infraestrutura | não há consulta nem histórico longo em dev | backend persistente e alta disponibilidade do coletor |
| Estado da Billing Account (`bsm.account`) na fase P0 persistido em volume local Docker (`bsm-account-state`), compartilhado entre Executor (`rw`) e Observer (`:ro`) | Robustez e resiliência, infraestrutura | o objetivo de P0 é exercitar o contrato e o loop de controle da Billing Account antes de acoplar o motor financeiro definitivo | substituição do driver de disco local pelo provedor de faturamento definitivo antes do stg |
| Migração de `core/account` (S6.2, decisões 0098 e 0100) aplicada só no dev: migração `0011-account-api.sql`, papéis/logins `core_account_api` e `core_account_controller`, conta Zitadel `core-account-controller` (`ORG_USER_CREATOR` e `ORG_OWNER_VIEWER` na `register`; `PROJECT_GRANT_OWNER` nos Grants de `roles-core` e `roles-sum`), rota `core-account-api` no gateway e no `telemetry-router`, remoção dos consumers e contêineres antigos (`receiver`, `manager`, `executor`, `observer`, `reconciler`); contas `core-account-executor` e `core-account-observer` expurgadas do Zitadel no dev; suíte `tests/e2e` validada com sucesso contra a stack real | Segurança e robustez, infraestrutura | o provisionamento do Zitadel e do banco de dev é manual e o ambiente é descartável | repetir tudo em stg/prd e remover os papéis de banco antigos (`core_account_manager`, `core_account_receiver`) |
| Migração de `sum/service` (S6.3, decisões 0098 e 0100) aplicada só no dev: migração `0009-service-api.sql`, papéis/logins `sum_service_{api,controller,publisher,maintenance}`, conta Zitadel `sum-service-controller` (`ORG_OWNER_VIEWER` na `register`; `PROJECT_GRANT_OWNER` só no Grant de `roles-ipm`), rota `sum-service-api` no gateway e no `telemetry-router`, remoção dos consumers e contêineres antigos (`receiver`, `manager`, `executor`, `observer`, `reconciler`); contas `sum-service-executor` e `sum-service-observer` expurgadas do Zitadel no dev; suíte `tests/e2e` validada com sucesso contra a stack real | Segurança e robustez, infraestrutura | o provisionamento do Zitadel e do banco de dev é manual e o ambiente é descartável | repetir tudo em stg/prd e remover os papéis de banco antigos (`sum_service_manager`, `sum_service_receiver`, `sum_service_executor`, `sum_service_observer`, `sum_service_reconciler`) |
| NATS com um só nó e Streams com `num_replicas: 1`; volume único `messaging-data` | Resiliência, infraestrutura | dev é descartável e o `DESIRED` se reconstrói do SSOT (`scripts/dev/republish`) | cluster de 3 nós e `num_replicas: 3` nos Streams, com a perda de um nó exercitada |
| PostgreSQL com uma instância, sem réplica, sem alta disponibilidade e sem PITR; o backup de dev (`scripts/dev/backup`) é lógico (`pg_dump`), local ao host, e `verify` prova a restauração dos dados | Resiliência, infraestrutura | dev é descartável e o backup com restauração verificada já existe | alta disponibilidade, PITR, cópia fora do host e ensaio periódico de restauração (seção 4 acima) |
| Um processo por papel (`api`, `publisher` e `controller` de cada feature), sem réplicas. A `api` não guarda estado e o `publisher` troca de instância pela trava do banco (`pg_try_advisory_lock`), mas **mais de um `controller` não foi verificado**: cada instância tem consumers próprios e não há eleição de líder | Resiliência, infraestrutura | uma instância por papel basta em dev | decidir entre eleição de líder pela trava do banco e idempotência comprovada do provedor, e só então rodar mais de uma instância do `controller` |
| O estado do NATS (`messaging-data`) não entra no backup. `DESIRED` e as projeções se reconstroem com `scripts/dev/republish`; **`UPDATED` e `AUDIT` não** (o `UPDATED` é gravado pelo Controller no outbox ao convergir, e o `AUDIT` só existe no Stream) | Resiliência, infraestrutura | em dev não há dado de cliente, e nenhum componente consulta o `AUDIT` | decidir onde vive a trilha de auditoria (backup do Stream ou gravação no SSOT) antes de qualquer dado de cliente |
| `UPDATED` e `AUDIT` com `max_age` de 24h (decisão 0101): o `AUDIT` **não é uma trilha de auditoria durável** em dev | Segurança e resiliência, infraestrutura | sem dados reais, e 24h limita o volume em disco | retenção do `AUDIT` definida pela política de auditoria, com armazenamento durável |
| `DESIRED` com `max_age: 0` e tombstones sem limpeza: o `scripts/dev/retention` expurga `<tipo>_outbox` e `<tipo>_idempotency`, **não** os tombstones do Stream (`NATS.md` §15.4); só o `scripts/dev/cleanup` os remove, e apenas dos recursos de teste | Robustez, infraestrutura | o volume de dev é pequeno | job de limpeza por identidade administrativa, ou TTL por mensagem, antes de crescer o número de recursos removidos |
| Sem Stream de quarentena: a mensagem de estado que falha 20 vezes (`max_deliver`) recebe `TERM` e um log `ERROR`, e continua no Stream, mas não é copiada para outro lugar nem gera alerta | Resiliência, código | o estado se corrige na próxima mensagem do recurso ou na reavaliação periódica do Controller | alerta sobre o log `message discarded after the maximum number of deliveries` e decisão sobre a cópia para um Stream de quarentena (`NATS.md` §12) |
| A queda do NATS e a do banco **não têm teste automatizado**. O comportamento foi provado só à mão em 2026-10-28 (broker parado por 150 s, reconexão e `max_deliver` com um NATS descartável); a reconexão do pool após reinício do banco só tem teste unitário | Robustez, código | a correção é de código e vale em todo ambiente; a lacuna é de verificação | teste de integração que derruba o NATS e o banco e confirma a recuperação, rodado no CI |
| Projeto de roles `roles-bsm` ainda não provisionado na instância Zitadel de dev | Segurança, infraestrutura | o provisionamento do Zitadel de dev é manual; a audience `SMARKEE_GATEWAY_AUTH_AUDIENCE_BSM_ACCOUNT` e `BSM_ACCOUNT_RECEIVER_AUTH_AUDIENCE` são obrigatórias ao subir a feature | provisionar `roles-bsm` e incluir `bsm` no catálogo do SUM / IaC antes do stg |
| Condition `DriftLoop` não implementada no Controller (detecção de flapping / reconciliação cíclica em curto intervalo): a proteção ativa é o backoff exponencial e o `failure_limit` (5 falhas consecutivas) | Robustez, código | em dev o volume é baixo e a suspensão por `failure_limit` já interrompe laços infinitos | implementação da condition `DriftLoop` e testes de detecção de flapping antes de stg |

**Violações do piso em aberto** (segurança de código e configuração: não são lacunas declaráveis, §2.5 item 1): nenhuma.

**Exceções deliberadas** (AGENTS §4.3: deliberada, explícita e justificável; valem em todos os ambientes, e não só em dev):

| Exceção | Justificativa | Controles compensatórios | Quando rever |
|---|---|---|---|
| Papéis de instância `IAM_ORG_MANAGER` (Controller, decisão 0096; o Executor antigo foi removido) e `IAM_OWNER_VIEWER` (conta `ipm-organization-observer`, sem uso desde a remoção do Observer) da Organization, mais largos que o necessário (58 e 34 permissões; o primeiro inclui usuários, projetos e políticas) | O padrão do Zitadel v4.19.4 não tem papel menor para criar e listar organizações. Papéis customizados exigem substituir a lista inteira de `InternalAuthZ.RolePermissionMappings` (copiar e manter todos os padrões, valer só após `zitadel setup`), e não está confirmada a permissão do v2 para renomear, ativar, desativar e remover (o `AddOrganization` v2 exige `org.write` de instância: issue #12899). Decisão do responsável em 2026-10-18 | O Executor escreve só a organização (nunca usuário nem roles); contas só na organização `core`, uma por papel; chave de cada conta em volume (dono 10001, modo 0400), cada componente montando só a própria; validade da chave verificada pela suíte de conformidade | Se o Zitadel passar a oferecer um papel padrão menor, ou se a customização ficar barata de manter (decisão 0060) |

**Corrigido e verificado em 2026-10-18 (decisão 0059):** os logs de infra com e-mail, nome e código de verificação (o `WARN` "missing translation" do Zitadel), pelo teste `tests/telemetry`. Um item antes listado aqui, "query inteira nos spans", era um **falso positivo**: os valores de `url.query` já eram redigidos (`REDACTED`) pela normalização do `telemetry-router`, e o campo `args` nem chega ao arquivo.

# 8. Como manter

- Mudou um comportamento especificado? Atualize a especificação, a implementação e a linha correspondente aqui.
- Fechou uma lacuna? Troque a situação e cite a evidência (arquivo, teste ou comando).
- Itens **Alvo** só passam a **Atende** com verificação em stg ou prd.
- Uma lacuna de dev só é aceita se estiver na seção 7.1 com a condição de saída (AGENTS §2.5).
