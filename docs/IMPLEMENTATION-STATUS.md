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
| Loop completo da Account (Receiver, Manager, Publisher, Reconciler, Observer, Executor) | Atende: cadastro anônimo até `Ready` e remoção, contra o Zitadel e o Mailpit reais |
| Contratos (JSON Schema, modelos gerados, OpenAPI) | Atende: 268 testes dos schemas; modelos regerados e conferidos por teste em cada projeto |
| Estrutura interna (`domain/` puro, camadas, saúde) | Atende nos seis papéis, com teste de isolamento do `domain/` em cada projeto |
| Resiliência | Atende para queda de Manager, Executor e Publisher (testes e2e com `E2E_CHAOS=1`); queda do NATS e do banco não é testada |
| Segurança de transporte e identidade no barramento | **Alvo**: dev usa um só usuário NATS, sem TLS |
| Observabilidade | Parcial: logs estruturados e probes de saúde, spans do gateway e métricas de contêiner; o `traceparent` do gateway é propagado até os componentes e os logs trazem `trace_id` (decisão 0055) e o contexto de negócio (ator, recurso, ação, dono e organização, decisão 0061); sem spans nem métricas de aplicação, e o span do gateway ainda sem o contexto. Logs no formato OpenTelemetry (`OBSERVABILITY.md`, decisão 0045) nos 18 contêineres; em dev o `telemetry-agent` os coleta (com as métricas de contêiner) e os telemeters (`platform-telemeter` e o de cada feature) os gravam em arquivos com rotação, depois do `telemetry-router` (decisões 0051 e 0062); o destino persistente ainda não existe |
| Retenção, quarentena, backup e recuperação | Pendente |
| Organization (`ipm`) | Atende para o loop completo (Receiver, Manager, Publisher, Reconciler, Observer e Executor), refeito a partir da Account (decisão 0038), com testes e2e contra a stack do dev e o Zitadel real: criar, renomear, desativar e reativar (`platformAccess`), remover e a queda de cada papel. O Executor escreve a organização e o preparo dela para os usuários (Project Grant de `roles-ipm` e papéis das contas do `ipm/user`, decisão 0081), e o Manager observa `manager.desired.ipm.permission.>` via NATS para atualizar dinamicamente o `grantPermissions` sem exigir redeploy (decisão 0083) |
| Catálogo de Permissões (`ipm.permission`) e de Roles (`ipm.role`) | Atende: contratos (`schemas/ipm/permission/` e `schemas/ipm/role/`), os seis papéis do loop (`features/ipm/permission/` e `features/ipm/role/`), migrações com sementes do catálogo inicial (`0001-permission.sql` e `0001-role.sql`), bootstrap do banco (`ipm.sql`), gateway (`/v1/ipm/permissions` e `/v1/ipm/roles`) e telemetria implementados e verificados (decisão 0083). `ipm.permission` gerencia as permissões atômicas (`<módulo>.<tipo>.<ação>`) nos projetos `roles-<módulo>` do Zitadel; `ipm.role` gerencia as Roles compostas no padrão Google Cloud IAM (`<módulo>.<tipo><Admin\|Viewer>`) exclusivamente na Smarkee: a definição no SSOT e o estado aplicado no banco `platform` (plano de dados multi-tenant, decisão 0086), sem criar projetos ou objetos adicionais no Zitadel. Desde a decisão `0092`, uma Organization cria Roles `custom` (permissões `ipm.role.create\|update\|delete\|bind`, só com permissões `grantable`, nome único por Organization, cota de 10, `409 ResourcesAttached` se em uso) e a CLI `sk ipm role` aceita `--organization-id` |
| Grupo da Organization (`ipm.group`) | Atende: contratos (`schemas/ipm/group/`), os seis papéis do loop (`features/ipm/group/`), migração (`0001-group.sql`), tabelas de plano de dados no banco `platform` (`ipm.group` e `ipm.group_role`, decisão 0086), gateway (`/v1/ipm/groups`), telemetria e CLI (`sk ipm group`) implementados e verificados por testes unitários, de contrato e e2e contra a stack em execução (decisão 0088). Exige `ipm.group.bind` para atribuir ou alterar `roles` quando o solicitante é membro da Organization, nasce com `deletionProtection: false` e bloqueia `DELETE` com `409 ResourcesAttached` enquanto houver usuários (`ipm.user`) associados ao grupo |
| Usuário da Organization (`ipm.user`) | Atende para o loop completo (Receiver, Manager, Publisher, Reconciler, Observer e Executor) e a CLI `sk ipm user`, com suporte a permissões atômicas (`permissions`), Roles compostas (`roles`, decisão 0083) e Grupos da Organization (`groups`, decisão 0088), expandidos em permissões atômicas. Consome `manager.desired.ipm.permission.>`, `manager.desired.ipm.role.>` e `manager.desired.ipm.group.>` em tempo real para validar catálogos e re-expandir permissões sem redeploy, e exige estritamente `ipm.user.bind` para atribuir ou alterar `permissions`, `roles` ou `groups` |
| Billing Account (`bsm.account`) | Atende: contratos (`schemas/bsm/account/`), os seis papéis do loop (`features/bsm/account/`), migração (`0001-account.sql`), bootstrap do banco (`bsm.sql`), gateway (`/v1/bsm/accounts`), projeto `roles-bsm` no Zitadel, telemetria e CLI (`sk bsm account`) implementados e verificados por testes unitários, de contrato, de integração e e2e contra a stack em execução (decisão 0082). O `bsm` é uma capacidade de nível de conta (`core.account`): as roles `bsm.account.*` vêm de `DEFAULT_PLATFORM_ROLES` no cadastro e o Manager provisiona a conta `"Free Tier"` quando `core.account` converge para `Ready`. Na fase P0, o Executor e o Observer operam sobre estado local em disco (`bsm-account-state`), como lacuna declarada até a integração com Gateway de Pagamentos na fase P3 (`docs/billing/BILLING.md`) |
| SUM (`sum.service`) | Atende para o loop completo (Receiver, Manager, Publisher, Reconciler, Observer e Executor) e a CLI `sk sum service`, com testes e2e contra a stack do dev: ligar, desligar e a queda de Manager, Executor e Publisher, e o reinício de Reconciler e Observer no meio de uma ligação; e o teste de jornada (`tests/e2e`: cadastro, ativação, `sk auth login` interativo, ligar e desligar o `ipm` com a CLI real e a renovação da sessão). Pendente: verificação de e-mail do solicitante (decisão aberta), a Operation não vira `failed`, retenção das linhas desligadas, kill switch e visão de operador (`features/sum/service/README.md` §10) |
| CLI | Parcial: `sk config`, `sk auth login`, `sk auth whoami`, `sk sum service`, `sk ipm organization`, `sk ipm permission`, `sk ipm role`, `sk ipm group`, `sk ipm user` e `sk bsm account` implementados e testados (a jornada e2e usa a CLI real contra o dev); `sk account create|get|delete` (cadastro, consulta e exclusão segura da conta). Pendente: o client ID de produção (`000000000000000000`) e o endereço de stg e prd, que ainda não existem |

