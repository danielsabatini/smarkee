# sum-service-manager

Manager de `sum.service` (`sum-service-manager`), um dos seis papéis da imagem única `sum-service` (decisões 0015 e 0063), com processo e contêiner próprios. Veja o [README da feature](../../../README.md). Implementa a
ligação de um serviço por usuário (decisão 0033). É o único escritor do SSOT (`sum.service`,
`sum.service_operation`, `sum.service_action_result`) e do outbox.

## O que faz

- `domain/`: regras puras (catálogo, decisão de criar e desligar, política de convergência da ligação em `service.py`).
  `convergence.py`, `errors.py` e `outcome.py` vêm do template (perfil `manager-handlers`, decisão 0080).
- `handlers/requested.py` e `store/ssot.py`: tratamento de `requested-create` e `requested-delete` no SSOT, numa
  transação com o outbox.
- `handlers/{observed,result,envelope,publishing}.py` (do template) e `store/state.py`: aplicam `observed` e os
  resultados como nos outros tipos (decisão 0080). A geração só é confirmada (`observed_generation`) por uma leitura
  feita depois dela; a Operation conclui nessa confirmação, e cada mudança de fase sai como `updated`. Falhas contam uma
  vez por `actionId` e suspendem a reconciliação no `failureLimit`; a condition `Progressing` vai a
  `ProgressDeadlineExceeded` (fase `Failed`) no prazo esgotado. A ligação desfeita não é apagada
  (`SERVICE.removes_absent = False`).
- `transport/requested.py` e `transport/state.py`: validação (envelope tolerante, versão `MAJOR`, módulo, emissor e
  dados) e decisão ACK, TERM ou RETRY.
- `main.py`: valida a configuração (`SUM_SERVICE_MANAGER_*`), consome `REQUESTED`, `OBSERVED`, `RESULT` e o `UPDATED` de `core.account` (remoção da conta, decisão 0044) pelos consumers
  duráveis `sum-service-manager-{requested,observed,completed,failed,account-removed}` (manifestos em `consumers/`) e expõe as probes de
  saúde.

O Manager só insere no outbox. A publicação do outbox no NATS é do Publisher ([`../publisher`](../publisher/README.md)).

## Regras

- **Ligar:** `lifecycle = present`, com as roles do serviço copiadas do catálogo. O serviço precisa existir no catálogo;
  senão a recusa é `service_unavailable`. Já existe ligação ativa do dono para o serviço: `already_exists`.
- **Desligar:** `lifecycle = absent`, `servicePermissions = []`, geração e versão + 1. Sem ligação ativa: `not_found`; versão
  diferente da lida: `conflict`. A linha continua existindo, e os recursos do usuário no serviço não são apagados
  (decisão 0033).
- Todo `desired` é validado contra `schemas/sum/service/desired.v1.schema.json` antes de sair.
- Mensagem de outra versão `MAJOR`, de outro módulo ou emissor, ou fora do contrato, é descartada (`TERM`).

## Catálogo

`SUM_SERVICE_MANAGER_CATALOG_PERMISSIONS`, JSON com serviço → permissões. Exemplo:

```json
{"ipm": ["ipm.organization.create", "ipm.organization.delete", "ipm.organization.get", "ipm.organization.list", "ipm.organization.update",
         "ipm.user.bind", "ipm.user.create", "ipm.user.delete", "ipm.user.get", "ipm.user.list", "ipm.user.update",
         "ipm.group.bind", "ipm.group.create", "ipm.group.delete", "ipm.group.get", "ipm.group.list", "ipm.group.update",
         "ipm.role.bind", "ipm.role.create", "ipm.role.delete", "ipm.role.get", "ipm.role.list", "ipm.role.update",
         "ipm.serviceaccount.bind", "ipm.serviceaccount.create", "ipm.serviceaccount.delete", "ipm.serviceaccount.get", "ipm.serviceaccount.list", "ipm.serviceaccount.update"]}
```

As permissões `ipm.user.*`, `ipm.group.*`, `ipm.role.*` e `ipm.serviceaccount.*` dão ao root (o dono da Organization) a gestão dos usuários, grupos, roles `custom` e service accounts dela (decisões 0077, 0088, 0092 e 0094).

O catálogo existe **só no Manager** (decisão 0079). O `desired` leva as permissões que o usuário deve ter (`servicePermissions`) e as que a ligação controla (`managedPermissions`: as do catálogo mais as que saíram dele), e o Observer e o Executor leem só o `desired`. Na partida, o Manager faz o **rollout** (`handlers/catalog_rollout.py`): cada ligação cujo `desired` difere do catálogo de agora ganha uma geração nova, com uma Operation `update` de `system:catalog`, e o loop aplica a mudança, inclusive para quem ligou antes. Repetir não grava nada (a linha é bloqueada e comparada). Um serviço que saiu do catálogo não é alterado.

Um catálogo inválido: `parse_catalog` levanta `CatalogError` com o motivo e o processo não sobe.

## Contratos

`uv run datamodel-codegen` regera `src/sum_service/common/contracts/generated.py` a partir de
`schemas/sum.service.index.json`. Não edite o arquivo gerado: o teste de contrato falha se ele divergir.

## Testes

```bash
uv run pytest                                  # unitários, de contrato e de integração (os de integração são pulados sem as variáveis)
export SUM_MANAGER_TEST_DATABASE_URL=postgresql://sum_service_manager_login:...@127.0.0.1:5432/smarkee
export SUM_MANAGER_TEST_MAINTENANCE_URL=postgresql://sum_service_maintenance_login:...@127.0.0.1:5432/smarkee
uv run pytest tests/integration                # usa o banco de dev já migrado
uv run ruff check . && uv run pyright
```

Os testes de integração limpam o que criaram (a manutenção apaga o outbox e as Operations; o Manager, a ligação). As
senhas de dev são iguais ao nome do papel (`bootstrap/sum.sql`); não as use fora do dev.
