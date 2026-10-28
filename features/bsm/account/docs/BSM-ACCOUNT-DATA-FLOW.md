# bsm.account: fluxo de dados (do `POST` até o estado convergido)

Documento de fluxo de dados da feature `bsm.account`, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md) e das decisões de arquitetura:
- [0098](../../../../.decisions/0098-api-sincrona-e-fim-da-operation.md): API síncrona e extinção da Operation;
- [0099](../../../../.decisions/0099-extincao-do-banco-platform.md): extinção do banco `platform` e concentração no SSOT;
- [0100](../../../../.decisions/0100-desacoplamento-http-ipm-e-projecoes-desejado.md): desacoplamento total de chamadas HTTP mútuas entre features via Informers e projeções em memória no stream `DESIRED`.

Todos os passos rodam no dev (Docker Compose) e são verificados pela suíte e2e (`tests/e2e`).

**Comando.** `sk bsm account create|get|list|update|protect|unprotect|delete` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

A Billing Account existe **exclusivamente no SSOT da Smarkee** (banco `ssot`, schema `bsm`). Por se tratar de um recurso do perfil **`internal-state`**, ele não possui representação direta em provedores externos (como o Zitadel) nem arquivos em disco: nasce imediatamente com `phase: Ready`, `presence: present` e `observedGeneration = generation`.

O pedido é admitido de forma síncrona pela API (`bsm-account-api`) em uma única transação no PostgreSQL. O Publisher (`bsm-account-publisher`) lê o outbox e publica o evento no stream `DESIRED` do NATS JetStream para que as features dependentes (`ipm.organization` e `sum.service`) consumam via projeções locais em memória sem nenhuma chamada HTTP síncrona à API de faturamento.

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → API | `POST /v1/bsm/accounts` (via gateway) | `{displayName, billingCurrency, billingContacts, ...}` | nada |
| 2 | API → banco `ssot` | SQL, uma transação atômica | `201 Created` (`Resource` em `phase: Ready`) | `bsm.account`, `bsm.account_outbox`, `bsm.account_idempotency` |
| 3 | Publisher → NATS | JetStream, Stream `DESIRED` | `desired` (`manager.desired.bsm.account.<id>.changed`) | `bsm.account_outbox.published_at` |
| 4 | NATS → Consumidores | JetStream (Informer/Stream) | `desired` entregue a `ipm.organization` e `sum.service` | Atualização de projeções locais de faturamento |

Apenas a **API** escreve nas tabelas de recurso (`bsm.account`) e outbox (`bsm.account_outbox`). O **Publisher** apenas lê o outbox e marca `published_at`. Não há `Receiver`, `Manager`, `Reconciler`, `Observer`, `Executor`, `Operation` nem arquivos JSON em disco.

Diagramas de arquitetura e estados:
- Componentes: [`architecture/01-componentes.svg`](architecture/01-componentes.svg)
- Modelo de dados (ER): [`database/01-er-fisico.svg`](database/01-er-fisico.svg)
- Fases do recurso: [`state/01-fase-do-recurso.svg`](state/01-fase-do-recurso.svg)
- Fluxos de execução: criação [`flow/01-criar-account.svg`](flow/01-criar-account.svg), validação e borda [`flow/02-validacao-e-borda.svg`](flow/02-validacao-e-borda.svg), atualização e remoção [`flow/03-atualizar-e-remover.svg`](flow/03-atualizar-e-remover.svg), falhas e resiliência [`flow/04-falhas-na-api-e-mensageria.svg`](flow/04-falhas-na-api-e-mensageria.svg).

### Identificadores que ligam tudo

