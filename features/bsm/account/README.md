# bsm.account

A **Billing Account** é a unidade de cobrança do módulo `bsm` (*Billing Service Manager*): um recurso criado por um usuário registrado (a Account, do módulo `core`), que passa a ser o dono dela (`ownerAccountId`). É gerenciada pelo Resource Control Loop (`docs/RESOURCE-CONTROL-LOOP.md`) e guarda nome de exibição (`displayName`), moeda de cobrança imutável após a criação (`billingCurrency`: `BRL`, `USD` ou `EUR`), lista de contatos financeiros (`billingContacts`: 1 a 10 e-mails únicos) e proteção contra exclusão (`deletionProtection`, `true` por padrão, decisões `0043` e `0074`). Um mesmo dono pode possuir várias Billing Accounts, desde que não existam duas ativas (`lifecycle = 'present'`) com o mesmo `displayName`.

Na fase P0, o alvo do Executor e do Observer é um diretório local de estado em disco (um arquivo JSON por `resourceId`, compartilhado entre Executor em leitura/escrita e Observer em somente leitura). A feature `features/ipm/organization` é o **modelo** desta estrutura.

# 1. Estado da implementação

Os seis componentes do loop e a CLI estão implementados para execução no ambiente de dev (Compose).

| Papel | Projeto | Estado |
|---|---|---|
| Receiver | `receiver/` (`bsm-account-receiver`) | API `/v1/bsm/accounts`: autentica, confere a role, o e-mail verificado e a cota, publica `requested`. Contrato em `openapi.json` |
| Manager | `manager/` (`bsm-account-manager`) | Consome `requested`, `observed` e `completed`/`failed`; unicidade de `(ownerAccountId, displayName)` em contas ativas e cota por dono na unidade atômica |
| Publisher | `publisher/` (`bsm-account-publisher`) | Publica o outbox no NATS, com trava de sessão, envelope estrito e `Nats-Msg-Id` (decisão 0019) |
| Reconciler | `reconciler/` (`bsm-account-reconciler`) | Compara `displayName`, `billingCurrency`, `billingContacts` e `deletionProtection` e decide `create`, `update` ou `delete`; estado reconstruído da mensageria |
| Observer | `observer/` (`bsm-account-observer`) | Lê o estado local em disco (somente leitura) e publica `observed`; partição por `resourceId` |
| Executor | `executor/` (`bsm-account-executor`) | Grava atomicamente (arquivo temporário + `os.replace`) ou remove o arquivo JSON da Billing Account no diretório local; revalida cada ação; um laço por partição |
| Testes e2e | `tests/e2e/` | Black-box: contrato, loop completo e caos (os cinco papéis de runtime) |

A CLI é o comando `sk bsm account create|get|list|update|protect|unprotect|delete` (`clients/cli`).

# 2. Papéis e componentes

Os seis papéis são **um projeto e uma imagem** (decisão 0063), cada um rodando como processo e contêiner próprios: cada papel tem o próprio papel de banco (`bsm_account_<papel>`, em `infrastructure/dev/database/bootstrap/bsm.sql`) e a própria identidade no NATS. O código igual em todos fica em `common/`, e nenhum papel importa outro.

| Componente | Serviço no Compose | Papel de banco | Alvo local | Escreve |
|---|---|---|---|---|
| Receiver | `bsm-account-receiver` | `bsm_account_receiver` (só leitura das views) | — | `requested` no NATS |
| Manager | `bsm-account-manager` | `bsm_account_manager` | — | SSOT (`bsm.account*`) e outbox |
| Publisher | `bsm-account-publisher` | `bsm_account_publisher` | — | `published_at` do outbox; NATS |
| Reconciler | `bsm-account-reconciler` | — | — | `action` no NATS |
| Observer | `bsm-account-observer` | — | volume `bsm-account-state` (`:ro`) | `observed` no NATS |
| Executor | `bsm-account-executor` | — | volume `bsm-account-state` (`rw`) | `completed` e `failed`; arquivo JSON no disco |

## 2.1 Receiver (`bsm-account-receiver`)

- Rotas sob `/v1/bsm/accounts`: `POST` cria, `GET` lista, `GET /{resourceId}` lê, `PATCH /{resourceId}` altera, `DELETE /{resourceId}?resourceVersion=` remove e `GET /{resourceId}/operations/{operationId}` acompanha a Operation.
- Valida o token (assinatura por JWKS, `iss`, `aud` = projeto `roles-bsm`, `exp`). O dono é o `sub`: nunca vem do corpo. Cada ação exige a role `bsm.account.<create|get|list|update|delete>`. Para criar, o solicitante precisa de **e-mail verificado** e de cota (`BSM_ACCOUNT_RECEIVER_API_ACCOUNT_QUOTA`, padrão 5); o operador (`bsm.account.admin`) não tem cota.
- O dono altera `displayName`, `billingContacts` e a proteção contra exclusão (`deletionProtection`); `reconciliation` é do operador; `billingCurrency` é imutável após a criação. A Billing Account **nasce protegida** (decisão 0043): o `DELETE` responde `409 DeletionProtected` até um `PATCH` com `deletionProtection: false`; alterar só a proteção percorre o loop como qualquer alteração e conclui quando a observação confirma a nova geração (decisão 0072). Uma Billing Account de outro dono responde `404`, para não revelar que existe. `Idempotency-Key` torna o `POST`, o `PATCH` e o `DELETE` repetíveis.
- Só lê o SSOT, pelas views `bsm.account_v1` e `bsm.account_operation_v1`. Não expõe `/docs` nem `/openapi.json`: o contrato descritivo é o arquivo versionado `openapi.json`, conferido por teste. Erros no formato `api-error`; a entrada inválida é `400` e nunca repete o valor enviado.

