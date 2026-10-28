# ipm.organization: fluxo de dados (do `POST` até a organização no Zitadel)

Documento de fluxo de dados da feature `ipm.organization`, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md) e das decisões de arquitetura:
- [0006](../../../../.decisions/0006-organization-como-unidade-de-isolamento.md): Organization como unidade primária de isolamento multi-tenant;
- [0096](../../../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md): unificação do loop de reconciliação no Controller;
- [0098](../../../../.decisions/0098-api-sincrona-e-fim-da-operation.md): API síncrona e extinção da Operation;
- [0100](../../../../.decisions/0100-desacoplamento-http-ipm-e-projecoes-desejado.md): desacoplamento total de chamadas HTTP mútuas entre features via Informers e projeções no Stream `DESIRED`.

Todos os passos rodam no dev (Docker Compose) e são verificados pela suíte e2e (`tests/e2e`).

**Comando.** `sk ipm organization create|get|list|update|protect|unprotect|delete` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

A Organization vive no Zitadel como uma organização com ID correspondente ao `resourceId`. Pertence ao perfil **`external-reconciled`**: possui `api`, `publisher` e `controller`.

O pedido é admitido de forma síncrona pela API (`ipm-organization-api`), que grava a intenção no SSOT (`phase: Pending`). O Publisher (`ipm-organization-publisher`) publica no Stream `DESIRED`, e o Controller (`ipm-organization-controller`) provisiona a organização no Zitadel via gRPC/HTTP (`OrgService`), configura o `userAccess` e promove a fase para `Ready`.

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → API | `POST /v1/ipm/organizations` (via gateway) | `{name, billingAccountId, ...}` | nada |
| 2 | API → banco `ssot` | SQL, uma transação atômica | `201 Created` (`Resource` em `phase: Pending`) | `ipm.organization`, `ipm.organization_outbox`, `ipm.organization_idempotency` |
| 3 | Publisher → NATS | JetStream, Stream `DESIRED` | `desired` (`desired.ipm.organization.<id>`) | `ipm.organization_outbox.published_at` |
| 4 | Controller → Zitadel; Controller → SSOT | HTTP no Zitadel (OrgService); SQL transacional | Criação da Org e userAccess | `ipm.organization` (`phase: Ready`, `observedGeneration: 1`) |

Diagramas de arquitetura e estados:
- Componentes: [`architecture/01-componentes.svg`](architecture/01-componentes.svg)
- Modelo de dados (ER): [`database/01-er-fisico.svg`](database/01-er-fisico.svg)
- Fases do recurso: [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg)
- Fluxos: criação [`flow/01-criar-organization.svg`](flow/01-criar-organization.svg), validação [`flow/02-validacao-e-borda.svg`](flow/02-validacao-e-borda.svg), atualização e remoção [`flow/03-atualizar-e-remover.svg`](flow/03-atualizar-e-remover.svg), falhas [`flow/04-falhas-na-api-e-mensageria.svg`](flow/04-falhas-na-api-e-mensageria.svg).

### Identificadores que ligam tudo

| Campo | Quem cria | Formato | Papel |
|---|---|---|---|
| `resourceId` | API | UUIDv7 minúsculo | Identidade primária da Organization no SSOT e orgId no Zitadel. |
| `ownerAccountId` | Token JWT (`sub`) | UUIDv7 minúsculo | Usuário dono da Organization. |
| `name` | Solicitante | string até 64 chars | Nome da organização (único globalmente). |
| `messageId` | API (na outbox) | UUIDv7 | É o `Nats-Msg-Id` (deduplicação) e a chave única do outbox. |
| `correlationId` | API | UUIDv7 (propagado ou gerado) | Rastreia a requisição de ponta a ponta. |
| `resourceVersion` | API | inteiro serializado como string | Concorrência otimista no `PATCH` e `DELETE`. |
| `Idempotency-Key` | Cliente (opcional) | string até 128 chars | Garante idempotência na admissão da API. |

---

## 1. CLI → API: `POST /v1/ipm/organizations`

A API `ipm-organization-api`:
- Valida o token JWT (audience `roles-ipm`). O dono é o `sub`.
- Exige `ipm.organization.create` e e-mail verificado.
- Valida cota de organizações do dono.
- Valida `billingAccountId` via cache local `BillingAccountProjection` (sem chamadas HTTP a `bsm.account`, decisão 0100).
- Insere na tabela `ipm.organization` com `phase: Pending` e `generation: 1`, grava na outbox e responde síncrono `201 Created`.

---

## 2. Publicação Assíncrona: `ipm-organization-publisher`

Drena o outbox pendente em ordem de `sequence` e publica em `desired.ipm.organization.<resourceId>`.

---

## 3. Reconciliação Unificada: `ipm-organization-controller`

O Controller:
1. Consome os eventos do Stream `DESIRED`.
2. Observa o Zitadel via `OrgService.GetOrgByID`:
   - Se ausente: chama `AddOrg(name, orgId=resourceId)` e configura metadados e permissões de acesso (`userAccess`).
   - Se divergente: atualiza o nome.
   - Se remoção solicitada (`lifecycle = absent`): chama `RemoveOrg(orgId)`.
3. Reobserva a organização no Zitadel e atualiza `ipm.organization` no banco `ssot` para `phase: Ready` com `observed_generation = generation`. No caso de remoção convergida, apaga a linha física no SSOT.

---

## 4. Remoção e Proteção contra Exclusão com Dependentes

- Exclusão com `deletionProtection == true` retorna `409 Conflict` (`DeletionProtected`).
- **Verificação de dependentes ativos (decisão 0100):** a API consulta o cache local `UserUsageProjection`. Se houver usuários pertencentes àquela Organization, a exclusão é recusada com `409 Conflict` (`ResourcesAttached`), impedindo a remoção acidental de organizações com membros cadastrados.
