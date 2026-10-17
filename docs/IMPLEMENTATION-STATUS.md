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
| Observabilidade | Parcial: logs estruturados e probes de saúde, spans do gateway e métricas de contêiner; sem métricas nem traces de aplicação. Logs no formato OpenTelemetry (`OBSERVABILITY.md`, decisão 0045) nos 18 componentes; em dev o `telemetry-agent` os coleta (com as métricas de contêiner) e o `telemetry-gateway` os grava no stdout (decisão 0051); o destino persistente ainda não existe |
| Retenção, quarentena, backup e recuperação | Pendente |
| Organization (`ipm`) | Atende para o loop completo (Receiver, Manager, Publisher, Reconciler, Observer e Executor), refeito a partir da Account (decisão 0038), com testes e2e contra a stack do dev e o Zitadel real: criar, renomear, desativar e reativar (`platformAccess`), remover e a queda de cada papel. O Executor escreve só a organização, sem Project Grant |
| SUM (`sum.service`) | Atende para o loop completo (Receiver, Manager, Publisher, Reconciler, Observer e Executor) e a CLI `sk sum service`, com testes e2e contra a stack do dev: ligar, desligar e a queda de Manager, Executor e Publisher, e o reinício de Reconciler e Observer no meio de uma ligação; e o teste de jornada (`tests/e2e`: cadastro, ativação, `sk auth login` interativo, ligar e desligar o `ipm` com a CLI real e a renovação da sessão). Pendente: verificação de e-mail do solicitante (decisão aberta), a Operation não vira `failed`, retenção das linhas desligadas, kill switch e visão de operador (`features/sum/service/README.md` §10) |
| CLI | Parcial: `sk config`, `sk auth login`, `sk auth whoami`, `sk register`, `sk sum service` e `sk ipm organization` implementados e testados (a jornada e2e usa a CLI real contra o dev); `sk account get\|delete` (consulta e exclusão segura da conta). Pendente: o client ID de produção (`000000000000000000`) e o endereço de stg e prd, que ainda não existem |

# 2. `RESOURCE-CONTROL-LOOP.md`: checklist de implementação (seção 55), por papel (`core.account`)

## 2.1 Modelo do recurso

| Item | Situação | Evidência |
|---|---|---|
| `resourceId` estável, `desired`, `observed`, `desiredGeneration`, lifecycle, conditions | Atende | `schemas/core/account/`, migração `core.account` |
| `observedGeneration` | Atende | Existe na `condition` (`observedGeneration`); o `observed` da Account não precisa dele |

## 2.2 Manager

| Item | Situação | Evidência |
|---|---|---|
| Dono do SSOT e do lifecycle; publica `desired`; processa `observed`; não executa provider | Atende | `manager/src/core_account_manager/handlers/` |
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

## 2.6 Componentes autocontidos (seção 48)

| Item | Situação | Evidência |
|---|---|---|
| Cada papel é um projeto autocontido, sem biblioteca comum | Atende | seis projetos em `features/core/account/` |
| Receiver com autenticação e autorização próprias | Atende | `receiver/.../auth/tokens.py` (JWKS) e `domain/principal.py` |
| Manager dono das migrações, executadas como etapa de implantação | Atende | `manager/migrations/`, serviço `core-account-migrate` |
| Publisher como papel próprio, com papel de banco e identidade próprios | Atende | `publisher/`, `core_account_publisher` |
| Contratos verificados por testes e2e black-box | Atende | `features/core/account/tests/e2e` |
| Estrutura interna da decisão 0017 | Atende | teste `test_domain_isolation.py` em cada projeto |

## 2.7 Mensagens

| Item | Situação | Evidência |
|---|---|---|
| Subject na gramática oficial, `messageType`, `operation`, `messageId` | Atende | validados pelo envelope e pelos testes e2e |
| `correlationId`, `causationId`, reentrega, ordering | Atende | propagados em todas as mensagens; ordem por `resourceId` (Subject, partição) e `sequence` do outbox |

