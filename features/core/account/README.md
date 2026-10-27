# core.account

O **Account** é a identidade da plataforma: a pessoa que se cadastra sozinha (`sk account create`) e depois se autentica (`sk auth login`) para criar Organizations. É um recurso do módulo `core`, gerenciado pelo Resource Control Loop (`docs/loop/RESOURCE-CONTROL-LOOP.md`), e vive na organização `register` do Zitadel.

Decisões que definem esta feature: `0098` (API síncrona e fim da Operation), `0100` (sem chamadas HTTP entre features: projeções locais do `DESIRED`), `0096` (o loop unificado no Controller), `0014` (Account e auto-cadastro sem senha), `0013` (API → CLI → console, Zitadel protegido), `0010` (roles e dono), `0040` (exclusão segura), `0043` e `0074` (proteção contra exclusão como metadado), `0072` (toda alteração percorre o loop), `0075` (motores gerados do template) e `0063` (um projeto, uma imagem). A `0096` substitui, para este tipo, a separação em Observer, Reconciler e Executor. A feature `features/ipm/user` é o **modelo** desta estrutura.

# 1. Estado da implementação

| Papel | Projeto | Estado |
|---|---|---|
| API | `api/` (`core-account-api`) | API `/v1/core/accounts`: autentica, decide o acesso (o dono ou o operador) e admite a escrita síncrona numa transação (e-mail único, versão, recurso e `desired` no outbox). Cadastro anônimo uniforme. Contrato em `openapi.json` |
| Publisher | `publisher/` (`core-account-publisher`) | Publica o outbox no NATS (template, decisão 0065) |
| Controller | `controller/` (`core-account-controller`) | Decisão 0096: lê o `desired` do Stream `DESIRED` e, por conta, observa o Zitadel, decide, age e reobserva numa só transação, e grava o estado e o `updated` no outbox. Substitui o Reconciler, o Observer e o Executor |
| Telemeter (observabilidade, **não é papel do loop**) | `telemeter/` (`core-account-telemeter`) | Recebe os logs e os spans de app da feature (do `telemetry-router`) e os grava em `telemeter/logs/` e `telemeter/traces/` (decisão 0062) |
| Testes e2e | `tests/e2e/` | Black-box: contrato, loop completo contra o Zitadel e resiliência (`E2E_CHAOS=1`); **não são um componente** |
| CLI | `clients/cli` | `sk account create` (cadastro anônimo), `sk account get|protect|unprotect|delete` |

Além dos papéis, o serviço `core-account-migrate` (migrações) roda e sai.

A ativação (senha e e-mail) foi verificada em dev em 2026-10-12 (`docs/platform/IMPLEMENTATION-STATUS.md` §7). **Não verificado de ponta a ponta:** o `sk auth login` com o usuário novo. A migração para a API síncrona (decisão 0098) tem verificação por testes (unidade, contrato e integração contra o banco de dev); a execução e2e contra os contêineres novos depende de subir a stack (ver §10).

# 2. Arquitetura

![Componentes](docs/architecture/01-componentes.svg)

*Fonte: [`docs/architecture/01-componentes.mmd`](docs/architecture/01-componentes.mmd).* O diagrama ainda mostra o modelo anterior (Receiver, Manager, Reconciler, Observer e Executor); o texto deste README é o vigente (pendência declarada, §10). O fluxo de dados completo está em [`docs/CORE-ACCOUNT-DATA-FLOW.md`](docs/CORE-ACCOUNT-DATA-FLOW.md).

Os papéis são **um projeto e uma imagem** (decisão 0063), cada um rodando como processo e contêiner próprios, com o próprio papel de banco (`core_account_<papel>`, em `infrastructure/dev/database/bootstrap/core.sql`), a própria identidade no NATS e, quando usa o Zitadel, a própria conta de serviço. O que os une é a mensageria, o SSOT (cada papel com o seu privilégio) e os contratos neutros de `schemas/`.

# 3. Papéis e componentes

| Componente | Serviço no Compose | Papel de banco | Conta no Zitadel | Escreve |
|---|---|---|---|---|
| API | `core-account-api` | `core_account_api` (`SELECT`, `INSERT` e `UPDATE` em `account`; `SELECT` na view; `INSERT` no outbox; `SELECT` e `INSERT` na idempotência; sem `DELETE`) | — | SSOT (`core.account*`) e outbox |
| Publisher | `core-account-publisher` | `core_account_publisher` | — | `published_at` do outbox; NATS |
| Controller | `core-account-controller` | `core_account_controller` (`SELECT`, `UPDATE` e `DELETE` em `account`; `INSERT` só no outbox) | `core-account-controller` (`ORG_USER_CREATOR` e `ORG_OWNER_VIEWER` na `register` e `PROJECT_GRANT_OWNER` nos Grants dos módulos) | estado observado, fase, conditions e `updated` no SSOT (e o `desired` suspenso, ao suspender); o usuário no Zitadel |