# 2. `RESOURCE-CONTROL-LOOP.md`: checklist de implementação (seção 55), por papel (`core.account`)

## 2.1 Modelo do recurso

| Item | Situação | Evidência |
|---|---|---|
| `resourceId` estável, `desired`, `observed`, `desiredGeneration`, lifecycle, conditions | Atende | `schemas/core/account/`, migração `core.account` |
| `observedGeneration` | Atende | Coluna `observed_generation` (migração `0008`), preenchida pelo Manager só com uma observação feita depois da geração (o Observer envia o `observedGeneration` no envelope); publicada no `updated` com `desiredGeneration` e na `condition` (decisão 0072). Ainda não exposta na view do Receiver |

## 2.2 Manager

| Item | Situação | Evidência |
|---|---|---|
| Dono do SSOT e do lifecycle; publica `desired`; processa `observed`; não executa provider | Atende | `features/core/account/src/core_account/manager/handlers/` |
| Outbox na mesma transação | Atende | `store/ssot.py`, `handlers/publishing.py`; testes de integração |
| Conta falhas por geração, marca `Failed` e suspende no `desired` | Atende | `domain/convergence.py` (`decide_result`), limite 5 |
| Registra `ObservationStale` | Pendente | A condition não é registrada |

## 2.3 Observer

