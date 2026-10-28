# ipm-serviceaccount-controller

Controller de `ipm.serviceaccount` (`ipm-serviceaccount-controller`), um dos quatro papéis da imagem única `ipm-serviceaccount` (decisões 0063 e 0096), com processo e contêiner próprios. Veja o [README da feature](../../../README.md).

Observa, decide, age e reobserva a service account (usuário de máquina do Zitadel) **numa só transação**, e grava o estado convergido e o `updated` no outbox. Substitui os antigos Observer, Reconciler e Executor, no modelo de controlador do Kubernetes (Informer + Workqueue). Decisão [`0096`](../../../../../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md).

## Ciclo

1. **Informer:** consome `desired.ipm.serviceaccount.>` (Stream `DESIRED`, consumer `ipm-serviceaccount-controller-desired-<instância>`) e enfileira o `resourceId` na Workqueue, só se ele pertencer à partição da instância (`hash(resourceId) mod count == index`).
2. **Reavaliação periódica:** enfileira todos os recursos `reconciliation = 'active'` da partição, com jitter, para detectar divergência externa.
3. **Workqueue:** deduplica por `resourceId` e repete com backoff exponencial quando o provedor falha de forma transitória ou o recurso ainda não convergiu.
4. **`reconcile(resourceId)`**, numa transação com a linha bloqueada (`FOR UPDATE`):
   - observa o Zitadel (usuário de máquina, chaves, autorizações em `roles-ipm` e metadados);
   - decide com a função pura `decide(desired, observed)` (`domain/decision.py`): `create`, `update`, `delete` ou nada;
   - executa a ação idempotente nos drivers, se houver divergência, e **reobserva**;
   - calcula fase e conditions (`domain/convergence.py`), grava `observed`, `phase`, `conditions`, as Operations e o `updated` no outbox; se a remoção convergiu, apaga o registro; se atingiu o limite de falhas, suspende a reconciliação e grava um `desired` suspenso no outbox.

A idempotência da ação vem das operações idempotentes dos drivers e do ciclo atômico; não há registro por `actionId` (a tabela `ipm.serviceaccount_action_result` foi removida).

## Regras do tipo

- Campos gerenciados: `lifecycle`, `permissions`, `deletionProtection`, `description` e os fingerprints das chaves; `organizationId` e `name` são imutáveis. Chave vencida segue como `expired`, sem divergência.
- Token sempre `ACCESS_TOKEN_TYPE_JWT`. Só chaves **públicas** passam por aqui; o Zitadel não devolve a pública, então o metadado `keys` guarda o mapa `fingerprint → keyId`, cruzado com o `ListKeys` na observação.
- As autorizações ficam com **exatamente** as permissões do `desired`; o Project Grant de `roles-ipm` é o teto.
- `absent` só com o `404` do usuário exato; qualquer outra falha é `unknown`.

## Estrutura

```text
src/ipm_serviceaccount/controller/
  domain/      decisão pura e convergência (fase, conditions, prazos)
  drivers/     Zitadel: conexão, máquina e chaves, autorização e metadados
  engine/      Informer, Workqueue, observação, ação e o ciclo atômico
  store/       único código com SQL do Controller (ControllerSsotStore)
  settings.py
  main.py
```

## Privilégios

- **Banco:** papel `ipm_serviceaccount_controller` (migrações `0002` e `0003`): `SELECT`, `UPDATE` e `DELETE` em `ipm.serviceaccount`; `SELECT` e `UPDATE` em `ipm.serviceaccount_operation`; só `INSERT` no outbox. Não cria nem altera o `desired` de um pedido.
- **Zitadel:** conta `ipm-serviceaccount-controller`, com `ORG_USER_CREATOR` e `ORG_OWNER_VIEWER` em cada organização de cliente e `PROJECT_GRANT_OWNER` no Grant de `roles-ipm` dela.

## Saúde

`GET /health/live`, `/health/ready` e `/health/startup` na porta `8000`.

## Configuração

Variáveis de ambiente `IPM_SERVICEACCOUNT_CONTROLLER_<SEÇÃO>_<CAMPO>` e o `config.toml` da feature. Obrigatórias, sem default: `IPM_SERVICEACCOUNT_CONTROLLER_DATABASE_PASSWORD`, `IPM_SERVICEACCOUNT_CONTROLLER_MESSAGING_PASSWORD` e `IPM_SERVICEACCOUNT_CONTROLLER_IDENTITY_PROJECT_ID`. Todos os campos estão em [`docs/CONFIGURATION.md`](../../../docs/CONFIGURATION.md).

## Desenvolvimento

```bash
# Na raiz da feature (features/ipm/serviceaccount), que é o projeto único:
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/controller  # os testes de integração exigem a stack de dev e são pulados sem ela
```

Imagem: o `Dockerfile` da feature (imagem única; este papel roda com `command: ipm-serviceaccount-controller`).