## 3.1 API (`core-account-api`)

| Rota | Efeito | Quem | Respostas |
|---|---|---|---|
| `POST /v1/core/accounts` | Auto-cadastro (**anônimo**) | Qualquer pessoa | `202` + `{resourceId}` uniforme, `400`, `429` (com `Retry-After`), `503` (com `Retry-After`) |
| `GET /v1/core/accounts/{id}` | Lê a conta (`Resource`) | O próprio usuário ou `core.account.admin`, permissão `core.account.get` | `200`, `401`, `403`, `404` |
| `PATCH /v1/core/accounts/{id}` | Liga ou desliga a proteção contra exclusão (corpo `{resourceVersion, deletionProtection}`; cabeçalho opcional `Idempotency-Key`) | O próprio usuário ou `core.account.admin`, permissão `core.account.delete` | `200` + `Resource`, `400`, `401`, `403`, `404`, `409`, `422`, `503` |
| `DELETE /v1/core/accounts/{id}?resourceVersion=` | Pede a remoção (cabeçalho opcional `Idempotency-Key`) | O próprio usuário ou `core.account.admin`, permissão `core.account.delete` | `202` + `Resource` (`phase=Deleting`), `400`, `401`, `403`, `404`, `409`, `422`, `503` |

Não há Operation: a convergência se lê no próprio recurso (`observedGeneration >= desiredGeneration` com `phase` `Ready` ou `Failed`; depois do `DELETE`, `404`). Não há listagem. O contrato descritivo é [`openapi.json`](openapi.json). Erros: `{errorCode, message, field?}` (`schemas/common/api-error`), sem repetir valores enviados. Quem não é o dono recebe `404`, e não `403`, para não revelar a existência.

- **Admissão (decisão 0098):** numa transação, bloqueia a linha (`FOR UPDATE`), confere a versão (`409 Conflict`), o estado (`409 NotPresent` para conta em remoção) e a proteção (`409 DeletionProtected`); grava o recurso (`requested_by`, `correlation_id`, geração) e o `desired` no outbox. Banco indisponível é `503 StorageUnavailable` com `Retry-After`. Um `PATCH` sem mudança efetiva devolve `200` com o recurso atual, sem gravar.
- **Idempotência:** `Idempotency-Key` opcional, por solicitante, em `core.account_idempotency`. Mesma chave e mesmo conteúdo devolvem o recurso atual; conteúdo diferente é `422 IdempotencyKeyReused`.
- **Auto-cadastro uniforme:** a resposta é sempre `202` com um `resourceId` novo, exista ou não o e-mail (`RESOURCE-CONTROL-LOOP.md` §6.1.2). Se o e-mail já está em uso (normalizado em minúsculas, trava consultiva `pg_advisory_xact_lock` e consulta sobre as contas `present`), a transação é revertida e **nada é gravado nem publicado**. `requestedBy = anonymous`; não há `Idempotency-Key`. Limite de taxa por origem no gateway (10/min por IP) e na API (5/60 s).
- **`desired` da criação:** `platformAccess = granted`, `platformPermissions` (`CORE_ACCOUNT_API_PLATFORM_PERMISSIONS`, decisão 0025) e `deletionProtection = true`. O `desired` de remoção mantém só `lifecycle = absent`, `platformAccess` e `platformPermissions`: **sem dados pessoais**.
- **Exclusão segura (decisões 0040 e 0100):** a API confere se a conta ainda tem Organizations, serviços ou contas de cobrança com **projeções locais** do Stream `DESIRED` (`ipm.organization`, `bsm.account` e `sum.service`, por `ownerAccountId`), sem chamar outras APIs. Só o dono pode verificar (`409 ResourcesNotVerifiable` para outro solicitante); projeção ainda sincronizando é `503 ProjectionSyncPending` (`Retry-After`); recursos atrelados é `409 ResourcesAttached`. A conta já em remoção pula as checagens (idempotente).

## 3.2 Publisher e Controller

