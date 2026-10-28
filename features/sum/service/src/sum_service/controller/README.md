# sum-service-controller

Controller de `sum.service` (`sum-service-controller`), um dos papéis da imagem única `sum-service` (decisões 0033, 0096 e 0098), com processo e contêiner próprios. Veja o [README da feature](../../../README.md) e o [fluxo de dados](../../../docs/SUM-SERVICE-DATA-FLOW.md).

Observa, decide, age e reobserva as permissões do dono da ligação no Zitadel **numa só transação**, e grava o estado convergido e o `updated` no outbox. Substitui os antigos Manager (parte de estado), Observer, Reconciler e Executor, no modelo de controlador do Kubernetes (Informer + Workqueue). Decisão [`0096`](../../../../../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md).

## Ciclo

1. **Rollout do catálogo (na partida):** cada ligação cujo `desired` difere do que o catálogo atual produz ganha uma geração nova (`requested_by = system:catalog`) e um `desired` no outbox (decisão 0079). Repetir não grava nada.
2. **Informer:** consome `manager.desired.sum.service.>` (Stream `DESIRED`, consumer `sum-service-controller-desired-<instância>`) e enfileira o `resourceId` na Workqueue, só se ele pertencer à partição da instância (`hash(resourceId) mod count == index`).
3. **Reavaliação periódica:** enfileira todos os recursos `reconciliation = 'active'` da partição, com jitter, para detectar divergência externa.
4. **Workqueue:** deduplica por `resourceId` e repete com backoff exponencial quando o provedor falha de forma transitória ou o recurso ainda não convergiu.
5. **`reconcile(resourceId)`**, numa transação com a linha bloqueada (`FOR UPDATE`):
   - observa o Zitadel (o usuário dono e as autorizações nos projetos configurados), limitado às permissões que a ligação controla;
   - decide com a função pura `decide(desired, observed)` (`domain/decision.py`): `enable`, `disable` ou nada;
   - executa a ação idempotente nos drivers, se houver divergência, e **reobserva**;
   - calcula fase e conditions (`domain/convergence.py`), grava `observed`, `phase` e `conditions` e o `updated` no outbox; se atingiu o limite de falhas, suspende a reconciliação e grava um `desired` suspenso no outbox.
6. **Conta removida (decisão 0044):** um segundo consumer lê `manager.updated.core.account.>` (Stream `UPDATED`) e, no `updated` com `removed`, apaga as ligações do dono (`DELETE FROM sum.service WHERE owner_account_id = …`). Repetir não tem efeito.

## Regras do tipo

- Campos gerenciados: as `managedPermissions`. As `servicePermissions` precisam estar com o usuário; as demais permissões gerenciadas (por exemplo, uma que saiu do catálogo) não podem estar.
- `disable` tira só as permissões gerenciadas e mantém as demais (o usuário pode ter permissões de outros serviços); a autorização que ficar vazia é removida.
- Ligação desfeita convergida: sem nenhuma permissão gerenciada, inclusive quando o usuário já não existe. A linha **não é apagada** (decisão 0033); o `observed` vira `absent` com `servicePermissions: []`.
- `absent` só com o `404` do usuário exato; qualquer outra falha de leitura é `unknown`, que nunca autoriza ação.

## Estrutura

```text
src/sum_service/controller/
  domain/      decisão pura e convergência (fase, conditions, prazos)
  drivers/     Zitadel: conexão, usuário (leitura) e autorização
  engine/      Informer, Workqueue, observação, ação, ciclo atômico, rollout e conta removida
  store/       único código com SQL do Controller (ControllerSsotStore)
  settings.py
  main.py
```

## Privilégios

- **Banco:** papel `sum_service_controller`: `SELECT`, `UPDATE` e `DELETE` em `sum.service` (o `DELETE` só serve à conta removida); só `INSERT` no outbox.
- **Zitadel:** conta `sum-service-controller`, com `ORG_OWNER_VIEWER` na organização `register` e `PROJECT_GRANT_OWNER` nos Grants dos projetos de permissões dos serviços do catálogo (hoje `roles-ipm`).

## Saúde

`GET /health/live`, `/health/ready` e `/health/startup` na porta `8000`.

## Configuração

Variáveis `SUM_SERVICE_CONTROLLER_<SEÇÃO>_<CAMPO>` e o `config.toml` da feature. Todos os campos estão em [`docs/CONFIGURATION.md`](../../../docs/CONFIGURATION.md).
