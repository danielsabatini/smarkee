# ipm.user: fluxo de dados (do `POST` até o usuário na organização do Zitadel)

Documento de fluxo de dados da feature `ipm.user`, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md) e das decisões de arquitetura:
- [0077](../../../../.decisions/0077-ipm-user-usuarios-da-organizacao.md): usuário humano na organização do cliente;
- [0096](../../../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md): unificação do loop de reconciliação no Controller;
- [0097](../../../../.decisions/0097-desired-puro-e-permissoes-efetivas-no-controller.md): `desired` puro e permissões efetivas calculadas pelo Controller via catálogos de `roles` e `groups`;
- [0098](../../../../.decisions/0098-api-sincrona-e-fim-da-operation.md): API síncrona e extinção da Operation;
- [0100](../../../../.decisions/0100-desacoplamento-http-ipm-e-projecoes-desejado.md): desacoplamento total de chamadas HTTP mútuas entre features via Informers e projeções no Stream `DESIRED`.

Todos os passos rodam no dev (Docker Compose) e são verificados pela suíte e2e (`tests/e2e`).

**Comando.** `sk ipm user create|get|list|update|protect|unprotect|delete` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

O usuário da Organization vive no Zitadel como um usuário humano criado **dentro** da organização do cliente, com o mesmo ID (`resourceId`), e autorizações concedidas no Project Grant de `roles-ipm` daquela organização. Pertence ao perfil **`external-reconciled`**: possui `api`, `publisher` e `controller`.

O pedido é admitido de forma síncrona pela API (`ipm-user-api`), que grava a intenção no SSOT (`phase: Pending`). O Publisher (`ipm-user-publisher`) publica no Stream `DESIRED`, e o Controller (`ipm-user-controller`) provisiona o usuário no Zitadel, concede a membership e o userGrant com as roles calculadas dinamicamente e atualiza a fase para `Ready`.

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → API | `POST /v1/ipm/users` (via gateway) | `{organizationId, email, roles, ...}` | nada |
| 2 | API → banco `ssot` | SQL, uma transação atômica | `201 Created` (`Resource` em `phase: Pending`) | `ipm.user`, `ipm.user_outbox`, `ipm.user_idempotency` |
| 3 | Publisher → NATS | JetStream, Stream `DESIRED` | `desired` (`manager.desired.ipm.user.<id>.changed`) | `ipm.user_outbox.published_at` |
| 4 | Controller → Zitadel; Controller → SSOT | HTTP no Zitadel (UserService / OrgService); SQL transacional | Criação de usuário e userGrant no Project Grant | `ipm.user` (`phase: Ready`, `observedGeneration: 1`) |

Diagramas de arquitetura e estados:
- Componentes: [`architecture/01-componentes.svg`](architecture/01-componentes.svg)
- Modelo de dados (ER): [`database/01-er-fisico.svg`](database/01-er-fisico.svg)
- Fases do recurso: [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg)
- Fluxos: criação [`flow/01-criar-usuario.svg`](flow/01-criar-usuario.svg), validação [`flow/02-validacao-e-borda.svg`](flow/02-validacao-e-borda.svg), atualização e remoção [`flow/03-alterar-roles-e-remover.svg`](flow/03-alterar-roles-e-remover.svg), falhas [`flow/04-falhas-na-api-e-mensageria.svg`](flow/04-falhas-na-api-e-mensageria.svg).

### Identificadores que ligam tudo

| Campo | Quem cria | Formato | Papel |
|---|---|---|---|
| `resourceId` | API | UUIDv7 minúsculo | Identidade primária do User no SSOT e userId no Zitadel. |
| `organizationId` | Solicitante (imutável) | UUIDv7 minúsculo | Identidade da Organization no SSOT e orgId no Zitadel. |
| `email` | Solicitante | string até 254 chars | E-mail corporativo único por organização. |
| `messageId` | API (na outbox) | UUIDv7 | É o `Nats-Msg-Id` (deduplicação) e a chave única do outbox. |
| `correlationId` | API | UUIDv7 (propagado ou gerado) | Rastreia a requisição de ponta a ponta. |
| `resourceVersion` | API | inteiro serializado como string | Concorrência otimista no `PATCH` e `DELETE`. |
| `Idempotency-Key` | Cliente (opcional) | string até 128 chars | Garante idempotência na admissão da API. |

---

## 1. CLI → API: `POST /v1/ipm/users`

A API `ipm-user-api`:
- Valida o token JWT (audience `roles-ipm`).
- Reconhece o escopo:
  - Operador (`ipm.user.admin`): atua em qualquer organização;
  - Root: dono confirmado pelo cache local `OrganizationUsageProjection` (sem chamada HTTP a `ipm.organization`);
  - Usuário da organização: identificado pelo próprio registro no SSOT (`resourceId == sub`) e permissão `ipm.user.create`.
- Valida cota de usuários da Organization e unicidade do e-mail.
- Valida regras de RBAC `bind` contra o catálogo de roles.
- Insere na tabela `ipm.user` com `phase: Pending` e `generation: 1`, grava na outbox e responde síncrono `201 Created`.

---

## 2. Publicação Assíncrona: `ipm-user-publisher`

Drena o outbox pendente em ordem de `sequence` e publica em `manager.desired.ipm.user.<resourceId>.changed`.

---

## 3. Reconciliação Unificada: `ipm-user-controller`

O Controller:
1. Consome os eventos do Stream `DESIRED`.
2. Mantém informers locais dos catálogos de `ipm.permission`, `ipm.role` e `ipm.group`.
3. Calcula as permissões efetivas do usuário somando as roles diretas com as permissões dos grupos aos quais pertence.
4. Observa o Zitadel via `UserService.GetUserByID`:
   - Se ausente: cria o usuário humano na organização do cliente, ativa sua membership e cria o userGrant no Project Grant de `roles-ipm` da organização.
   - Se divergente: atualiza o perfil e o conjunto de roles no userGrant.
   - Se remoção solicitada (`lifecycle = absent`): remove o usuário humano no Zitadel.
5. Reobserva o usuário e atualiza `ipm.user` no banco `ssot` para `phase: Ready` com `observed_generation = generation`. No caso de remoção concluída, remove a linha do SSOT.
