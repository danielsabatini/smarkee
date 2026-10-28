# bsm.account

A **Billing Account** é a unidade de cobrança do módulo `bsm` (*Billing Service Manager*): um recurso criado por um usuário registrado (a Account, do módulo `core`), que passa a ser o dono dela (`ownerAccountId`). Guarda nome de exibição (`displayName`), moeda de cobrança imutável após a criação (`billingCurrency`: `BRL`, `USD` ou `EUR`), lista de contatos financeiros (`billingContacts`: 1 a 10 e-mails únicos) e proteção contra exclusão (`deletionProtection`, `true` por padrão, decisões `0043` e `0074`). Um mesmo dono pode possuir várias Billing Accounts, desde que não existam duas ativas (`lifecycle = 'present'`) com o mesmo `displayName`.

É um recurso do perfil **`internal-state`** (`docs/loop/RESOURCE-CONTROL-LOOP.md` e decisões `0098` e `0100`): vive exclusivamente no SSOT da plataforma (banco `ssot`, schema `bsm`), nasce imediatamente com `phase: Ready`, `observedGeneration = generation`, e não requer provedor externo nem arquivos em disco.

# 1. Estado da implementação

Dois papéis implementados para execução no ambiente de dev (Docker Compose), sobre a **API síncrona** (decisão `0098`):

| Papel | Projeto | Estado |
|---|---|---|
| API | `api/` (`bsm-account-api`) | API `/v1/bsm/accounts`: `POST` 201, `PATCH` 200 e `DELETE` 202, todos com o `Resource`; sem Operation. Autentica (Zitadel), confere permissões (`bsm.account.*`), e-mail verificado e cota de 5 contas ativas por dono (sem cota para operador `bsm.account.admin`). Valida moeda imutável e bloqueia exclusão com `409 ResourcesAttached` se houver organizações vinculadas (projeção em memória de `ipm.organization`). Grava atomicamente no SSOT e no outbox numa única transação. Contrato em `openapi.json` |
| Publisher | `publisher/` (`bsm-account-publisher`) | Drena o outbox pendente em ordem de `sequence` e publica no JetStream (`desired.bsm.account.>`), com trava de sessão, envelope estrito e `Nats-Msg-Id` determinístico |

A migração inicial e estrutural roda com `bsm-account-migrate` e sai.

# 2. Papéis e componentes

Os papéis são **um projeto e uma imagem** (decisão 0063), cada um rodando como processo e contêiner próprios com privilégios mínimos no banco `ssot`:

| Componente | Serviço no Compose | Papel de banco | Escreve |
|---|---|---|---|
| API | `bsm-account-api` | `bsm_account_api` | SSOT (`bsm.account`, `bsm.account_outbox`, `bsm.account_idempotency`) |
| Publisher | `bsm-account-publisher` | `bsm_account_publisher` | `published_at` em `bsm.account_outbox`; NATS (Stream `DESIRED`) |

## 2.1 API (`bsm-account-api`)
- Rotas sob `/v1/bsm/accounts`: `POST` cria, `GET` lista, `GET /{resourceId}` lê, `PATCH /{resourceId}` altera e `DELETE /{resourceId}?resourceVersion=` remove.
- Valida o token JWT (audiência `roles-bsm`). O dono é o `sub`: nunca vem do corpo. Cada ação exige a permissão `bsm.account.<create|get|list|update|delete>`.
- O dono altera `displayName`, `billingContacts` e `deletionProtection`; `billingCurrency` é estritamente imutável.
- `DELETE` de conta protegida responde `409 DeletionProtected`.
- `DELETE` de conta em uso por Organizations ativas responde `409 ResourcesAttached` (verificado via `OrganizationUsageProjection`, sem chamadas HTTP entre features, decisão 0100).
- `Idempotency-Key` garante repetição segura na admissão síncrona.

## 2.2 Publisher (`bsm-account-publisher`)
- Lê o outbox em ordem de `sequence`, valida o envelope de forma estrita, acrescenta `publishedAt` e `publishedBy` e publica em `desired.bsm.account.<resourceId>`.
- Marca `published_at` após a confirmação (`PubAck`) do JetStream.

# 3. Mensageria

Apenas o Stream `DESIRED` é utilizado:

| Stream | Subject | Publicador | Consumidores |
|---|---|---|---|
| `DESIRED` | `desired.bsm.account.>` | `bsm-account-publisher` | `ipm.organization` (API), `sum.service` (API) |

Não há Streams `REQUESTED`, `OBSERVED`, `ACTION` nem `RESULT` (decisões 0096 e 0098).

# 4. Contratos

Os contratos estão em `schemas/bsm/account/` (e `schemas/common/`), com o índice `schemas/bsm.account.index.json`: `desired`, `api-create-request`, `api-update-request`, `resource` e `resource-list`. A API HTTP é descrita em [`openapi.json`](openapi.json), gerado a partir do código e conferido por teste.

# 5. Configuração, execução e testes

Variáveis `BSM_ACCOUNT_<PAPEL>_<SEÇÃO>_<CAMPO>`, com `config.toml` por papel e senhas em `/run/secrets`. Todos os parâmetros de cada papel estão em [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md). O fluxo de dados completo e os diagramas de arquitetura, banco e estados estão em [`docs/BSM-ACCOUNT-DATA-FLOW.md`](docs/BSM-ACCOUNT-DATA-FLOW.md).

```bash
# 1. Plataforma (banco, messaging, identidade, gateway): infrastructure/dev, no ar e saudável
# 2. Os componentes da Billing Account
docker compose up -d --build
# 3. Testes do projeto
uv sync && uv run ruff check . && uv run pyright && uv run pytest   # na raiz da feature
```