| Item | Situação | Evidência |
|---|---|---|
| Somente leitura, observa a realidade, publica `observed` com `observedAt` | Atende | conta `core-account-observer` (`ORG_OWNER_VIEWER`) |
| Periódico, distingue `present`, `absent`, `unknown` | Atende | 5 min com jitter; `absent` só com 404 inequívoco |
| Observa só a sua partição | Atende | `hash(resourceId) mod count` (em dev, `0/1`) |
| Observa após `completed` e `failed`, com `causationId` | Atende | `engine/observer.py` |

## 2.4 Reconciler

| Item | Situação | Evidência |
|---|---|---|
| Consome `desired` e `observed`, compara, reavalia periodicamente | Atende | `domain/decision.py`, `engine/reconciler.py` |
| Decide só com estados conclusivos e válidos; não reemite `action` pendente | Atende | validade 10 min (5 min para `delete`), prazo 2 min |
| Respeita `desired` suspenso, aplica backoff, aguarda a observação causada | Atende | backoff 5 s a 300 s |
| `actionId` inclui a observação | Atende | `<id>.<geração>.<operação>.<messageId do observed>` |
| Não executa a ação | Atende | não tem credencial do provedor |

## 2.5 Executor

| Item | Situação | Evidência |
|---|---|---|
| Privilégios mínimos | Atende | `ORG_USER_CREATOR` na `register` (sem conceder roles) e `PROJECT_GRANT_OWNER` só nos Grants de `core` e `sum`; as roles saem do Project Grant de cada módulo (sem as `*.admin`); monta só a própria chave |
| Revalida a `action` e consulta o desfecho do `actionId` | Atende | `domain/revalidation.py`, `engine/executor.py` (Direct Get) |
| Chave de correlação com o recurso externo | Atende | `userId = resourceId` |
| *Single-flight* por recurso | Atende | uma partição por `resourceId`, `max_ack_pending=1` (decisão 0018) |
| Limita taxa e concorrência contra o provider | Parcial | concorrência limitada a 4 partições; sem limite de taxa explícito (429 do Zitadel vira falha retentável) |
| Idempotência, publica `completed`/`failed`, não decide o estado desejado | Atende | `actions/user_actions.py` |

## 2.6 Componentes por papel (seção 48)

| Item | Situação | Evidência |
|---|---|---|
| Cada papel roda como processo e contêiner próprios; a feature é um projeto e uma imagem (decisão 0063), sem um papel importar outro | Atende nas três features: um projeto e uma imagem por feature (`core-account`, `ipm-organization`, `sum-service`), seis contêineres cada um, e `tests/common/unit/test_role_isolation.py` | `features/core/account/`, `features/ipm/organization/` e `features/sum/service/` |
| Receiver com autenticação e autorização próprias | Atende | `receiver/auth/tokens.py` (JWKS) e `receiver/domain/principal.py`, em `features/core/account/src/core_account/` |
| Manager dono das migrações, executadas como etapa de implantação | Atende | `features/core/account/migrations/`, serviço `core-account-migrate` |
| Publisher como papel próprio, com papel de banco e identidade próprios | Atende | `features/core/account/src/core_account/publisher/`, papel de banco `core_account_publisher` |
| Contratos verificados por testes e2e black-box | Atende | `features/core/account/tests/e2e` |
| Estrutura interna da decisão 0017 | Atende | teste `test_domain_isolation.py` em cada papel (`tests/<papel>/unit/` em `core.account`) |

## 2.7 Mensagens

| Item | Situação | Evidência |
|---|---|---|
| Subject na gramática oficial, `messageType`, `operation`, `messageId` | Atende | validados pelo envelope e pelos testes e2e |
| `correlationId`, `causationId`, reentrega, ordering | Atende | propagados em todas as mensagens; ordem por `resourceId` (Subject, partição) e `sequence` do outbox |

# 3. `NATS.md`: checklist operacional (seção 31)

