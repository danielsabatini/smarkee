# ipm.permission: fluxo de dados (do `POST` até a role de projeto no Zitadel)

Documento de fluxo de dados da feature `ipm.permission`, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md) e das decisões de arquitetura:
- [0083](../../../../.decisions/0083-ipm-permission-ipm-role-e-fim-da-trava-de-deploy.md): Permission atômica no formato `<módulo>.<tipo>.<ação>`;
- [0096](../../../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md): unificação do loop de reconciliação no Controller;
- [0098](../../../../.decisions/0098-api-sincrona-e-fim-da-operation.md): API síncrona e extinção da Operation;
- [0100](../../../../.decisions/0100-desacoplamento-http-ipm-e-projecoes-desejado.md): desacoplamento total via Stream `DESIRED`.

Todos os passos rodam no dev (Docker Compose) e são verificados pela suíte e2e (`tests/e2e`).

**Comando.** `sk ipm permission create|get|list|update|protect|unprotect|delete` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

A Permission é uma permissão atômica da plataforma reconciliada pelo `ipm-permission-controller` diretamente como uma Project Role no Zitadel (`roles-<módulo>` da organização `core`).

O pedido é admitido de forma síncrona pela API (`ipm-permission-api`), gravando o estado no SSOT (`phase: Pending`). O Publisher (`ipm-permission-publisher`) publica no Stream `DESIRED`, e o Controller (`ipm-permission-controller`) reconcilia a role no Zitadel, promovendo a fase a `Ready` quando confirmada.

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → API | `POST /v1/ipm/permissions` (via gateway) | `{key, displayName, ...}` | nada |
| 2 | API → banco `ssot` | SQL, uma transação atômica | `201 Created` (`Resource` em `phase: Pending`) | `ipm.permission`, `ipm.permission_outbox`, `ipm.permission_idempotency` |
| 3 | Publisher → NATS | JetStream, Stream `DESIRED` | `desired` (`manager.desired.ipm.permission.<id>.changed`) | `ipm.permission_outbox.published_at` |
| 4 | Controller → Zitadel; Controller → SSOT | HTTP no Zitadel (ProjectService); SQL transacional | Chamadas `Add/Update/RemoveProjectRole` | `ipm.permission` (`phase: Ready`, `observedGeneration: 1`) |

Diagramas de arquitetura e estados:
- Componentes: [`architecture/01-componentes.svg`](architecture/01-componentes.svg)
- Modelo de dados (ER): [`database/01-er-fisico.svg`](database/01-er-fisico.svg)
- Fases do recurso: [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg)
- Fluxos: criação [`flow/01-criar-permission.svg`](flow/01-criar-permission.svg), validação [`flow/02-validacao-e-borda.svg`](flow/02-validacao-e-borda.svg), atualização e remoção [`flow/03-atualizar-e-remover.svg`](flow/03-atualizar-e-remover.svg), falhas [`flow/04-falhas-na-api-e-mensageria.svg`](flow/04-falhas-na-api-e-mensageria.svg).

### Identificadores que ligam tudo

| Campo | Quem cria | Formato | Papel |
|---|---|---|---|
| `resourceId` | API | UUIDv7 minúsculo | Identidade primária da Permission no SSOT. |
| `key` | Solicitante (imutável) | `<módulo>.<tipo>.<ação>` | Chave da role no projeto do Zitadel (`roles-<módulo>`). |
| `messageId` | API (na outbox) | UUIDv7 | É o `Nats-Msg-Id` (deduplicação) e a chave única do outbox. |
| `correlationId` | API | UUIDv7 (propagado ou gerado) | Rastreia a requisição de ponta a ponta. |
| `resourceVersion` | API | inteiro serializado como string | Concorrência otimista no `PATCH` e `DELETE`. |
| `Idempotency-Key` | Cliente (opcional) | string até 128 chars | Garante idempotência na admissão da API. |

---

## 1. CLI → API: `POST /v1/ipm/permissions`

A API `ipm-permission-api`:
- Valida o token JWT (audience `roles-ipm`).
- Exige permissão de operador global `ipm.permission.admin`.
- Valida o formato estrito da chave (`^[a-z]+(\.[a-z0-9_-]+){2}$`).
- Insere na tabela `ipm.permission` com `phase: Pending` e `generation: 1`, grava na tabela `ipm.permission_outbox` e responde síncrono `201 Created`.

---

## 2. Publicação Assíncrona: `ipm-permission-publisher`

Drena o outbox pendente em ordem de `sequence` e publica em `manager.desired.ipm.permission.<resourceId>.changed` com `Nats-Msg-Id: <messageId>`.

---

## 3. Reconciliação Unificada: `ipm-permission-controller`

O Controller:
1. Consome os eventos do Stream `DESIRED` e alimenta sua workqueue deduplicada.
2. Identifica o projeto alvo no Zitadel com base no prefixo da chave (`roles-<módulo>` na organização `core`).
3. Consulta o Zitadel via `ProjectService.ListProjectRoles`:
   - Se ausente: chama `AddProjectRole`.
   - Se divergente: chama `UpdateProjectRole`.
   - Se remoção solicitada (`lifecycle = absent`): chama `RemoveProjectRole`.
4. Reobserva a Project Role no Zitadel e atualiza `ipm.permission` no banco `ssot` para `phase: Ready` com `observed_generation = generation`. No caso de remoção concluída, remove a linha do banco.