- **Publisher:** o do template (decisão 0065), sem regra do tipo. Publica `desired` (que a API gravou) e `updated` (que o Controller gravou) do mesmo outbox. Detalhes em [`publisher/README.md`](src/core_account/publisher/README.md).
- **Controller:** consome o Stream `DESIRED`, enfileira o `resourceId` numa fila com deduplicação e backoff e, para cada um, executa o ciclo atômico `reconcile`. Detalhes no [README do Controller](src/core_account/controller/README.md) e em [`docs/CORE-ACCOUNT-DATA-FLOW.md`](docs/CORE-ACCOUNT-DATA-FLOW.md), seção 4.
  - **Decisão:** campos gerenciados `lifecycle`, `platformAccess`, `platformPermissions` (as desejadas precisam estar contidas nas observadas) e `deletionProtection`; os dados pessoais são imutáveis.
  - **Observação:** lê o usuário (`accountState`, `initial` até a senha ser definida, e `emailVerified`), as permissões nos projetos da plataforma e o metadado `deletionProtection`. `absent` só com o `404` do usuário exato; qualquer falha é `unknown`.
  - **Ação:** cria o usuário humano **sem senha** na organização `register` (o Zitadel envia o e-mail de verificação, que também define a senha) e concede as permissões do `desired`, cada uma no projeto do seu módulo (decisão 0032); remove o usuário no `delete`.

## 3.3 Um projeto, uma imagem, três papéis (decisões 0063, 0096 e 0098)

```text
src/core_account/
  common/      igual em todos os papéis (template, decisão 0064), exceto resource.py e contracts/generated.py
  api/  publisher/  controller/    (cada um com o seu README)
tests/
  common/  api/  publisher/  controller/    (unit, contract e integration)
  e2e/                                      (projeto à parte, black-box)
migrations/    SQL da API e do Controller, aplicado pelo serviço core-account-migrate
```

Os arquivos de `common/` (exceto `resource.py` e `contracts/generated.py`) são gerados do template (`templates/feature`, decisão 0064): altere o modelo, não a cópia. Um papel nunca importa outro (`tests/common/unit/test_role_isolation.py`).

## 3.4 Estrutura interna dos papéis

| Papel | Pastas | README |
|---|---|---|
| API | `auth/`, `domain/`, `http/`, `store/`, `transport/` (projeções do `DESIRED` para a exclusão segura) | [`api`](src/core_account/api/README.md) |
| Publisher | `domain/`, `outbox/` | [`publisher`](src/core_account/publisher/README.md) |
| Controller | `domain/` (`decision`, `convergence`), `drivers/` (`user`, `authorization`, `metadata`, `identity`), `engine/` (fila, observação, ação, ciclo `reconcile`), `store/` | [`controller`](src/core_account/controller/README.md) |

A saúde (`/health/*`) é de `common/http/health.py`, igual em todos os papéis.

## 3.5 Testes e2e (`tests/e2e`)

Suíte black-box (decisão 0017): fala só com o gateway, o NATS e o SSOT (leitura do observado e limpeza), e valida as respostas e as mensagens contra os JSON Schemas de `schemas/`. Ver [`tests/e2e/README.md`](tests/e2e/README.md).

# 4. Fluxos

Os diagramas de `docs/flow/` e `docs/state/` ainda descrevem o modelo anterior (com Receiver, Manager, Reconciler, Observer, Executor e Operation). **Pendência declarada (decisões 0096 e 0098):** serão redesenhados; o texto de [`docs/CORE-ACCOUNT-DATA-FLOW.md`](docs/CORE-ACCOUNT-DATA-FLOW.md) é o vigente.

| Fluxo (modelo anterior) | Diagrama |
|---|---|
| Caminho perfeito | [`flow/01-caminho-perfeito`](docs/flow/01-caminho-perfeito.svg) |
| Erros antes do loop | [`flow/02-validacao-e-borda`](docs/flow/02-validacao-e-borda.svg) |
| E-mail já cadastrado | [`flow/03-email-ja-cadastrado`](docs/flow/03-email-ja-cadastrado.svg) |
| Falhas | [`04`](docs/flow/04-falhas-no-manager-e-mensageria.svg), [`05`](docs/flow/05-falhas-na-reconciliacao.svg), [`06`](docs/flow/06-falhas-no-executor-e-email.svg) |
| Ativação e login | [`flow/07-ativacao-e-login`](docs/flow/07-ativacao-e-login.svg) (vale como está) |
| Remoção | [`flow/08-remocao`](docs/flow/08-remocao.svg) |

### Como ativar a conta (senha e e-mail)