| Item | Situação | Evidência ou observação |
|---|---|---|
| Subject, emissor e destinatário (não embutido) | Atende | emissores `receiver`, `manager`, `observer`, `reconciler`, `executor`; o Publisher publica no emissor `manager` |
| Um Stream por `messageType`, com a retenção da classe | Atende | `infrastructure/dev/messaging/bootstrap/` (seis Streams) |
| `desired` e `observed` com a operação `changed` | Atende | `manager.desired.core.account.<id>.changed` |
| `WorkQueue` com `DiscardNew` e consumers sem filtro sobreposto | Atende | `REQUESTED` e `ACTION`; no `ACTION`, um consumer por partição, de filtros disjuntos |
| Consumer de estado por instância (`DeliverLastPerSubject`, nome único, `inactive_threshold`) | Atende | Reconciler e Observer |
| Consumer de trabalho ou persistência durável e compartilhado | Atende | `core-account-manager-{requested,observed,result}` |
| Um único filtro por consumer, no nível `<módulo>.<tipo>` | Parcial | o do Executor adiciona o token da partição (`reconciler.action.core.account.<p>.>`), mais estreito, por decisão 0018 |
| Executor: consumer por partição, `max_ack_pending=1`, Direct Get do `desired` | Atende | |
| Executor com `pinned_client` | Alvo | em dev há uma só instância, sem `pinned_client` (`NATS.md` §7.5) |
| Nenhum serviço de runtime com purge ou administração de Stream | Alvo | em dev, todos usam o mesmo usuário NATS |
| Pull Consumer, ACK após o processamento, retry com backoff | Atende | consumers do Manager e do Executor |
| Quarentena de mensagens *poison* | Pendente | a mensagem inválida recebe `TERM` e é registrada em log |
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
| Tabelas e views geradas do modelo | Parcial | seguem o modelo, mas as migrações são escritas à mão |
| `CHECK` em `lifecycle`, `reconciliation`, `presence`, `phase`, `operation_status`, identificadores e `jsonb` | Atende | `core.account` (todas as colunas de controle e de identificação) |
| `FOR UPDATE` na linha; `resource_version` na condição; conflito na Operation | Atende | `store/ssot.py` |
| Geração só incrementa quando a especificação muda | Atende | `change_desired` |
| Deduplicação por `operation_id` e `action_id`, com filtro de geração | Atende | `handlers/requested.py`, `handlers/result.py` |
| Publisher: uma instância ativa, sequencial, sem marca-d'água e sem `SKIP LOCKED`; marca só após confirmação | Atende | `publisher/.../outbox/publication.py` |
| Matriz de privilégios igual à de segurança | Atende | `features/core/account/README.md` §8.1 |
| Receiver só lê as views; Manager sem `DELETE` em outbox, resultados e operation | Atende | migração `0001-account.sql` |
| Papéis de login com `search_path`, `lock_timeout`, `statement_timeout`, `idle_in_transaction_session_timeout` | Atende | `database/bootstrap/core.sql` |
| Identidade de manutenção para a retenção | Parcial | o papel `core_maintenance` existe; não há tarefa de retenção |
| TLS e proteção em repouso | Alvo | |
| Parâmetros e colunas `confidential` fora dos logs | Parcial | verificado por revisão (o log não registra mensagens de exceção nem valores); sem teste automatizado de varredura |
| PITR, teste de restauração e recuperação | Pendente | |
| Migrações expandir → migrar → contrair, por infraestrutura | Parcial | executadas por `core-account-migrate`, idempotentes; sem controle de versão (obrigatório antes de stg e prd) |

# 5. `SSOT.md`: checklist (seção 21)

| Item | Situação | Evidência |
|---|---|---|
| Manager único escritor; unidade atômica por mensagem; acesso exclusivo ao registro; ACK após a gravação | Atende | `handlers/`, `transport/consumers.py` |
| Rejeições na Operation, com motivo | Atende | `validation`, `conflict`, `not_found`, `protected` (só nos tipos com proteção contra exclusão, decisão 0043) |
| Outbox na mesma unidade; ordem por recurso preservada | Atende | Manager e Publisher |
| Idempotência semântica de `requested`, `observed` e `completed`/`failed` | Atende | testes de integração do Manager |
| `desiredGeneration` e `resourceVersion` | Atende | |
| Dicionário de dados com sensibilidade e escritor | Atende | `SSOT.md` §8 e `x-sensitivity`/`x-writer` nos schemas |
| Privilégios mínimos por tipo | Atende | |
| Estrutura gerada de um modelo | Parcial | ver a seção 4 |
| Backup com recuperação a um ponto no tempo e teste de restauração | Pendente | |
| Sinais de observabilidade | Parcial | o atraso do outbox e a idade da observação são consultáveis por SQL e mensagens; não há métricas exportadas |
| Mensagens publicadas removidas após a retenção | Pendente | não há tarefa de retenção |

