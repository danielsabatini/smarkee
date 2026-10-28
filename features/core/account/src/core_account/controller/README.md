# core-account-controller

Controller de `core.account` (`core-account-controller`), um dos papéis da imagem única `core-account` (decisões 0014, 0096 e 0098), com processo e contêiner próprios. Veja o [README da feature](../../../README.md) e o [fluxo de dados](../../../docs/CORE-ACCOUNT-DATA-FLOW.md).

Observa, decide, age e reobserva o usuário da Account (usuário humano do Zitadel) **numa só transação**, e grava o estado convergido e o `updated` no outbox. Substitui os antigos Observer, Reconciler e Executor, no modelo de controlador do Kubernetes (Informer + Workqueue). Decisão [`0096`](../../../../../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md).

## Ciclo

1. **Informer:** consome `desired.core.account.>` (Stream `DESIRED`, consumer `core-account-controller-desired-<instância>`) e enfileira o `resourceId` na Workqueue, só se ele pertencer à partição da instância (`hash(resourceId) mod count == index`).
2. **Reavaliação periódica:** enfileira todos os recursos `reconciliation = 'active'` da partição, com jitter, para detectar divergência externa.
3. **Workqueue:** deduplica por `resourceId` e repete com backoff exponencial quando o provedor falha de forma transitória ou o recurso ainda não convergiu.
4. **`reconcile(resourceId)`**, numa transação com a linha bloqueada (`FOR UPDATE`):
   - observa o Zitadel (usuário, autorizações nos projetos da plataforma e metadado de proteção);
   - decide com a função pura `decide(desired, observed)` (`domain/decision.py`): `create`, `update`, `delete` ou nada;
   - executa a ação idempotente nos drivers, se houver divergência, e **reobserva**;
   - calcula fase e conditions (`domain/convergence.py`), grava `observed`, `phase`, `conditions` e o `updated` no outbox; se a remoção convergiu, apaga o registro; se atingiu o limite de falhas, suspende a reconciliação e grava um `desired` suspenso no outbox.

## Regras do tipo

- Campos gerenciados: `lifecycle`, `platformAccess`, `platformPermissions` e `deletionProtection`; os dados pessoais (`givenName`, `familyName`, `email`) são imutáveis.
- Cria o usuário humano **sem senha**, na organização `register`: o Zitadel envia o e-mail de verificação, cuja página define a senha. A senha nunca passa pela plataforma.
- As permissões desejadas precisam estar contidas nas observadas; a mais não diverge.
- `absent` só com o `404` do usuário exato; qualquer outra falha de leitura é `unknown`, que nunca autoriza ação. O `observed` não traz dados pessoais.

## Estrutura

```text
src/core_account/controller/
  domain/      decisão pura e convergência (fase, conditions, prazos)
  drivers/     Zitadel: conexão, usuário, autorização e metadado
  engine/      Informer, Workqueue, observação, ação e o ciclo atômico
  store/       único código com SQL do Controller (ControllerSsotStore)
  settings.py
  main.py
```

## Privilégios

- **Banco:** papel `core_account_controller`: `SELECT`, `UPDATE` e `DELETE` em `core.account`; só `INSERT` no outbox. Não cria nem altera o `desired` de um pedido.
- **Zitadel:** conta `core-account-controller`, com `ORG_USER_CREATOR` e `ORG_OWNER_VIEWER` na organização `register` e `PROJECT_GRANT_OWNER` nos Grants dos projetos de permissões.

## Saúde

`GET /health/live`, `/health/ready` e `/health/startup` na porta `8000`.

## Configuração

Variáveis `CORE_ACCOUNT_CONTROLLER_<SEÇÃO>_<CAMPO>` e o `config.toml` da feature. Todos os campos estão em [`docs/CONFIGURATION.md`](../../../docs/CONFIGURATION.md).
