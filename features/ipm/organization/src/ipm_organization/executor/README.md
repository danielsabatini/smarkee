# ipm-organization-executor

Executor de `ipm.organization` (`ipm-organization-executor`), um dos seis papéis da imagem única `ipm-organization` (decisão 0063), com processo e contêiner próprios. Veja o [README da feature](../../../README.md).

Única identidade com escrita da Organization no Zitadel (conta `ipm-organization-executor`, papel de instância `IAM_ORG_MANAGER`). Escreve a organização e o **preparo dela para os usuários** (`.decisions/0081`); não cria usuários nem autoriza o dono. Consome a `action` do Reconciler, **revalida** contra o `desired` vigente (geração, coerência da operação, reconciliação ativa), confere o desfecho já registrado do `actionId` por Direct Get (idempotência) e executa, pela API v2 de organizações (`zitadel.org.v2.OrganizationService`):

- `create`: cria a organização com o `resourceId` como ID e o `name` do `desired`. Um `409` (ID ou nome já usado) leva a ler a organização pelo ID: se existe com o nome esperado, é sucesso idempotente; senão, falha permanente (`Rejected`). Depois, deixa a organização ativa ou desativada conforme `platformAccess`;
- em `create` e `update`, grava o metadado `deletionProtection` da organização com o valor do `desired` (decisão 0074; repetir é idempotente);
- `update`: renomeia quando o nome difere e ativa (`granted`) ou desativa (`revoked`) quando o estado difere. Só chama o Zitadel quando há diferença; o "já feito" do Zitadel (nome igual, já ativa, já desativada) também conta como sucesso;
- em `create` e `update`, com `userAccess` no `desired` e `platformAccess = granted`, prepara a organização para os usuários (`drivers/user_access.py`, decisão 0081): cria o Project Grant de `roles-ipm` (`409` conta como já criado) ou o ajusta para exatamente `grantPermissions`; depois dá às contas do `ipm/user` as permissões que faltam (`ORG_USER_CREATOR` e `ORG_OWNER_VIEWER` na organização, `PROJECT_GRANT_OWNER` no Grant), com a união das que elas já têm, porque `UpdateAdministrator` substitui o conjunto;
- `delete`: remove a organização (ausente é sucesso; o Zitadel leva o Grant e os papéis junto).

Publica `completed` ou `failed {reason, retryable}`; o retry é do Reconciler.

## Partições (decisão 0018)

O Stream `ACTION` é particionado por `resourceId` (4 partições). O Executor roda um laço e um consumer por partição (`ipm-organization-executor-action-p<N>`, `max_ack_pending=1`): uma `action` por vez em cada recurso, até 4 recursos em paralelo. `IPM_ORGANIZATION_EXECUTOR_PARTITION_COUNT` deve ser igual ao do bootstrap do messaging. Os manifestos estão em `consumers/`.

## Estrutura (decisão 0017)

```text
src/ipm_organization/executor/
  domain/      revalidação da action, erros e tipos do provedor
  actions/     cada operação, compondo os drivers (idempotente)
  drivers/     escrita no Zitadel, um por sub-recurso (organization.py; decisão 0073)
  provider/    conexão de escrita com o Zitadel (HTTP, JWT da conta de serviço)
  engine/      fluxo de cada action e publicação do resultado
  transport/   consumers por partição, Direct Get e publicação no NATS
  main.py
```

`tests/common/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Configuração

Variáveis `IPM_ORGANIZATION_EXECUTOR_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatória, sem default: `IPM_ORGANIZATION_EXECUTOR_MESSAGING_PASSWORD`. A chave da conta de serviço é um arquivo montado (`/run/secrets/zitadel-key.json`), só desta conta.

## Desenvolvimento

```bash
# Na raiz da feature (features/ipm/organization), que é o projeto único:
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/executor
```