# 6. `RESOURCE-CONTROL-SECURITY.md`: checklist (seção 15)

| Item | Situação | Evidência ou observação |
|---|---|---|
| Identidade própria por serviço | Parcial | nomes `core-account-<papel>`, papéis de banco e contas do Zitadel próprios; no NATS, usuário único em dev |
| Permissões de publicação e consumo pela matriz, escopadas por `<módulo>.<tipo>` | Alvo | |
| Sem purge nem administração de Stream para serviços; limpeza de tombstones por identidade administrativa | Alvo / Pendente | |
| `resourceId` validado antes de compor o Subject | Atende | padrão do contrato e `CHECK`; o Receiver gera UUIDv7 |
| Executor revalida e consulta o desfecho do `actionId` | Atende | |
| Observação periódica particionada; distingue `present`, `absent` e `unknown`; destrutiva exige observação recente | Atende | |
| Limite de remoções por janela | Pendente | |
| Observer só leitura; Executor com escrita de escopo mínimo | Atende | |
| Nenhum segredo em mensagens, logs ou erros | Atende | senha nunca trafega; chaves por arquivo montado |
| Ator acompanha a operação | Atende | `requestedBy` em `desired`, `action` e resultados |
| Isolamento por organization | Parcial | definido para a Organization (decisão 0010); a Account não tem organização |
| Eventos de segurança observáveis | Parcial | só em logs estruturados |

# 7. Lacunas conhecidas e desvios deliberados

| Tema | Situação | Referência |
|---|---|---|
| Organization (`features/ipm/organization`) | Papéis de instância `IAM_ORG_MANAGER` (Executor) e `IAM_OWNER_VIEWER` (Observer): mais largos que o necessário, por exceção deliberada (AGENTS §4.3, decisão 0060): ver 7.1. O nome `register` não é reservado (falha no Executor, `Rejected`) | `features/ipm/organization/README.md`, decisão 0038 |
| Usuário da Organization (`features/ipm/user`) | A lacuna da decisão 0077 (Grant e papéis por organização feitos pelo operador) está **fechada** pela decisão 0081: o loop da `ipm/organization` prepara cada Organization, e o catálogo é o enum `grantableRole` do contrato. Trocar a conta do Executor ou do Observer do User não retira os papéis da antiga (limitação declarada). A cota de 5 usuários por Organization é provisória | `features/ipm/user/README.md`, `.decisions/0081-organization-pronta-para-usuarios-pelo-loop.md` |
| CLI | `sk config`, `sk auth`, `sk sum service`, `sk ipm organization`, `sk ipm user` e `sk account create|get|delete` | `ROADMAP.md` |
| `pinned_client` no Executor | Alvo antes de stg e prd | `NATS.md` §7.5 |
| Partição do Observer | Na aplicação (`hash(resourceId) mod count`); o `DESIRED` não é particionado | decisão 0018 |
| Quarentena, `ObservationStale`, limite de remoções, retenção, métricas de aplicação e spans nos componentes | Pendentes | seções 2 a 6 |
| Ativação de ponta a ponta | Verificada em dev em 2026-10-12: a pessoa definiu a senha e confirmou o e-mail pelos links, e os reenvios pelo provedor funcionaram. Falta confirmar o `sk auth login` com esse usuário | `features/core/account/README.md` §4.7 |
| Configuração do Zitadel | Aplicada em dev por script temporário e não versionado; o mecanismo para stg e prd não está decidido | `infrastructure/dev/README.md` |
| Leitor tolerante | Implementado: os consumidores de mensagens internas (Manager, Reconciler, Observer e Executor da Account e da Organization) validam em modo tolerante, ignoram campos de `MINOR` mais novo e recusam `MAJOR` não suportado. A entrada de clientes e a publicação continuam estritas. Testes unitários em cada feature e caso no e2e (`schemaVersion` 1.1 com campo desconhecido) | `schemas/`, `common/contracts/base.py` de cada feature, `tests/common/unit/test_tolerant_reader.py` |
| Dados pessoais retidos | O `payload` do `desired` de criação (e-mail e nomes) permanece no outbox, e as Operations não são removidas, porque a retenção não existe; a limpeza do tombstone no `DESIRED` também não | `features/core/account/README.md` §11.6 |
| Catálogo do SUM (decisão 0079) | Atende: uma fonte só (o Manager), `managedRoles` no `desired` e rollout na partida do Manager quando o catálogo muda, verificado em dev com a ligação real | `features/sum/service/README.md` |
| Recurso que não converge (decisão 0078) | Atende em parte: o Reconciler das quatro features freia a ação sem efeito (backoff e aviso com os campos divergentes); a condition `Progressing` com `progressDeadline` vale nas quatro features (no `sum/service` desde a decisão 0080). Pendente: a Operation virar `failed` no prazo esgotado | `.decisions/0078-progresso-acao-sem-efeito-e-configuracao-visivel.md` |
| Retomada de `Failed` | A Account não tem `update`; a intervenção explícita não está definida | `features/core/account/README.md` §10 |
| Imagens em `docs/images/` | O infográfico do fluxo é do desenho antigo (Tenant, `api.*`); a arquitetura Kubernetes é uma proposta | `docs/images/README.md` |

