# bsm.account: fluxo de dados (do `POST` até o estado reconciliado)

Documento de fluxo de dados da feature `bsm.account`, no padrão da [decisão 0024](../../../../.decisions/0024-data-flow-por-feature.md).

**Comando.** `sk bsm account create|get|list|update|protect|unprotect|delete` (`clients/cli`) é o cliente deste fluxo.

## 0. Visão geral

Criar uma Billing Account (`POST /v1/bsm/accounts`) não grava nada diretamente no SSOT nem no alvo. O pedido vira uma mensagem `requested`, o Manager decide e grava no SSOT, o Publisher publica o `desired`, o Reconciler compara com o `observed` e manda uma `action`, o Executor grava atomicamente o estado local em disco, e o Observer lê de volta.

| # | De → Para | Meio | O que sai | O que é gravado |
|---|---|---|---|---|
| 1 | CLI → Receiver | `POST /v1/bsm/accounts` (via gateway) | `{displayName, billingCurrency, billingContacts}` | nada |
| 2 | Receiver → Manager | NATS, Stream `REQUESTED` | `requested` / `create` | nada |
| 3 | Manager → banco | SQL, uma transação | (nada publicado) | `bsm.account`, `bsm.account_operation`, `bsm.account_outbox` |
| 4 | Publisher → consumidores | NATS, Stream `DESIRED` | `desired` | `bsm.account_outbox.published_at` |
| 5 | Observer → Manager/Reconciler | NATS, Stream `OBSERVED` | `observed` (`absent`) | `bsm.account` (observação), `bsm.account_operation` |
| 6 | Reconciler → Executor | NATS, Stream `ACTION` | `action` / `create` | nada |
| 7 | Executor → disco; Executor → Manager | I/O atômico em `<stateDir>/<resourceId>.json`; NATS, Stream `RESULT` | `completed` | `bsm.account_action_result`, `bsm.account` |
| 8 | Observer → Manager | NATS, Stream `OBSERVED` | `observed` (`present`) | `bsm.account` → `Ready`, `bsm.account_operation` → `completed` |
| 9 | Manager → consumidores | outbox + Publisher, Stream `UPDATED` | `updated` (a cada mudança de fase) | `bsm.account_outbox` |

Só o **Manager** escreve no SSOT de `bsm.account`.

## 1. CLI → Receiver: `POST /v1/bsm/accounts`

O corpo contém `displayName`, `billingCurrency` (`BRL`, `USD` ou `EUR`), `billingContacts` (1 a 10 e-mails únicos) e, opcionalmente, `deletionProtection` (`true` por padrão). O Receiver valida o token (audience `roles-bsm`), exige a role `bsm.account.create`, o **e-mail verificado** e a cota de Billing Accounts por dono (`BSM_ACCOUNT_RECEIVER_API_ACCOUNT_QUOTA`, padrão 5; o operador, com `bsm.account.admin`, não tem cota), atribui o `resourceId` e publica `requested` em `receiver.requested.bsm.account.<resourceId>.create`, com `Nats-Msg-Id` igual ao `operationId`.

## 2. Manager consome `requested` e grava

O consumer durável `bsm-account-manager-requested` entrega a mensagem ao handler:

1. valida o envelope e os dados;
2. aplica tudo numa transação, com a linha bloqueada e travas consultivas composta por `(ownerAccountId, displayName)` e por dono;
3. ACK depois do `COMMIT`.

| Pedido | Condição | Resultado |
|---|---|---|
| criar ou atualizar | `displayName` já usado por outra Billing Account ativa (`lifecycle = 'present'`) do mesmo `ownerAccountId` | recusa `validation` |
| criar | cota do dono esgotada | recusa `validation` |
| atualizar ou remover | Billing Account inexistente ou já removida | recusa `not_found` |
| atualizar ou remover | `resourceVersion` diferente da atual | recusa `conflict` |
| remover | `deletionProtection` diferente de `false` | recusa `protected` (decisão 0043) |
| qualquer | senão | aceita: `desired` com a nova geração (`lifecycle absent` ao remover) |

## 3. Outbox → NATS

O Publisher (`bsm-account-publisher`) lê as linhas pendentes em ordem de `sequence`, valida o envelope de forma estrita, acrescenta `publishedAt` e `publishedBy` e publica em `manager.desired.bsm.account.<resourceId>.changed`, marcando `published_at` depois da confirmação do transporte.

## 4. Observer (`bsm-account-observer`)

Lê `<stateDir>/<resourceId>.json` em modo somente leitura e produz:

- `present`, com `displayName`, `billingCurrency`, `billingContacts` e `deletionProtection`;
- `absent`, quando o arquivo não existe;
- `unknown`, para qualquer falha de leitura ou JSON fora do contrato.

## 5. Reconciler (`bsm-account-reconciler`)

Reconstrói o estado da mensageria (`DeliverLastPerSubject`) e compara `lifecycle`, `displayName`, `billingCurrency`, `billingContacts` e `deletionProtection`:

- `observed` ausente com `lifecycle present` → `create` (`Missing`);
- qualquer campo gerenciado diferente do `desired` → `update` (`Drift`);
- `lifecycle absent` com a Billing Account presente → `delete` (`DeletionRequested`).

## 6. Executor (`bsm-account-executor`)

Valida e revalida cada `action` contra o `desired` vigente e aplica no diretório local:

- **`create` / `update`:** grava `<stateDir>/<resourceId>.json` atomicamente via arquivo temporário no mesmo diretório e `os.replace`.
- **`delete`:** remove `<stateDir>/<resourceId>.json` (idempotente se já ausente).

## 7. Manager aplica `observed` e resultados

Quando `observed` traz `presence = present`, os campos gerenciados batem com `desired` e `observedGeneration` confirma a geração atual (decisão 0072), a Billing Account vai para `Ready` e as Operations pendentes até essa geração vão para `completed`. Na remoção convergida (`absent`), a linha de `bsm.account` é apagada e `updated` sai com `operation = removed`.
