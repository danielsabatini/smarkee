# sum-service-executor

Executor de `sum.service` (`sum-service-executor`), componente autocontido (decisões 0015, 0032 e 0033).
É o único componente que concede roles de serviço (`ipm.*`) no Zitadel.

## O que faz

- `provider/zitadel.py`: o único cliente de escrita do Zitadel do SUM. Autentica com a conta de serviço
  por assertion JWT e usa a API v2 de autorizações (decisão 0029). Só conhece os projetos configurados em
  `SUM_SERVICE_EXECUTOR_ZITADEL_PROJECT_IDS` (hoje `ipm`).
- `actions/service_roles.py`: `enable` (garante as roles, sem apagar as outras) e `disable` (tira só as
  roles do serviço; remove a autorização quando não sobra nenhuma). Ambas são idempotentes.

## Isolamento (decisão 0032)

A conta `sum-service-executor` tem `PROJECT_GRANT_OWNER` só no Project Grant de `roles-ipm`. O Zitadel
recusa a concessão de qualquer outra role, e o provider recusa módulos sem projeto configurado antes de
chamar o Zitadel.

Verificado no Zitadel de dev (2026-10-15) com o provider real e uma conta temporária com esse papel:
ligar criou a autorização no `roles-ipm`; repetir não duplicou; `core.account.get` no `roles-core` foi recusado
pelo Zitadel (`Unauthorized`); `ipm.organization.admin` no `roles-ipm` foi recusado (`Rejected`); desligar
removeu a autorização. A conta e o usuário de teste foram removidos.

## Processo

`engine/executor.py` e `main.py`: consomem as partições do `ACTION` (um consumer e um laço por partição, 0 a 3, no mesmo
processo; decisão 0018). Cada `action` passa por, nesta ordem:

1. **Validação da mensagem:** emissor `reconciler`, tipo `action`, módulo e tipo do recurso, versão `MAJOR` e `actionId`.
   Fora disso, é descartada e registrada. O `desired` lido do transporte precisa ser do emissor `manager`.
2. **Idempotência:** um `actionId` com `completed` (ou `failed` permanente) já registrado não é executado de novo; o resultado
   é republicado com o mesmo `Nats-Msg-Id`.
3. **Revalidação** (`domain/revalidation.py`, `docs/RESOURCE-CONTROL-SECURITY.md` §7), contra o último `desired` (leitura
   direta do Stream `DESIRED`): sem `desired` ou geração diferente é `failed` `StaleAction`; `reconciliation = suspended` é
   `failed` `Suspended`; `lifecycle` ausente ou inválido, ou operação fora de `update`, é `failed` `Rejected`. Todas
   permanentes. Não existe `lifecycle` padrão: sem ele nada é concedido.

Depois concede ou revoga as roles (desligar usa as do catálogo, porque o `desired` vem vazio) e publica `completed` ou
`failed`. Erro transitório do Zitadel volta à fila; recusa permanente vira `failed` com o motivo.

No ar no dev (Compose), no ciclo de ligar e desligar e com o Executor parado durante um pedido (`../tests/e2e`).

## Configuração

`SUM_SERVICE_EXECUTOR_<SEÇÃO>_<CAMPO>`. Obrigatórias: `NATS_PASSWORD`, `ZITADEL_REGISTER_ORGANIZATION_ID`,
`ZITADEL_PROJECT_IDS` e `CATALOG_ROLES`. A chave da conta `sum-service-executor` é montada do volume `identity-bootstrap`
(`/run/secrets/zitadel-key.json`); a rotação está em `infrastructure/dev/README.md`. `PARTITION_COUNT` (padrão 4) é o número
de partições do `ACTION`, definido no bootstrap do broker.

## Testes

```bash
uv run pytest     # ligar e desligar, provider com Zitadel simulado, motor (emissor, revalidação, idempotência), saúde e logging
uv run ruff check . && uv run pyright
```