Depois do `sk account create`, a pessoa tem uma conta criada, mas sem senha e com o e-mail não verificado. Ela ativa a conta assim:

1. **Abra o e-mail "Verificar e-mail"** mais recente do provedor e use o botão. A página do Zitadel confirma o e-mail e já pede a senha: informe e confirme (a política de senha da instância se aplica). Um e-mail só.
2. **Entre.** Com o e-mail confirmado e a senha definida, `sk auth login` autentica a pessoa.

Em desenvolvimento, as mensagens chegam ao Mailpit (http://localhost:8025). Em outros ambientes, chegam à caixa de e-mail real.

**Se o link expirou ou a pessoa não recebeu o e-mail:**

- **Senha:** na tela de login do Zitadel (`http://ipm-dev.smarkee.com.br:8080/ui/v2/login/`), use a opção de recuperar a senha ("Esqueci a senha") e informe o e-mail do cadastro, que é também o nome de login. O Zitadel envia um novo link. Use sempre o link da mensagem mais recente.
- **Verificação do e-mail:** na página de verificação, use a opção de reenviar o código.

Esses reenvios não passam pela plataforma, de propósito: um reenvio anônimo revelaria se um e-mail já está cadastrado (`docs/loop/RESOURCE-CONTROL-LOOP.md`, seção 6.1.2).

**Procedimento do operador (dev).** Se a opção do provedor não estiver disponível, um operador reenvia com a conta de serviço do Executor, que já tem essa permissão (`docs/loop/RESOURCE-CONTROL-SECURITY.md`, seção 9): `POST /v2/users/{id}/password_reset` com `{"sendLink": {}}` para o link de senha, e `POST /v2/users/{id}/email/resend` com `{"sendCode": {}}` para o código de verificação. A chave da conta de serviço nunca sai do volume `identity-bootstrap`.

# 5. Estados

Fase do recurso: [`state/01-fase-do-recurso`](docs/state/01-fase-do-recurso.svg). A Operation deixou de existir (decisão 0098); [`state/02-operation`](docs/state/02-operation.svg) é histórico. A fase `Failed` suspende a reconciliação; a saída é uma nova geração ou intervenção explícita.

# 6. Mensageria

O tipo **não tem** o Stream `REQUESTED` (decisão 0098): a API grava o `desired` no outbox na própria admissão, com `emitter: api`. O `updated` do Controller continua com `emitter: manager`. Gramática e modelo geral em [`docs/messaging/NATS.md`](../../../docs/messaging/NATS.md).

| Mensagem | Subject | Publica | Consome | Stream |
|---|---|---|---|---|
| `desired` | `manager.desired.core.account.<id>.changed` | Publisher (a API grava no outbox) | Controller | `DESIRED` |
| `updated` | `manager.updated.core.account.<id>.changed` | Publisher (o Controller grava no outbox) | Console, auditoria, métricas | `UPDATED` |

A API também lê, como projeções locais (decisão 0100), o `DESIRED` de `ipm.organization`, `bsm.account` e `sum.service`, para a exclusão segura. Consumers do Controller: `core-account-controller-desired-<instância>`.

# 7. Contratos

Em [`schemas/core/account/`](../../../schemas/core/account/) (JSON Schema 2020-12, com exemplos): `definitions`, `desired`, `observed`, `api-create-request`, `api-registration-response`, `api-update-request` e `resource`; e, em `schemas/common/`, envelope, `updated` e `api-error`. O índice usado para gerar os modelos é `schemas/core.account.index.json`; os modelos Pydantic são gerados (`uv run datamodel-codegen`, decisão 0012).

`givenName`, `familyName` e `email` são `confidential` (nunca em log, mensagem de erro nem métrica) e **não existem** no `desired` de remoção. Campos gerenciados: `lifecycle`, `platformAccess`, `platformPermissions` (as desejadas precisam estar contidas nas observadas; permissões a mais não divergem) e `deletionProtection`. Não há senha em nenhum contrato (`SCHEMA.md` §20.1).

# 8. Segurança e privacidade

- **Cadastro anônimo:** `requestedBy = anonymous`; limite de taxa por origem; resposta uniforme; nada é revelado sobre e-mails cadastrados, e a API não expõe nada de uma conta a quem não é o dono ou o operador.
- **Sem senha na mensageria:** o Zitadel cria o usuário e envia o link; a senha é definida na página dele.
- **Menor privilégio:** a API não tem `DELETE` nem conta no Zitadel (valida tokens pelo JWKS); o Controller é a única identidade que escreve no Zitadel e só ele remove a linha do SSOT; o Publisher só lê o outbox e marca `published_at`.
- **Observação inconclusiva nunca é ausência.**
- **Dados pessoais:** só no `desired` de criação (SSOT e `DESIRED`); o `desired` de remoção não os carrega; o `observed` não os traz.

## 8.1 Identidades e privilégios por papel

| Papel | Banco | NATS | Zitadel |
|---|---|---|---|
| API | `SELECT` na view; `SELECT`, `INSERT` e `UPDATE` em `account`; `INSERT` no outbox; `SELECT` e `INSERT` em `account_idempotency` | lê o `DESIRED` (projeções) | só valida tokens (JWKS) |
| Publisher | `SELECT` no outbox e `UPDATE (published_at)` | publica `desired` e `updated` | — |
| Controller | `SELECT`, `UPDATE` e `DELETE` em `account`; `INSERT` no outbox | lê `desired` | `ORG_USER_CREATOR` e `ORG_OWNER_VIEWER` na `register`; `PROJECT_GRANT_OWNER` nos Grants dos módulos |

A manutenção (`core_maintenance`) é uma identidade de infraestrutura, com `SELECT` e `DELETE` no outbox e na idempotência. **Saúde:** cada componente atende `GET /health/live`, `/health/ready` e `/health/startup` na porta `8000` (rede interna; o gateway publica só `/v1/core/accounts`).

# 9. Configuração, execução e testes

Variáveis `CORE_ACCOUNT_<PAPEL>_<SEÇÃO>_<CAMPO>`, com `config.toml` por papel e senhas em `/run/secrets`. Todos os parâmetros estão em [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) (decisões 0067 e 0070). O `.env.example` lista as obrigatórias: a senha do NATS, as senhas dos papéis do banco, a audience da API (`CORE_ACCOUNT_API_AUTH_AUDIENCE`) e, no Controller, os IDs no Zitadel (a organização `register` e os projetos de permissões).

```bash
# 1. Plataforma (banco, messaging, identidade, gateway, e-mail): infrastructure/dev
cd infrastructure/dev && docker compose up -d && docker compose up -d --wait messaging database gateway identity identity-login mail

# 2. Os componentes da Account
cd features/core/account && cp -n .env.example .env   # preencha os valores vazios
docker compose up -d --build

# 3. Testes do projeto
uv sync && uv run ruff check . && uv run pyright && uv run pytest
# 4. Testes e2e (stack no ar): ver tests/e2e/README.md
```

Os e-mails do Zitadel de dev são capturados pelo Mailpit (http://localhost:8025): ninguém os recebe.

# 10. Limitações e pendências

- **Diagramas** de `docs/{flow,state,architecture,database}`: ainda no modelo anterior (§4).
- **Stack de dev:** os contêineres novos (`core-account-{api,controller,publisher,telemeter}`) precisam substituir os antigos (`receiver`, `manager`, `executor`, `observer`, `reconciler`), a conta Zitadel `core-account-controller` precisa existir e o gateway deve ser reiniciado após recriar a API (cache de DNS). Sem isso, a suíte e2e não roda de ponta a ponta.
- **CLI:** `sk account create` confirma que o pedido foi aceito e orienta a verificar o e-mail; `sk account get|protect|unprotect|delete` consulta e exclui a própria conta (exclusão segura, decisões 0040 e 0100).
- **E-mail:** o loop não garante a entrega; falha de SMTP, endereço errado e spam estão fora da garantia. É um e-mail só ("Verificar e-mail"), com texto do Zitadel a revisar.
- **Retomada de `Failed`:** a Account não tem `update` além da proteção; falta definir a intervenção explícita.
- **Exclusão:** a política completa (dados residuais, sessões e confirmação) ainda será definida (`ROADMAP.md`); a exclusão pela API vale só para a própria conta.
- **Retenção:** o outbox e a idempotência não têm retenção implementada: o `payload` do `desired` de criação (com dados pessoais) permanece no outbox e no Stream `DESIRED` até a limpeza (`docs/platform/IMPLEMENTATION-STATUS.md`).
- **Migrações:** sem controle de versão (obrigatório antes de stg e prd).
- **Controller:** em dev, uma só partição (`0/1`); com mais réplicas, defina `CORE_ACCOUNT_CONTROLLER_PARTITION_INDEX` e `_COUNT` por réplica.
- **Identidades no NATS em dev:** os componentes se conectam com um único usuário (`smarkee`); as identidades e permissões por papel (`docs/messaging/NATS.md`) são o alvo para stg e prd.

# 11. Banco de dados (SSOT da Account)

O SSOT da Account é o schema `core` do banco `ssot` (decisão 0087). A especificação lógica está em [`docs/data/SSOT.md`](../../../docs/data/SSOT.md) e a física, em [`docs/data/POSTGRESQL.md`](../../../docs/data/POSTGRESQL.md). A migração [`0001-account.sql`](migrations/0001-account.sql) cria o estado inicial e a [`0011-account-api.sql`](migrations/0011-account-api.sql) introduz a API síncrona (decisão 0098): adiciona `core.account_idempotency`, remove `core.account_operation`, `core.account_action_result` e a view da Operation, e troca os papéis `core_account_manager` e `core_account_receiver` por `core_account_api` e `core_account_controller`. Os papéis vêm de [`infrastructure/dev/database/bootstrap/core.sql`](../../../infrastructure/dev/database/bootstrap/core.sql).

> O diagrama [`docs/database/01-er-fisico`](docs/database/01-er-fisico.svg) ainda mostra as tabelas da Operation e do resultado de ação (pendência declarada, §10).

## 11.1 Tabelas

| Tabela | Conteúdo | Quem grava |
|---|---|---|
| `core.account` | Uma linha por conta: intenção, observado, fase, geração confirmada | API (admissão síncrona); Controller (observado, fase, conditions, geração confirmada; remove a linha ao convergir a remoção) |
| `core.account_idempotency` | Idempotência das admissões autenticadas | API |
| `core.account_outbox` | Mensagens `desired` e `updated` à espera de publicação, com o `traceparent` | API insere o `desired`; Controller insere o `updated`; Publisher marca `published_at` |

Views: `core.account_v1` (a conta **sem** `failure_count`, com `observed_generation`).

## 11.2 O que cada coluna `jsonb` guarda

- `account.desired`: `lifecycle`, `platformAccess`, `platformPermissions`, `deletionProtection` (nasce `true`) e, enquanto `present`, `givenName`, `familyName` e `email` (normalizado). Na remoção, só `lifecycle = absent`, `platformAccess` e `platformPermissions`.
- `account.observed`: `emailVerified`, `accountState`, `platformAccess`, `platformPermissions` e `deletionProtection`.
- `account.conditions`: array de conditions (`Ready`, `Progressing`, `ObservationStale`).
- `account_outbox.payload`: o envelope completo (`desired` ou `updated`), com `publishedAt` e `publishedBy` preenchidos pelo Publisher.

## 11.3 Índices e restrições

- `account_email` (índice **não único** sobre `desired ->> 'email'`): a unicidade do e-mail é conferida pela API na admissão, sob trava consultiva por e-mail, e não por restrição única. Escrever na tabela por outro caminho pularia a regra.
- `account_outbox_pending` e `account_outbox_published`: o Publisher lê só o que falta publicar; a retenção do que já foi publicado ainda não existe.
- `account_idempotency_retention`: apoio à retenção da idempotência (a tarefa ainda não existe).
- Restrições `CHECK` nas colunas de controle e identificação, e em `observed_generation` (nula, ou entre 1 e `desired_generation`).

## 11.4 Dados pessoais no banco

`givenName`, `familyName` e `email` ficam em claro em `core.account.desired` e no `payload` da linha do outbox que carregou o `desired` de criação. Com a remoção, a linha de `core.account` sai e o `desired` de remoção não os carrega, **mas o outbox não tem retenção implementada**: o `payload` do `desired` de criação permanece nele (e no Stream `DESIRED`, como tombstone até a limpeza). É uma pendência de privacidade registrada em `docs/platform/IMPLEMENTATION-STATUS.md`.

## 11.5 Consultas úteis (dev)

```bash
# Contas por fase
docker exec database.smarkee.internal psql -U postgres -d ssot -c \
  'SELECT phase, count(*) FROM core.account GROUP BY phase'
# Atraso do outbox (idade da mensagem pendente mais antiga)
docker exec database.smarkee.internal psql -U postgres -d ssot -c \
  'SELECT now() - min(created_at) AS atraso, count(*) AS pendentes FROM core.account_outbox WHERE published_at IS NULL'
# Geração pedida e confirmada
docker exec database.smarkee.internal psql -U postgres -d ssot -c \
  'SELECT resource_id, desired_generation, observed_generation, phase FROM core.account ORDER BY updated_at DESC LIMIT 20'
```
