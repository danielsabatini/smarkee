# sum.service

Módulo `sum`, tipo `service`: o uso de um serviço da plataforma (hoje, `ipm`) por um usuário. Um usuário
liga ou desliga um serviço, e a ligação concede ou revoga as roles desse serviço no Zitadel (decisão 0033).
É o SUM (Service Usage Manager). A estrutura segue a de `features/core/user`.

# 1. Estado da implementação

| Papel | Diretório | Estado |
|---|---|---|
| Receiver | `receiver/` | API `/v1/sum/services`: autentica, confere a role, publica `requested`. No ar no dev (Compose) |
| Manager | `manager/` | Consome `requested`, grava a ligação, a Operation e o outbox. No ar no dev (Compose) |
| Publisher | `publisher/` | Publica o outbox no NATS, com trava, envelope estrito e `Nats-Msg-Id`. No ar no dev (Compose) |
| Reconciler | `reconciler/` | Decisão, motor e processo. No ar no dev (Compose); ciclo de ligar e desligar verificado |
| Observer | `observer/` | Leitura somente de leitura, motor e processo. No ar no dev (Compose); ciclo verificado |
| Executor | `executor/` | Concede e revoga as roles no Zitadel, motor e processo, com isolamento verificado no dev |
| Testes e2e | `tests/e2e/` | Suíte black-box: **10 passam** no dev com a stack no ar e um solicitante de teste (loop completo de ligar e desligar incluído) |

Os componentes com `main.py` são os que entram no `compose.yaml`: hoje, Receiver, Manager e Publisher. Os demais têm
Dockerfile e consumers prontos, e entram no Compose quando o processo existir.

# 2. Arquitetura

![Componentes](docs/architecture/01-componentes.svg)

Fonte: [`01-componentes.mmd`](docs/architecture/01-componentes.mmd). O fluxo de dados completo está em
[`docs/SUM-SERVICE-DATA-FLOW.md`](docs/SUM-SERVICE-DATA-FLOW.md).

# 3. Papéis e componentes

Cada componente é autocontido (decisão 0015): tem o próprio papel de banco (`sum_service_<papel>`, em
`infrastructure/dev/database/bootstrap/sum.sql`), a própria identidade no NATS e, quando usa o Zitadel, a
própria conta de serviço.

| Componente | Serviço no Compose | Papel de banco | Conta no Zitadel | Escreve |
|---|---|---|---|---|
| Receiver | `sum-service-receiver` | `sum_service_receiver` (só leitura das views) | — | `requested` no NATS |
| Manager | `sum-service-manager` | `sum_service_manager` | — | SSOT (`sum.service*`) e outbox |
| Publisher | `sum-service-publisher` | `sum_service_publisher` | — | `published_at` do outbox; NATS |
| Reconciler | `sum-service-reconciler` | — | — | `action` no NATS |
| Observer | `sum-service-observer` | — | `sum-service-observer` (`ORG_OWNER_VIEWER` na `register`, leitura) | `observed` no NATS |
| Executor | `sum-service-executor` | — | `sum-service-executor` (`PROJECT_GRANT_OWNER` só no Grant de `roles-ipm`) | — (só o Zitadel) |

O Executor é o único componente que concede roles. O Zitadel nega as concessões fora do Grant de `roles-ipm`,
o que limita o estrago de uma credencial vazada (decisão 0032).

# 4. Consumers e subjects

Os manifestos ficam em cada componente (`consumers/`) e são criados pelo serviço `sum-service-consumer`, no
mesmo padrão de `core.user`.

| Stream | Subject | Consumer | Quem lê |
|---|---|---|---|
| `REQUESTED` | `receiver.requested.sum.service.>` | `sum-service-manager-requested` | Manager |
| `DESIRED` | `manager.desired.sum.service.>` | `sum-service-reconciler-desired`, `sum-service-observer-desired` | Reconciler, Observer |
| `OBSERVED` | `observer.observed.sum.service.>` | `sum-service-reconciler-observed` | Reconciler |
| `RESULT` | `executor.completed.sum.service.>`, `executor.failed.sum.service.>` | `sum-service-reconciler-completed/failed`, `sum-service-observer-completed/failed` | Reconciler, Observer |
| `ACTION` | `reconciler.action.sum.service.<partição>.>` | `sum-service-executor-action-p0..p3` | Executor |

No `ACTION`, a partição é aplicada pelo servidor (`subject_transform`, decisão 0018), uma por consumer, com
`max_ack_pending = 1`: uma ação por recurso por vez.

# 5. Configuração e execução

Variáveis `SUM_SERVICE_<COMPONENTE>_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. O `.env.example` lista as
obrigatórias.

```bash
# Plataforma (banco, broker, identidade, gateway): infrastructure/dev, no ar e saudável.
cp .env.example .env            # preencha as senhas e o catálogo (fora do git)
docker compose up -d --build    # migrações, consumers, Manager e Publisher
```

O papel `sum_service_*` e o esquema `sum` são criados uma vez por `infrastructure/dev/database/bootstrap/sum.sql`
e pelas migrações de `manager/migrations/`. Nos bancos de dev já existentes, esses dois passos foram aplicados
à mão, porque o bootstrap só roda na criação do volume.

# 6. Testes

```bash
cd <componente> && uv run pytest && uv run ruff check . && uv run pyright
```

Os testes de integração de `manager/` e `publisher/` pedem as URLs dos papéis e as credenciais do broker de dev
(ver o README de cada componente). Sem essas variáveis, são pulados. Os testes deixam o banco como estava, e os
de NATS usam um stream temporário, nunca o `DESIRED` real.

# 7. Pendências

- Receiver: subir como contêiner e verificar a rota pelo gateway. Testes de integração do repositório.
- Manager: consumo de `observed` e de resultados (`completed` e `failed`). Hoje a fase do recurso fica `Pending`,
  porque o Manager ainda não aplica esses resultados ao SSOT.
- Reconstrução do estado do Reconciler e do Observer ao reiniciar; partição do Observer.
- Estratégia de apagar os recursos do usuário no serviço (decisão 0033; fora desta fase).
