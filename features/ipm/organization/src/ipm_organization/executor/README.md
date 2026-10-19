# ipm-organization-executor

Executor de `ipm.organization` (`ipm-organization-executor`), um dos seis papéis da imagem única `ipm-organization` (decisão 0063), com processo e contêiner próprios. Veja o [README da feature](../../../README.md).

Única identidade com escrita da Organization no Zitadel (conta `ipm-organization-executor`, papel de instância `IAM_ORG_MANAGER`). Escreve **só a organização**: não cria usuários, não autoriza o dono e não cria Project Grant (`.decisions/0038`). Consome a `action` do Reconciler, **revalida** contra o `desired` vigente (geração, coerência da operação, reconciliação ativa), confere o desfecho já registrado do `actionId` por Direct Get (idempotência) e executa, pela API v2 de organizações (`zitadel.org.v2.OrganizationService`):

- `create`: cria a organização com o `resourceId` como ID e o `name` do `desired`. Um `409` (ID ou nome já usado) leva a ler a organização pelo ID: se existe com o nome esperado, é sucesso idempotente; senão, falha permanente (`Rejected`). Depois, deixa a organização ativa ou desativada conforme `platformAccess`;
- `update`: renomeia quando o nome difere e ativa (`granted`) ou desativa (`revoked`) quando o estado difere. Só chama o Zitadel quando há diferença; o "já feito" do Zitadel (nome igual, já ativa, já desativada) também conta como sucesso;
- `delete`: remove a organização (ausente é sucesso).

Publica `completed` ou `failed {reason, retryable}`; o retry é do Reconciler.

## Partições (decisão 0018)

O Stream `ACTION` é particionado por `resourceId` (4 partições). O Executor roda um laço e um consumer por partição (`ipm-organization-executor-action-p<N>`, `max_ack_pending=1`): uma `action` por vez em cada recurso, até 4 recursos em paralelo. `IPM_ORGANIZATION_EXECUTOR_PARTITION_COUNT` deve ser igual ao do bootstrap do broker. Os manifestos estão em `consumers/`.

## Estrutura (decisão 0017)

```text
src/ipm_organization/executor/
  domain/      revalidação da action, erros e tipos do provedor
  actions/     execução de cada operação sobre o provedor (idempotente)
  provider/    escritor do Zitadel (HTTP, JWT da conta de serviço)
  engine/      fluxo de cada action e publicação do resultado
  transport/   consumers por partição, Direct Get e publicação no NATS
  http/        servidor de saúde (/health/live, /health/ready, /health/startup)
  main.py
```

`tests/common/unit/test_domain_isolation.py` falha se o `domain/` importar um adaptador.

## Configuração

Variáveis `IPM_ORGANIZATION_EXECUTOR_<SEÇÃO>_<CAMPO>`, sem arquivo de configuração. Obrigatória, sem default: `IPM_ORGANIZATION_EXECUTOR_NATS_PASSWORD`. A chave da conta de serviço é um arquivo montado (`/run/secrets/zitadel-key.json`), só desta conta.

## Desenvolvimento

```bash
# Na raiz da feature (features/ipm/organization), que é o projeto único:
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest tests/executor
```