## 2.2 Manager (`bsm-account-manager`)

- Único escritor do SSOT (`bsm.account`, `bsm.account_operation`, `bsm.account_action_result`) e do outbox (`bsm.account_outbox`).
- Consome `requested` (criar, alterar e remover), `observed` e os resultados `completed` e `failed`. Aceita ou recusa com motivo (`conflict`, `validation`, `not_found`, `protected`): o `delete` de uma Billing Account protegida (`deletionProtection`, decisão 0043) é `protected`; `displayName` já usado pelo mesmo dono em conta ativa (`lifecycle = 'present'`) e cota por dono esgotada são `validation`; a unicidade por `(ownerAccountId, displayName)` e a cota são conferidas na mesma unidade atômica, sob trava consultiva composta e por dono, além do índice único parcial `account_owner_display_name_present`.
- Só insere no outbox: a publicação é do Publisher. ACK depois do `COMMIT`; falha transitória do banco é `RETRY`; mensagem fora do contrato (inclusive de outra versão `MAJOR`) é `TERM`.
- Aplica `observed` (fase `Ready`, `Reconciling` ou `Deleting`) e acompanha as Operations; remoção convergida apaga a linha.

## 2.3 Publisher (`bsm-account-publisher`)

- Lê o outbox em ordem de `sequence`, valida o envelope de forma estrita, acrescenta `publishedAt` e `publishedBy` e publica em `manager.desired.bsm.account.<resourceId>.changed` (e `updated`), com `Nats-Msg-Id` igual ao `messageId`. Marca `published_at` depois da confirmação.

## 2.4 Reconciler (`bsm-account-reconciler`)

- Mantém em memória o último `desired`, `observed` e resultado de cada Billing Account, reconstruídos a cada início (consumer por instância, `DeliverLastPerSubject`). Não acessa o SSOT.
- Compara `displayName`, `billingCurrency`, `billingContacts` e `deletionProtection`, decide com as guardas do loop e publica a `action` (`create`, `update` ou `delete`) com `Nats-Msg-Id` igual ao `actionId`.

## 2.5 Observer (`bsm-account-observer`)

- Lê o arquivo `<stateDir>/<resourceId>.json` no diretório local (somente leitura) e publica `observed`: `present` com `displayName`, `billingCurrency`, `billingContacts` e `deletionProtection`; `absent` quando o arquivo não existe; `unknown` para falha de I/O ou conteúdo fora do contrato.

## 2.6 Executor (`bsm-account-executor`)

- Único componente que escreve no diretório local de estado da Billing Account: grava `<stateDir>/<resourceId>.json` de forma atômica (arquivo temporário no mesmo diretório + `os.replace`) em `create` e `update`, e remove o arquivo em `delete` (idempotente se já ausente).
- Revalida cada `action` contra o `desired` vigente antes de executar.

# 3. Mensageria

| Stream | Subject | Consumer | Quem lê |
|---|---|---|---|
| `REQUESTED` | `receiver.requested.bsm.account.>` | `bsm-account-manager-requested` (durável) | Manager |
| `DESIRED` | `manager.desired.bsm.account.>` | `bsm-account-{reconciler,observer}-desired-<instância>` | Reconciler, Observer |
| `OBSERVED` | `observer.observed.bsm.account.>` | `bsm-account-manager-observed` (durável); `bsm-account-reconciler-observed-<instância>` | Manager, Reconciler |
| `RESULT` | `executor.*.bsm.account.>` | `bsm-account-manager-result` (durável); `bsm-account-{reconciler,observer}-result-<instância>` | Manager, Reconciler, Observer |
| `ACTION` | `reconciler.action.bsm.account.<partição>.>` | `bsm-account-executor-action-p0..p3` (duráveis) | Executor |

# 4. Contratos

Os contratos estão em `schemas/bsm/account/` (e `schemas/common/`), com o índice `schemas/bsm.account.index.json`: `desired`, `observed`, `requested-create|update|delete`, `api-create-request`, `api-update-request`, `resource` e `resource-list`. A API HTTP é descrita em [`openapi.json`](openapi.json), gerado por `uv run python -m bsm_account.receiver.http.openapi` e conferido por teste.

# 5. Configuração, execução e testes

Variáveis `BSM_ACCOUNT_<PAPEL>_<SEÇÃO>_<CAMPO>`, com `config.toml` por papel e senhas em `/run/secrets`. Todos os parâmetros de cada papel estão em [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md). O fluxo de dados completo está em [`docs/BSM-ACCOUNT-DATA-FLOW.md`](docs/BSM-ACCOUNT-DATA-FLOW.md).

```bash
# 1. Plataforma (banco, messaging, identidade, gateway): infrastructure/dev, no ar e saudável
# 2. Os componentes da Billing Account
cd features/bsm/account && cp -n .env.example .env   # preencha os valores vazios
docker compose up -d --build
# 3. Testes do projeto
uv sync && uv run ruff check . && uv run pyright && uv run pytest   # na raiz da feature
```