## 7.1 Lacunas declaradas de dev e violações do piso (AGENTS §2.5)

Lacuna declarada: o que dev não tem, por que é aceitável em dev e a condição que a fecha **antes do stg**. Nada é promovido a stg com uma linha aberta aqui.

| Lacuna (dev) | Pilar | Por que é aceitável em dev | Condição de saída (antes do stg) |
|---|---|---|---|
| etcd do gateway sem autenticação nem TLS; a Admin API aceita a rede `internal` (com a chave) | Segurança, infraestrutura | rede interna do Compose, ambiente descartável | etcd com autenticação e TLS; Admin API fora da rede de carga (decisão 0049) |
| Banco `platform` (decisão 0086) no mesmo servidor do SSOT, com senhas triviais dos papéis (`platform`, `ipm_role_executor_login`, `ipm_role_observer_login`), sem réplica nem backup próprio além do script de dev e com `CONNECT` público no banco `postgres` | Segurança, robustez e resiliência, infraestrutura | dev tem um só servidor e sem cofre de segredos | servidor ou cluster dedicado com backup e réplica, segredos no cofre e `CONNECT` público revogado |
| NATS com um só usuário e sem TLS | Segurança, infraestrutura | sem certificados em dev | identidade por serviço e TLS (`NATS.md`, seção 3 acima) |
| Senhas dos papéis montadas em `/run/secrets` a partir do `.env` (decisão 0070); não há cofre de segredos | Segurança, infraestrutura | o `.env` fica fora do git e a senha não aparece no ambiente do processo | cofre de segredos escolhido e senhas fornecidas por ele, sem valor trivial igual ao nome do papel (decisão 0070) |
| PostgreSQL sem TLS nem proteção em repouso | Segurança, infraestrutura | sem certificados nem cofre em dev | TLS e proteção em repouso (seção 4 acima) |
| HTTP sem TLS entre os componentes e o Zitadel ou o gateway (JWKS do Receiver, API do Zitadel no Observer e no Executor, consulta aos Receivers de outros módulos): os endereços padrão dos `settings` são `http://*.smarkee.internal` | Segurança, infraestrutura | rede `internal` do Compose, sem certificados | endereços `https://` por variável de ambiente nos manifestos de stg e prd, com certificado confiável; os padrões de dev ficam como estão |
| `telemetry-agent` roda como root e monta o socket do Docker (somente leitura) | Segurança, infraestrutura | é o modo de ler os logs dos contêineres no Compose; `cap_drop: ALL` e `no-new-privileges` reduzem o risco | DaemonSet que lê os logs do nó, sem o socket do Docker e sem root (`OBSERVABILITY.md` seção 10) |
| OTLP sem TLS nem autenticação entre APISIX, agente, `telemetry-router`, `platform-telemeter` e os telemeters das features | Segurança, infraestrutura | rede `internal` do Compose, sem certificados | TLS e autenticação no receptor OTLP |
| `telemetry-router`, `platform-telemeter` e os telemeters das features (`core-account`, `ipm-organization`, `ipm-user`, `sum-service`, `bsm-account`) únicos, sem backend: só arquivos com rotação em 10 MB (cerca de 4 h de métricas). As filas do agente e do roteador já são persistentes (decisões 0059 e 0062) | Resiliência, infraestrutura | não há consulta nem histórico longo em dev | backend persistente e alta disponibilidade do coletor |
| Estado da Billing Account (`bsm.account`) na fase P0 persistido em volume local Docker (`bsm-account-state`), compartilhado entre Executor (`rw`) e Observer (`:ro`) | Robustez e resiliência, infraestrutura | o objetivo de P0 é exercitar o contrato e o loop de controle da Billing Account antes de acoplar o motor financeiro definitivo | substituição do driver de disco local pelo provedor de faturamento definitivo antes do stg |
| Projeto de roles `roles-bsm` ainda não provisionado na instância Zitadel de dev | Segurança, infraestrutura | o provisionamento do Zitadel de dev é manual; a audience `SMARKEE_GATEWAY_AUTH_AUDIENCE_BSM_ACCOUNT` e `BSM_ACCOUNT_RECEIVER_AUTH_AUDIENCE` são obrigatórias ao subir a feature | provisionar `roles-bsm` e incluir `bsm` no catálogo do SUM / IaC antes do stg |
| Roles `custom` por Organization (decisão `0092`): `GrantablePermission` (`schemas/ipm/definitions.v1.schema.json`), o catálogo do SUM (`SUM_SERVICE_MANAGER_CATALOG_PERMISSIONS`) e o `grant_catalog` de `ipm/organization` ainda não incluem `ipm.group.*` e `ipm.role.*`, então o root e os membros de uma Organization nova não os recebem no token até serem estendidos; além disso há uma janela de corrida entre a checagem do Receiver (cota, permissões do usuário) e o pedido | Segurança, robustez | em dev os Grants e a autorização do operador foram ajustados à mão no Zitadel e a cota é reconferida no Manager (advisory lock) | estender os três catálogos (decisão própria) e repetir Grants e autorizações em stg e prd |