| Campo | Quem cria | Formato | Papel |
|---|---|---|---|
| `resourceId` | API | UUIDv7 minúsculo | Identidade primária da Billing Account no SSOT. |
| `ownerAccountId` | Token JWT (`sub`) | UUIDv7 minúsculo | Usuário dono da conta de faturamento. |
| `displayName` | Solicitante | string até 64 chars | Nome descritivo da conta (único por dono entre ativas). |
| `billingCurrency` | Solicitante (imutável) | `BRL`, `USD` ou `EUR` | Moeda de cobrança da conta de faturamento. |
| `messageId` | API (na outbox) | UUIDv7 | É o `Nats-Msg-Id` (deduplicação) e a chave única do outbox. |
| `correlationId` | API | UUIDv7 (propagado ou gerado) | Rastreia a requisição de ponta a ponta. |
| `resourceVersion` | API | inteiro serializado como string | Concorrência otimista no `PATCH` e `DELETE`. |
| `Idempotency-Key` | Cliente (opcional) | string até 128 chars | Garante idempotência na admissão da API. |

---

## 1. CLI → API: `POST /v1/bsm/accounts`

Exemplo de chamada via CLI:
```bash
sk bsm account create \
  --name "Faturamento Principal" \
  --currency BRL \
  --contacts "financeiro@exemplo.com.br,contas@exemplo.com.br"
```

A requisição chega ao gateway APISIX e é roteada para a API `bsm-account-api` na rota `POST /v1/bsm/accounts`.

### 1.1 Autenticação e Autorização na API
1. **Autenticação:** validação do token JWT OIDC emitido pelo Zitadel (audience `roles-bsm`).
2. **Autorização:** exige a role `bsm.account.create` (ou `bsm.account.admin`) e e-mail do solicitante verificado (`email_verified: true`). O dono da conta (`ownerAccountId`) é extraído estritamente do `sub` do token JWT.

### 1.2 Validações de Domínio e Admissão Síncrona
A API valida em memória antes de tocar no banco:
- Moeda de cobrança (`billingCurrency`): deve ser uma das moedas aceitas (`BRL`, `USD`, `EUR`). É estritamente imutável após a criação.
- Contatos de cobrança (`billingContacts`): lista com 1 a 10 e-mails válidos e únicos.
- Cota de Billing Accounts ativas por dono: máximo de 5 contas ativas por dono (o operador com `bsm.account.admin` não possui limite de cota). Se excedida, retorna `409 Conflict` (`QuotaExceeded`).
- Suporte a `Idempotency-Key`: repetição exata devolve `201 Created` do recurso já salvo; divergência de payload devolve `422 IdempotencyConflict`.

### 1.3 Gravação Atômica no SSOT
A admissão executa uma única transação SQL no banco `ssot`:
1. Trava consultiva por `(owner_account_id, display_name)` para evitar colisão concorrente de nomes para o mesmo dono.
2. `INSERT` na tabela `bsm.account`:
   - `phase = 'Ready'`
   - `presence = 'present'`
   - `desired_generation = 1`
   - `observed_generation = 1`
   - `desired = observed = {"displayName": ..., "billingCurrency": ..., "billingContacts": [...], "deletionProtection": true}`
   - `requested_by = <sub do solicitante>`
   - `correlation_id = <correlationId>`
3. `INSERT` na tabela `bsm.account_outbox`:
   - evento `desired.changed` contendo o envelope estrito da conta de faturamento.
4. `INSERT` na tabela `bsm.account_idempotency` (se `Idempotency-Key` foi enviada).

A API responde imediatamente `201 Created` contendo o `Resource` completo já convergido.

---

## 2. Publicação Assíncrona: `bsm-account-publisher`

O processo `bsm-account-publisher` roda de forma contínua e assíncrona:
1. Drena as linhas de `bsm.account_outbox` onde `published_at IS NULL` ordenadas por `sequence ASC`.
2. Constrói a mensagem NATS com cabeçalho `Nats-Msg-Id = message_id`.
3. Publica no subject `manager.desired.bsm.account.<resourceId>.changed` no JetStream (Stream `DESIRED`).
4. Ao receber o `PubAck` do JetStream, atualiza `UPDATE bsm.account_outbox SET published_at = now() WHERE sequence = ...`.

