# sum.service: fluxo de dados (da ligação até as roles no Zitadel)

Este documento segue o padrão de `features/core/user/docs/CORE-USER-DATA-FLOW.md`. Cada passo diz se está
**implementado e testado** ou se é **planejado** (a regra e o contrato já existem, mas o processo não).
A decisão de desenho é a 0033 (`.decisions/0033-service-usage-manager.md`).

## 0. Visão geral

Ligar um serviço (`POST /v1/sum/services {"service": "ipm"}`) não concede roles diretamente. O pedido vira
uma mensagem `requested`, o Manager decide e grava, o Publisher publica o `desired`, o Reconciler compara com
o `observed` e manda uma `action`, o Executor concede no Zitadel, e o Observer lê de volta.

| Passo | Quem | Estado |
|---|---|---|
| 1 | Receiver: recebe o pedido e publica `requested` | Implementado; verificado no dev com processo no host |
| 2 | Manager: consome `requested`, decide, grava ligação, Operation e outbox | Implementado e testado |
| 3 | Publisher: publica o `desired` do outbox | Implementado e testado |
| 4 | Reconciler: decide e publica `action` | Implementado; verificado no dev com processo no host |
| 5 | Executor: concede as roles no Zitadel e publica `completed` ou `failed` | Implementado; verificado no dev com processo no host |
| 6 | Observer: lê o Zitadel e publica `observed` | Implementado; verificado no dev com processo no host |

Diagrama do caminho de ligar: [`flow/01-ligar-servico.svg`](flow/01-ligar-servico.svg). Componentes: [`architecture/01-componentes.svg`](architecture/01-componentes.svg).

### Identificadores

- `resourceId`: UUIDv7 atribuído pelo Receiver (o Manager não o gera). Recusas gravam o mesmo id.
- `operationId`, `requestDigest`: vêm do Receiver; a repetição de um `operationId` não grava de novo.
- `ownerUserId`: o `resourceId` do usuário dono (o `sub` do token). Vem do token, nunca do corpo.
- `actionId` = `<resourceId>.<desiredGeneration>.<operação>.<messageId do observed>`: chave de dedupe da `action`.

## 1. Receiver → NATS: `requested` (implementado)

O corpo do `POST` é `{"service": "<nome>"}` (`schemas/sum/service/api-create-request`). O Receiver valida o token
(audience `roles-sum`), confere a role `sum.<serviço>.enable`, atribui `resourceId` e `operationId`, calcula o
`requestDigest` e publica `requested-create` em `receiver.requested.sum.service.<resourceId>.create`, com
`Nats-Msg-Id` igual ao `operationId`. O `ownerUserId` vem do `sub` do token. O desligamento é `DELETE`, que confere
a `resourceVersion` e publica `requested-delete` (`.delete`). Detalhes da API: `receiver/README.md`.

## 2. Manager consome `requested` e grava (implementado)

O consumer `sum-service-manager-requested` (pull, durável, ACK explícito) entrega a mensagem a
`transport/requested.py`:

1. valida o envelope e os dados (`MessageEnvelope` tolerante, `ServiceRequestedCreateData` ou
   `ServiceRequestedDeleteData`). Desvio do contrato é `TERM`;
2. abre a transação, com o pool em autocommit (`transaction()` explícito);
3. chama `RequestedHandler.create` ou `.delete`;
4. ACK depois do `COMMIT`. Falha transitória do banco é `RETRY` com atraso.

### 2.1 Decisão (domínio puro, `domain/decision.py`)

| Pedido | Condição | Resultado |
|---|---|---|
| criar | serviço fora do catálogo | recusa `service_unavailable` |
| criar | par dono + serviço já com ligação ativa | recusa `already_exists`, com o `resourceId` existente |
| criar | senão | aceita: `desired` com `present` e as roles do catálogo, copiadas agora |
| desligar | sem ligação ativa | recusa `not_found` |
| desligar | `resourceVersion` diferente da atual | recusa `conflict` |
| desligar | senão | aceita: `desired` com `absent` e `serviceRoles = []` |

### 2.2 Gravação (`store/ssot.py`, `handlers/requested.py`)

- **Criar aceito:** `INSERT` em `sum.service` (geração 1, versão 1, fase `Pending`), dentro de um savepoint. O
  índice único parcial `service_active_link` impede duas ligações ativas para o mesmo par, mesmo com pedidos
  concorrentes: se a violação acontecer, a recusa é `already_exists`.
- **Desligar aceito:** `UPDATE` da mesma linha: `lifecycle = absent`, geração + 1, versão + 1. A linha não é
  apagada: quem desliga mantém o histórico, e uma nova ligação cria outra linha.
- **Operation:** `INSERT` em `sum.service_operation` com `accepted` (com `desired_generation`) ou `rejected`
  (com o motivo, sem geração).
