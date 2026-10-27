# ipm-user-controller

Controller de `ipm.user` (`ipm-user-controller`), um dos quatro papéis da imagem única `ipm-user` (decisões 0063 e 0096), com processo e contêiner próprios. Veja o [README da feature](../../../README.md) e o [fluxo de dados](../../../docs/IPM-USER-DATA-FLOW.md) (seção 4).

Observa, decide, age e reobserva o usuário da Organization (usuário humano do Zitadel) **numa só transação**, e grava o estado convergido e o `updated` no outbox. Substitui os antigos Observer, Reconciler e Executor, no modelo de controlador do Kubernetes (Informer + Workqueue). Decisão [`0096`](../../../../../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md).

## Ciclo

1. **Informer:** consome `manager.desired.ipm.user.>` (Stream `DESIRED`, consumer `ipm-user-controller-desired-<instância>`) e enfileira o `resourceId` na Workqueue, só se ele pertencer à partição da instância (`hash(resourceId) mod count == index`).
2. **Reavaliação periódica:** enfileira todos os recursos `reconciliation = 'active'` da partição, com jitter, para detectar divergência externa.
3. **Workqueue:** deduplica por `resourceId` e repete com backoff exponencial quando o provedor falha de forma transitória ou o recurso ainda não convergiu.
4. **`reconcile(resourceId)`**, numa transação com a linha bloqueada (`FOR UPDATE`):
   - observa o Zitadel (usuário, autorizações em `roles-ipm` e metadados);
   - decide com a função pura `decide(desired, observed)` (`domain/decision.py`): `create`, `update`, `delete` ou nada;
   - executa a ação idempotente nos drivers, se houver divergência, e **reobserva**;
   - calcula fase e conditions (`domain/convergence.py`), grava `observed`, `phase`, `conditions`, as Operations e o `updated` no outbox; se a remoção convergiu, apaga o registro; se atingiu o limite de falhas, suspende a reconciliação e grava um `desired` suspenso no outbox.

A idempotência da ação vem das operações idempotentes dos drivers e do ciclo atômico; não há registro por `actionId` (a tabela `ipm.user_action_result` foi removida pela migração `0005`).

## Regras do tipo

- Campos gerenciados: `lifecycle`, `permissions` e `deletionProtection`; a Organization e os dados pessoais (`givenName`, `familyName`, `email`) são imutáveis.
- Cria o usuário humano **sem senha**: o Zitadel envia o e-mail de verificação, cuja página define a senha. A senha nunca passa pela plataforma.
- As autorizações em `roles-ipm` ficam com **exatamente** as permissões do `desired`; o Project Grant é o teto.
- `absent` só com o `404` do usuário exato; qualquer outra falha de leitura é `unknown`, que nunca autoriza ação. O `observed` não traz dados pessoais.

## Estrutura

```text
src/ipm_user/controller/
  domain/      decisão pura e convergência (fase, conditions, prazos)
  drivers/     Zitadel: conexão, usuário, autorização e metadados
  engine/      Informer, Workqueue, observação, ação e o ciclo atômico
  store/       único código com SQL do Controller (ControllerSsotStore)
  settings.py
  main.py
```

A dependência vai em um sentido só; `tests/common/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Privilégios

- **Banco:** papel `ipm_user_controller` (migração `0004`): `SELECT`, `UPDATE` e `DELETE` em `ipm.user`; `SELECT` e `UPDATE` em `ipm.user_operation`; só `INSERT` no outbox. Não cria nem altera o `desired` de um pedido.
- **Zitadel:** conta `ipm-user-controller`, com `ORG_USER_CREATOR` e `ORG_OWNER_VIEWER` em cada organização de cliente e `PROJECT_GRANT_OWNER` no Grant de `roles-ipm` dela.

## Saúde

`GET /health/live`, `/health/ready` e `/health/startup` na porta `8000`.

## Configuração

Variáveis de ambiente `IPM_USER_CONTROLLER_<SEÇÃO>_<CAMPO>` e o `config.toml` da feature. Obrigatórias, sem default: `IPM_USER_CONTROLLER_DATABASE_PASSWORD`, `IPM_USER_CONTROLLER_MESSAGING_PASSWORD` e `IPM_USER_CONTROLLER_IDENTITY_PROJECT_ID`. Todos os campos estão em [`docs/CONFIGURATION.md`](../../../docs/CONFIGURATION.md).

## Desenvolvimento

```bash
# Na raiz da feature (features/ipm/user), que é o projeto único:
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/controller  # os testes de integração exigem a stack de dev e são pulados sem ela
```

Imagem: o `Dockerfile` da feature (imagem única; este papel roda com `command: ipm-user-controller`).