# 3. `NATS.md`: checklist operacional (seção 31)

| Item | Situação | Evidência ou observação |
|---|---|---|
| Subject, emissor e destinatário (não embutido) | Atende | emissores `receiver`, `manager`, `observer`, `reconciler`, `executor`; o Publisher publica no emissor `manager` |
| Um Stream por `messageType`, com a retenção da classe | Atende | `infrastructure/dev/broker/bootstrap/` (seis Streams) |
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
| Métricas e traces | Pendente | só logs e probes |
| Streams e consumers gerenciados de forma controlada | Atende | `bootstrap/*.json` e serviço `<módulo>-<tipo>-consumer` |
| Versão do NATS pinada | Atende | `nats:2.15.0-alpine` |

# 4. `POSTGRESQL.md`: checklist (seção 20)

| Item | Situação | Evidência ou observação |
|---|---|---|
| Versão fixada | Atende | `postgres:18.6-alpine` |
| Banco `smarkee` do proprietário `smarkee`, sem privilégios de `PUBLIC` | Atende | `database/bootstrap/smarkee.sql` |
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
| Organization (`features/ipm/organization`) | Papéis de instância `IAM_ORG_MANAGER` (Executor) e `IAM_OWNER_VIEWER` (Observer): mais largos que o necessário; estreitar antes de prd. O nome `register` não é reservado (falha no Executor, `Rejected`) | `features/ipm/organization/README.md`, decisão 0038 |
| CLI | `sk config`, `sk auth`, `sk register`, `sk sum service`, `sk ipm organization` e `sk account get\|delete` | `ROADMAP.md` |
| `pinned_client` no Executor | Alvo antes de stg e prd | `NATS.md` §7.5 |
| Partição do Observer | Na aplicação (`hash(resourceId) mod count`); o `DESIRED` não é particionado | decisão 0018 |
| Quarentena, `ObservationStale`, limite de remoções, retenção, métricas e traces | Pendentes | seções 2 a 6 |
| Ativação de ponta a ponta | Verificada em dev em 2026-10-12: a pessoa definiu a senha e confirmou o e-mail pelos links, e os reenvios pelo provedor funcionaram. Falta confirmar o `sk auth login` com esse usuário | `features/core/account/README.md` §4.7 |
| Configuração do Zitadel | Aplicada em dev por script temporário e não versionado; o mecanismo para stg e prd não está decidido | `infrastructure/dev/README.md` |
| Leitor tolerante | Implementado: os consumidores de mensagens internas (Manager, Reconciler, Observer e Executor da Account e da Organization) validam em modo tolerante, ignoram campos de `MINOR` mais novo e recusam `MAJOR` não suportado. A entrada de clientes e a publicação continuam estritas. Testes unitários em cada projeto e caso no e2e (`schemaVersion` 1.1 com campo desconhecido) | `schemas/`, `contracts/base.py` de cada componente, `tests/unit/test_tolerant_reader.py` |
| Dados pessoais retidos | O `payload` do `desired` de criação (e-mail e nomes) permanece no outbox, e as Operations não são removidas, porque a retenção não existe; a limpeza do tombstone no `DESIRED` também não | `features/core/account/README.md` §11.6 |
| Retomada de `Failed` | A Account não tem `update`; a intervenção explícita não está definida | `features/core/account/README.md` §10 |
| Imagens em `docs/images/` | O infográfico do fluxo é do desenho antigo (Tenant, `api.*`); a arquitetura Kubernetes é uma proposta | `docs/images/README.md` |

# 8. Como manter

- Mudou um comportamento especificado? Atualize a especificação, a implementação e a linha correspondente aqui.
- Fechou uma lacuna? Troque a situação e cite a evidência (arquivo, teste ou comando).
- Itens **Alvo** só passam a **Atende** com verificação em stg ou prd.
