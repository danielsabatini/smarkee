# sum-service-manager

Manager de `sum.service` (`sum-service-manager`), um dos seis papéis da imagem única `sum-service` (decisões 0015 e 0063), com processo e contêiner próprios. Veja o [README da feature](../../../README.md). Implementa a
ligação de um serviço por usuário (decisão 0033). É o único escritor do SSOT (`sum.service`,
`sum.service_operation`, `sum.service_action_result`) e do outbox.

## O que faz

- `domain/`: regras puras (catálogo, decisão de criar e desligar, convergência da fase).
- `handlers/requested.py` e `store/ssot.py`: tratamento de `requested-create` e `requested-delete` no SSOT, numa
  transação com o outbox.
- `handlers/state.py`: aplica `observed` (fase `Ready` ou `Reconciling`, ignorando o mais antigo que o último aplicado) e
  os resultados `completed` e `failed` (uma vez por `actionId`; `failed` marca a fase `Failed` da geração). Acompanha as
  Operations: `in_progress` na reconciliação e `completed` quando a fase chega a `Ready`.
- `transport/requested.py` e `transport/state.py`: validação (envelope tolerante, versão `MAJOR`, módulo, emissor e
  dados) e decisão ACK, TERM ou RETRY.
- `main.py`: valida a configuração (`SUM_SERVICE_MANAGER_*`), consome `REQUESTED`, `OBSERVED`, `RESULT` e o `UPDATED` de `core.account` (remoção da conta, decisão 0044) pelos consumers
  duráveis `sum-service-manager-{requested,observed,completed,failed,account-removed}` (manifestos em `consumers/`) e expõe as probes de
  saúde.

O Manager só insere no outbox. A publicação do outbox no NATS é do Publisher ([`../publisher`](../publisher/README.md)).

## Regras

- **Ligar:** `lifecycle = present`, com as roles do serviço copiadas do catálogo. O serviço precisa existir no catálogo;
  senão a recusa é `service_unavailable`. Já existe ligação ativa do dono para o serviço: `already_exists`.
- **Desligar:** `lifecycle = absent`, `serviceRoles = []`, geração e versão + 1. Sem ligação ativa: `not_found`; versão
  diferente da lida: `conflict`. A linha continua existindo, e os recursos do usuário no serviço não são apagados
  (decisão 0033).
- Todo `desired` é validado contra `schemas/sum/service/desired.v1.schema.json` antes de sair.
- Mensagem de outra versão `MAJOR`, de outro módulo ou emissor, ou fora do contrato, é descartada (`TERM`).

## Catálogo

`SUM_SERVICE_MANAGER_CATALOG_ROLES`, JSON com serviço → roles. Exemplo:

```json
{"ipm": ["ipm.organization.create", "ipm.organization.delete", "ipm.organization.get", "ipm.organization.list", "ipm.organization.update",
         "ipm.user.bind", "ipm.user.create", "ipm.user.delete", "ipm.user.get", "ipm.user.list", "ipm.user.update"]}
```

As roles `ipm.user.*` dão ao root (o dono da Organization) a gestão dos usuários dela (decisão 0077).

O catálogo existe **só no Manager** (decisão 0079). O `desired` leva as roles que o usuário deve ter (`serviceRoles`) e as que a ligação controla (`managedRoles`: as do catálogo mais as que saíram dele), e o Observer e o Executor leem só o `desired`. Na partida, o Manager faz o **rollout** (`handlers/catalog_rollout.py`): cada ligação cujo `desired` difere do catálogo de agora ganha uma geração nova, com uma Operation `update` de `system:catalog`, e o loop aplica a mudança, inclusive para quem ligou antes. Repetir não grava nada (a linha é bloqueada e comparada). Um serviço que saiu do catálogo não é alterado.

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
