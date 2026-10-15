# sum-service-manager

Manager de `sum.service` (`sum-service-manager`), componente autocontido (decisão 0015). Implementa a
ligação de um serviço por usuário (decisão 0033).

**Estado:** implementado e testado contra o dev:

- `domain/`: regras puras da ligação e decisão de criar e desligar;
- `handlers/requested.py` e `store/ssot.py`: tratamento de `requested-create` e `requested-delete` com o SSOT;
- `transport/requested.py`: validação do `requested` (envelope e dados) e decisão ACK, TERM ou RETRY;
- `outbox/publication.py` e `transport/publisher.py`: publicação do outbox com trava de sessão, envelope
  estrito, `Nats-Msg-Id` igual ao `messageId`, e `published_at` só depois da confirmação.

- `main.py`: o processo do Manager. Valida a configuração (`SUM_SERVICE_MANAGER_*`), consome o
  `REQUESTED` pelo consumer durável `sum-service-manager-requested` (definição em `consumers/`), e
  expõe as probes de saúde. Verificado no dev: a mensagem `requested` vira ligação `present`, Operation
  `accepted` e `desired` pendente no outbox, e o processo encerra em um segundo com SIGTERM.

Ainda não há: o processo do Publisher (publica o outbox; é outro componente), `observed`, resultados de
ação, a declaração do consumer pela infraestrutura (hoje criado à mão no dev com a CLI `nats`), o
`Dockerfile` e a entrada no Compose. São as próximas fatias.

## Regras

- **Ligar:** `lifecycle = present`, com as roles do serviço copiadas do catálogo. O serviço precisa
  existir no catálogo, senão `ServiceNotAvailableError` (recusa permanente).
- **Desligar:** `lifecycle = absent`, `serviceRoles = []`. A ligação continua existindo, e os recursos do
  usuário no serviço não são apagados (decisão 0033).
- Todo `desired` é validado contra `schemas/sum/service/desired.v1.schema.json` antes de sair.

## Catálogo

`SUM_MANAGER_SERVICE_ROLES`, JSON com serviço → roles. Exemplo:

```json
{"ipm": ["ipm.organization.create", "ipm.organization.delete", "ipm.organization.get", "ipm.organization.list", "ipm.organization.update"]}
```

Um catálogo inválido para o componente: `parse_catalog` levanta `CatalogError` com o motivo.

## Contratos

`uv run datamodel-codegen` regera `src/sum_service_manager/contracts/generated.py` a partir de
`schemas/sum.service.index.json`. Não edite o arquivo gerado.

## Testes

```bash
uv run pytest                                  # unitários e de integração (sem banco: os de integração são pulados)
export SUM_MANAGER_TEST_DATABASE_URL=postgresql://sum_service_manager_login:...@127.0.0.1:5432/smarkee
export SUM_MANAGER_TEST_PUBLISHER_URL=postgresql://sum_service_publisher_login:...@127.0.0.1:5432/smarkee
export SUM_MANAGER_TEST_MAINTENANCE_URL=postgresql://sum_service_maintenance_login:...@127.0.0.1:5432/smarkee
export SUM_MANAGER_TEST_NATS_URL=nats://127.0.0.1:4222 SUM_MANAGER_TEST_NATS_USER=smarkee SUM_MANAGER_TEST_NATS_PASSWORD=...
uv run pytest tests/integration                # usa o banco de dev já migrado (0001 e 0002)
uv run ruff check . && uv run pyright
```

Os testes de integração rodam em transação com `rollback`, e a ligação do teste de outbox é
limpa ao final. As senhas de dev são iguais ao nome do papel (`bootstrap/sum.sql`); não as use fora do dev.
