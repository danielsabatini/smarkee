# ipm.serviceaccount: fluxo de dados (do `POST` até a máquina no Zitadel)

Documento de fluxo de dados da feature `ipm.serviceaccount`, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md) e das decisões de arquitetura:
- [0094](../../../../.decisions/0094-ipm-serviceaccount-identidade-de-maquina-da-organization.md): identidade de máquina da Organization com chave privada que fica no cliente e pública no Zitadel;
- [0096](../../../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md): unificação do loop de reconciliação no Controller;
- [0097](../../../../.decisions/0097-desired-puro-e-permissoes-efetivas-no-controller.md): `desired` puro e permissões efetivas calculadas pelo Controller via catálogos de `roles` e `groups`;
- [0098](../../../../.decisions/0098-api-sincrona-e-fim-da-operation.md): API síncrona e extinção da Operation;
- [0100](../../../../.decisions/0100-desacoplamento-http-ipm-e-projecoes-desejado.md): desacoplamento total de chamadas HTTP mútuas entre features via Informers e projeções no Stream `DESIRED`.

Todos os passos rodam no dev (Docker Compose) e são verificados pela suíte e2e (`tests/e2e`).

**Comando.** `sk ipm serviceaccount create|get|list|update|protect|unprotect|delete` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

A Service Account é a identidade de máquina da Organization. Pertence ao perfil **`external-reconciled`**: possui `api`, `publisher` e `controller`.

O pedido é admitido de forma síncrona pela API (`ipm-serviceaccount-api`), que valida as chaves públicas (RSA >= 2048 bits), calcula fingerprints SHA-256 e grava a intenção no SSOT (`phase: Pending`). O Publisher (`ipm-serviceaccount-publisher`) publica no Stream `DESIRED`, e o Controller (`ipm-serviceaccount-controller`) provisiona o Machine User no Zitadel, injeta as chaves públicas via API v2 de usuários, adiciona o membership e userGrant no Project Grant e atualiza a fase para `Ready`.

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → API | `POST /v1/ipm/serviceaccounts` (via gateway) | `{organizationId, name, keys, roles, ...}` | nada |
| 2 | API → banco `ssot` | SQL, uma transação atômica | `201 Created` (`Resource` em `phase: Pending`) | `ipm.serviceaccount`, `ipm.serviceaccount_outbox`, `ipm.serviceaccount_idempotency` |
| 3 | Publisher → NATS | JetStream, Stream `DESIRED` | `desired` (`desired.ipm.serviceaccount.<id>`) | `ipm.serviceaccount_outbox.published_at` |
| 4 | Controller → Zitadel; Controller → SSOT | HTTP no Zitadel (UserService / OrgService); SQL transacional | Criação de Machine User, chaves e userGrant | `ipm.serviceaccount` (`phase: Ready`, `observedGeneration: 1`) |

Diagramas de arquitetura e estados:
- Componentes: [`architecture/01-componentes.svg`](architecture/01-componentes.svg)
- Modelo de dados (ER): [`database/01-er-fisico.svg`](database/01-er-fisico.svg)
- Fases do recurso: [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg)
- Fluxos: criação [`flow/01-criar-serviceaccount.svg`](flow/01-criar-serviceaccount.svg), validação [`flow/02-validacao-e-borda.svg`](flow/02-validacao-e-borda.svg), rotação e remoção [`flow/03-rotacao-chaves-e-remover.svg`](flow/03-rotacao-chaves-e-remover.svg), falhas [`flow/04-falhas-na-api-e-mensageria.svg`](flow/04-falhas-na-api-e-mensageria.svg).

### Identificadores que ligam tudo

| Campo | Quem cria | Formato | Papel |
|---|---|---|---|
| `resourceId` | API | UUIDv7 minúsculo | Identidade primária da ServiceAccount no SSOT e userId no Zitadel. |
| `organizationId` | Solicitante (imutável) | UUIDv7 minúsculo | Identidade da Organization no SSOT e orgId no Zitadel. |
| `name` | Solicitante | string até 64 chars | Nome único da service account na organização. |
| `fingerprint` | API | string SHA-256 (hex) | Hash identificador de cada chave pública cadastrada. |
| `messageId` | API (na outbox) | UUIDv7 | É o `Nats-Msg-Id` (deduplicação) e a chave única do outbox. |
| `correlationId` | API | UUIDv7 (propagado ou gerado) | Rastreia a requisição de ponta a ponta. |
| `resourceVersion` | API | inteiro serializado como string | Concorrência otimista no `PATCH` e `DELETE`. |
| `Idempotency-Key` | Cliente (opcional) | string até 128 chars | Garante idempotência na admissão da API. |

---

## 1. CLI → API: `POST /v1/ipm/serviceaccounts`

A API `ipm-serviceaccount-api`:
- Valida o token JWT (audience `roles-ipm`).
- Reconhece o escopo sem chamadas HTTP mútuas (decisão 0100):
  - Operador (`ipm.serviceaccount.admin`): atua em qualquer organização;
  - Root: dono confirmado pelo cache local `OrganizationUsageProjection`;
  - Usuário da organização: membro confirmado pelo cache local `MemberProjection`.
- Valida o material de chave: exige chave pública PEM RSA >= 2048 bits com validade futura de até 365 dias. Rejeita terminantemente chave privada (`400`).
- Insere na tabela `ipm.serviceaccount` com `phase: Pending` e `generation: 1`, grava na outbox e responde síncrono `201 Created`.

---

## 2. Publicação Assíncrona: `ipm-serviceaccount-publisher`

Drena o outbox pendente em ordem de `sequence` e publica em `desired.ipm.serviceaccount.<resourceId>`.

---

## 3. Reconciliação Unificada: `ipm-serviceaccount-controller`

O Controller:
1. Consome os eventos do Stream `DESIRED`.
2. Mantém informers locais dos catálogos de `ipm.permission`, `ipm.role` e `ipm.group` para calcular permissões dinamicamente.
3. Observa o Zitadel via `UserService.GetUserByID`:
   - Se ausente: cria o usuário de máquina com `ACCESS_TOKEN_TYPE_JWT`, injeta as chaves públicas via `AddMachineKey` e adiciona o userGrant no Project Grant da organização.
   - Se divergente: adiciona novas chaves públicas, remove as descartadas e sincroniza roles no userGrant.
   - Se remoção solicitada (`lifecycle = absent`): remove o usuário de máquina no Zitadel.
4. Reobserva a máquina e atualiza `ipm.serviceaccount` no banco `ssot` para `phase: Ready` com `observed_generation = generation`. No caso de remoção concluída, apaga a linha física no SSOT.
