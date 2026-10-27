# ipm-permission-controller

Controller de `ipm.permission` (`ipm-permission-controller`), um dos três papéis da imagem única `ipm-permission` (decisões 0063 e 0096), com processo e contêiner próprios. Veja o [README da feature](../../../README.md).

Observa, decide, age e reobserva a role de projeto da Permission **numa só transação** e grava o estado convergido e o `updated` no outbox. Substitui os antigos Observer, Reconciler e Executor, no modelo de controlador do Kubernetes (Informer + Workqueue). Decisão [`0096`](../../../../../../.decisions/0096-unificacao-do-loop-de-reconciliacao-no-controller.md).

## Ciclo

1. **Informer:** consome `manager.desired.ipm.permission.>` (Stream `DESIRED`, consumer `ipm-permission-controller-desired-<instância>`) e enfileira o `resourceId` na Workqueue, só se ele pertencer à partição da instância.
2. **Reavaliação periódica:** enfileira todos os recursos `reconciliation = 'active'` da partição, com jitter, para detectar divergência externa.
3. **Workqueue:** deduplica por `resourceId` e repete com backoff exponencial quando o provedor falha de forma transitória ou o recurso ainda não convergiu.
4. **`reconcile(resourceId)`**, numa transação com a linha bloqueada (`FOR UPDATE`):
   - observa a role no Zitadel (`ListProjectRoles`);
   - decide com a função pura `decide(desired, observed)` (`domain/decision.py`): `create`, `update`, `delete` ou nada;
   - executa a ação idempotente no driver, se houver divergência, e **reobserva**;
   - calcula fase e conditions (`domain/convergence.py`), grava `observed`, `phase`, `conditions` e o `updated` no outbox; se a remoção convergiu, apaga o registro; se atingiu o limite de falhas, suspende a reconciliação e grava um `desired` suspenso no outbox.

A idempotência da ação vem das operações idempotentes do driver (criar uma role existente a atualiza; remover uma role ausente conclui) e do ciclo atômico.

## Regras do tipo

- Campos comparados: `lifecycle`, `name` (a chave da role), `description` (o `displayName`) e `group` (o `<módulo>` da chave).
- Cada Permission `<módulo>.<tipo>.<ação>` é uma role do projeto `roles-<módulo>` na organização `core`; a ação `admin` fica em `roles-operator`.
- `absent` só quando a consulta ao projeto teve sucesso e a role não existe; qualquer falha de leitura é `unknown`, que nunca autoriza ação.
- `grantable` e `deletionProtection` são dados da plataforma: não existem no Zitadel. Alterações em `grantable` propagam-se pelo `desired` aos Project Grants das Organizations (`ipm.organization`).

## Estrutura

```text
src/ipm_permission/controller/
  domain/      decisão pura e convergência (fase, conditions, prazos)
  drivers/     Zitadel: conexão e roles de projeto
  engine/      Informer, Workqueue, observação, ação e o ciclo atômico
  store/       único código com SQL do Controller (ControllerSsotStore)
  settings.py
  main.py
```

A dependência vai em um sentido só; `tests/common/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Privilégios

- **Banco:** papel `ipm_permission_controller` (migração `0004`): `SELECT`, `UPDATE` e `DELETE` em `ipm.permission`; só `INSERT` no outbox. Não cria nem altera o `desired` de um pedido.
- **Zitadel:** conta `ipm-permission-controller`, com `PROJECT_OWNER` nos projetos `roles-<módulo>` e em `roles-operator`. Criação manual pelo operador (lacuna declarada em `docs/platform/IMPLEMENTATION-STATUS.md`).

## Saúde

`GET /health/live`, `/health/ready` e `/health/startup` na porta `8000`.

## Configuração

Variáveis de ambiente `IPM_PERMISSION_CONTROLLER_<SEÇÃO>_<CAMPO>` e o `config.toml` da feature. Obrigatórias, sem default: `MESSAGING_URL`, `MESSAGING_USER`, `MESSAGING_PASSWORD`, `DATABASE_HOST`, `DATABASE_PORT`, `DATABASE_NAME`, `DATABASE_USER` e `DATABASE_PASSWORD`. Todos os campos estão em [`docs/CONFIGURATION.md`](../../../docs/CONFIGURATION.md).

## Desenvolvimento

```bash
# Na raiz da feature (features/ipm/permission), que é o projeto único:
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/controller  # os testes de integração exigem a stack de dev e são pulados sem ela
```

Imagem: o `Dockerfile` da feature (imagem única; este papel roda com `command: ipm-permission-controller`).