Envelope publicado:
```json
{
  "messageId": "0199c8b3-0a1b-7c2d-8e3f-4a5b6c7d8e88",
  "schemaVersion": "1.0",
  "messageType": "desired",
  "emitter": "publisher",
  "module": "bsm",
  "resourceType": "account",
  "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d88",
  "operation": "changed",
  "desiredGeneration": 1,
  "publishedAt": "2026-10-28T14:00:00.000Z",
  "publishedBy": "bsm-account-publisher",
  "data": {
    "ownerAccountId": "0199c8a4-0000-7000-8000-00000000beef",
    "displayName": "Faturamento Principal",
    "billingCurrency": "BRL",
    "billingContacts": ["financeiro@exemplo.com.br", "contas@exemplo.com.br"],
    "deletionProtection": true,
    "lifecycle": "present",
    "reconciliation": "active"
  }
}
```

---

## 3. Consumo por Projeções Locais em Outras Features

As mensagens publicadas no Stream `DESIRED` alimentam projeções em memória de outras features (decisão 0100):
1. **`ipm.organization` (API):** consome `BillingAccountProjection` para validar se uma Organization referencia uma Billing Account existente e pertencente ao mesmo dono no momento de sua criação ou atualização, sem nenhuma chamada HTTP a `bsm.account`.
2. **`sum.service` (API):** consome projeção de Billing Account para garantir que o usuário dono possui conta de faturamento ativa antes de permitir a ativação de serviços cobráveis.
3. **`bsm.account` (API):** consome `OrganizationUsageProjection` (Informer de `ipm.organization`) para saber se há organizações ativas vinculadas à conta de faturamento.

---

## 4. Atualização e Exclusão

### 4.1 Atualização (`PATCH /v1/bsm/accounts/{resourceId}`)
- Exige `bsm.account.update` ou `bsm.account.admin` e pertinência ao dono.
- Tentativa de alterar `billingCurrency` é recusada com `400 ValidationFailed` (campo imutável).
- Concorrência otimista via cabeçalho `If-Match` ou campo `resourceVersion`.
- Na transação da API:
  - `desired_generation` é incrementado;
  - `observed_generation` acompanha o novo valor;
  - `resource_version` é incrementado;
  - novo evento `desired.changed` é inserido no outbox.
- Resposta síncrona `200 OK` com o recurso atualizado.

### 4.2 Exclusão (`DELETE /v1/bsm/accounts/{resourceId}`)
- Exige `bsm.account.delete` ou `bsm.account.admin` e pertinência ao dono.
- Se `deletionProtection` estiver ativa (`true`), recusa com `409 Conflict` (`DeletionProtected`).
- **Verificação de dependentes ativos (Ajuste 1 e decisão 0100):** a API consulta o cache local `OrganizationUsageProjection`. Se houver organizações vinculadas à conta de faturamento, a exclusão é recusada sincronamente com `409 Conflict` (`ResourcesAttached`), informando a quantidade de organizações dependentes.
- Quando elegível:
  - Remove a linha física em `bsm.account`.
  - Insere evento tombstone (`lifecycle: absent`) no `bsm.account_outbox`.
- Resposta síncrona `202 Accepted` (ou `204 No Content`). O Publisher propaga o tombstone e as demais features limpam as referências em cache.

---

## 5. Mapa de Acesso ao Banco de Dados

Todas as operações ocorrem exclusivamente no banco `ssot` sob o schema `bsm`:

| Tabela / Objeto | Papel `bsm_account_api` | Papel `bsm_account_publisher` |
|---|---|---|
| `bsm.account` | `SELECT`, `INSERT`, `UPDATE`, `DELETE` | Nenhum acesso |
| `bsm.account_v1` (view) | `SELECT` | Nenhum acesso |
| `bsm.account_outbox` | `INSERT` | `SELECT`, `UPDATE (published_at)` |
| `bsm.account_idempotency` | `SELECT`, `INSERT` | Nenhum acesso |

O banco `platform` e o volume local de arquivos em disco foram completamente extintos.
