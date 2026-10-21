# ipm-user-executor

Executor de `ipm.user` (`ipm-user-executor`), um dos seis papéis da imagem única `ipm-user` (decisão 0063), com processo e contêiner próprios. Veja o [README da feature](../../../README.md).

Única identidade com escrita do usuário no Zitadel (conta `ipm-user-executor`, decisão 0077): `ORG_USER_CREATOR` em cada organização de cliente (cria e remove usuários, sem conceder roles) e `PROJECT_GRANT_OWNER` no Project Grant de `roles-ipm` para ela (concede só as roles do Grant). Os dois papéis são dados pelo operador a cada organização. Consome a `action` do Reconciler, **revalida** contra o `desired` vigente (geração, coerência da operação, reconciliação ativa), confere o desfecho já registrado do `actionId` por Direct Get (idempotência) e executa, compondo os drivers de `drivers/`:

- `create`: cria o usuário humano **sem senha** na organização do `desired` (`organizationId`), com o `resourceId` como ID e o e-mail como nome de login; o Zitadel envia o e-mail de verificação, que também define a senha. Usuário já existente com o mesmo ID leva a lê-lo: mesmo e-mail e mesma organização é sucesso idempotente; senão, falha permanente (`Rejected`);
- em `create` e `update`, deixa a autorização em `roles-ipm` com **exatamente** as roles do `desired` (cria, atualiza ou remove) e grava o metadado `deletionProtection` (decisão 0074; repetir é idempotente). Uma role fora do Project Grant é recusada pelo Zitadel (`Rejected`);
- `update`: confere que o usuário existe e é da organização do `desired`;
- `delete`: remove o usuário (ausente é sucesso).

Publica `completed` ou `failed {reason, retryable}`; o retry é do Reconciler.

## Partições (decisão 0018)

O Stream `ACTION` é particionado por `resourceId` (4 partições). O Executor roda um laço e um consumer por partição (`ipm-user-executor-action-p<N>`, `max_ack_pending=1`): uma `action` por vez em cada recurso, até 4 recursos em paralelo. `IPM_USER_EXECUTOR_PARTITION_COUNT` deve ser igual ao do bootstrap do messaging. Os manifestos estão em `consumers/`.

## Estrutura (decisão 0017)

```text
src/ipm_user/executor/
  domain/      revalidação da action, erros e tipos do provedor
  actions/     cada operação, compondo os drivers (idempotente)
  drivers/     escrita no Zitadel, um por sub-recurso (user.py, authorization.py e metadata.py; decisão 0073)
  provider/    conexão de escrita com o Zitadel (HTTP, JWT da conta de serviço)
  engine/      fluxo de cada action e publicação do resultado
  transport/   consumers por partição, Direct Get e publicação no NATS
  main.py
```

`tests/common/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Configuração

Variáveis `IPM_USER_EXECUTOR_<SEÇÃO>_<CAMPO>` e o `config.toml` da feature. Obrigatórias, sem default: `IPM_USER_EXECUTOR_MESSAGING_PASSWORD` e `IPM_USER_EXECUTOR_IDENTITY_PROJECT_ID` (o projeto `roles-ipm`, o único em que concede roles). A chave da conta de serviço é um arquivo montado (`/run/secrets/zitadel-key.json`), só desta conta.

## Desenvolvimento

```bash
# Na raiz da feature (features/ipm/user), que é o projeto único:
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/executor
```