- **Outbox:** só nas aceitas, `INSERT` em `sum.service_outbox` com a mensagem `desired` (envelope sem
  `publishedAt` e `publishedBy`, que o Publisher preenche).

### 2.3 Repetição

Reentrega com o mesmo `operationId` não grava nada: `Duplicate`, e o ACK acontece. Pedidos concorrentes para
o mesmo par são resolvidos pelo índice único.

## 3. Outbox → NATS (implementado)

O Publisher (`sum-service-publisher`) lê as linhas pendentes em ordem de `sequence`, em lotes de 100, e para
cada uma:

1. valida o envelope completo de forma estrita e acrescenta `publishedAt` e `publishedBy: sum-service-publisher`;
2. publica em `manager.desired.sum.service.<resourceId>.changed`, com `Nats-Msg-Id` igual ao `messageId`;
3. marca `published_at` **depois** da confirmação do transporte.

Só uma instância publica por vez (trava consultiva de sessão). Envelope inválido ou recusa permanente do
transporte param o lote e o processo sai com código 1; a mensagem continua pendente. Erro transitório tem
recuo exponencial.

## 4. Reconciler (implementado)

O `desired` (stream `DESIRED`) e o `observed` (stream `OBSERVED`) chegam ao motor, junto com os resultados
(`RESULT`). Antes de decidir, a decisão confere as guardas do loop: sem os dois estados, `desired` suspenso,
`observed` `unknown` ou vencido, observação causada por um resultado ainda não chegada, ação pendente da
mesma geração, e backoff após falha.

- **Ligação ativa** com roles faltando → `update` (`Drift`).
- **Ligação desligada** com alguma role do serviço presente → `update` (`RolesRemovalRequested`).

A `action` vai para `reconciler.action.sum.service.<resourceId>.update`, com `Nats-Msg-Id` igual ao `actionId`.

## 5. Executor (implementado)

O Executor consome a partição do `ACTION` (um consumer por partição, `max_ack_pending = 1`).

- **Ligar:** garante as roles pedidas, no projeto `roles-ipm`. Cria a autorização se não existe; senão, acrescenta
  só as que faltam. Repetir não muda nada.
- **Desligar:** tira só as roles do serviço, mantém as demais, e remove a autorização quando não sobra nenhuma.

Toda concessão passa pela conta `sum-service-executor`, que tem `PROJECT_GRANT_OWNER` só no Grant de
`roles-ipm` (decisão 0032). O Zitadel recusa qualquer outra role. Isso foi verificado no dev com o provider
real: `core.user.get` em `roles-core` e `ipm.organization.admin` em `roles-ipm` foram recusados.

## 6. Observer (implementado)

Lê o Zitadel só de leitura (conta `sum-service-observer`): se o usuário existe e as autorizações nos
projetos de roles. Produz:

- `present`, com `serviceRoles` = as roles do catálogo que o usuário tem;
- `absent`, só quando o Zitadel confirma que o usuário não existe (404 com detalhe);
- `unknown`, para qualquer falha de leitura. Erro de leitura nunca vira `absent`.

A mensagem `observed` sai em `observer.observed.sum.service.<resourceId>.changed`, com `causationId` quando é
a resposta a um resultado.

## 7. Estados

- Fase do recurso (`phase`): `Pending` ao gravar. `Ready` quando o `observed` converge ainda não é aplicado
  ao SSOT: o Manager ainda não consome `observed` nem resultados (pendência).
- Operation: `accepted` (vai ao Executor) ou `rejected` (com motivo, sem geração).

## 8. Mapa: quem grava o quê

| Tabela, stream ou serviço | Escritor | Leitor |
|---|---|---|
| `sum.service` | Manager | Receiver (view `sum.service_v1`) |
| `sum.service_operation` | Manager | Receiver (view `sum.service_operation_v1`) |
| `sum.service_outbox` | Manager (insere) | Publisher (lê, e marca `published_at`) |
| `REQUESTED` | Receiver | Manager |
| `DESIRED` | Publisher | Reconciler, Observer |
| `OBSERVED` | Observer | Reconciler |
| `ACTION` | Reconciler | Executor |
| `RESULT` | Executor | Reconciler, Observer |
| Zitadel (autorizações em `roles-ipm`) | Executor | Observer (leitura) |

## 9. Verificação de ponta a ponta (2026-10-15, dev)

Com os processos no host e os consumers do broker de dev, ligar `ipm` para um usuário de teste gerou, nesta ordem:
Operation `accepted` e `desired` no outbox; `desired` publicado; `observed` sem roles; `action` `update`; autorização criada no
`roles-ipm` (conferida no Zitadel); `completed` no `RESULT`. Desligar gerou geração 2: `action`, revogação (o Zitadel ficou
sem autorização) e `completed`. Os recursos de teste foram removidos ao final.