**Violações do piso em aberto** (segurança de código e configuração: não são lacunas declaráveis, §2.5 item 1): nenhuma.

**Exceções deliberadas** (AGENTS §4.3: deliberada, explícita e justificável; valem em todos os ambientes, e não só em dev):

| Exceção | Justificativa | Controles compensatórios | Quando rever |
|---|---|---|---|
| Papéis de instância `IAM_ORG_MANAGER` (Executor) e `IAM_OWNER_VIEWER` (Observer) da Organization, mais largos que o necessário (58 e 34 permissões; o primeiro inclui usuários, projetos e políticas) | O padrão do Zitadel v4.19.4 não tem papel menor para criar e listar organizações. Papéis customizados exigem substituir a lista inteira de `InternalAuthZ.RolePermissionMappings` (copiar e manter todos os padrões, valer só após `zitadel setup`), e não está confirmada a permissão do v2 para renomear, ativar, desativar e remover (o `AddOrganization` v2 exige `org.write` de instância: issue #12899). Decisão do responsável em 2026-10-18 | O Executor escreve só a organização (nunca usuário nem roles); contas só na organização `core`, uma por papel; chave de cada conta em volume (dono 10001, modo 0400), cada componente montando só a própria; validade da chave verificada pela suíte de conformidade | Se o Zitadel passar a oferecer um papel padrão menor, ou se a customização ficar barata de manter (decisão 0060) |

**Corrigido e verificado em 2026-10-18 (decisão 0059):** os logs de infra com e-mail, nome e código de verificação (o `WARN` "missing translation" do Zitadel), pelo teste `tests/telemetry`. Um item antes listado aqui, "query inteira nos spans", era um **falso positivo**: os valores de `url.query` já eram redigidos (`REDACTED`) pela normalização do `telemetry-router`, e o campo `args` nem chega ao arquivo.

# 8. Como manter

- Mudou um comportamento especificado? Atualize a especificação, a implementação e a linha correspondente aqui.
- Fechou uma lacuna? Troque a situação e cite a evidência (arquivo, teste ou comando).
- Itens **Alvo** só passam a **Atende** com verificação em stg ou prd.
- Uma lacuna de dev só é aceita se estiver na seção 7.1 com a condição de saída (AGENTS §2.5).
