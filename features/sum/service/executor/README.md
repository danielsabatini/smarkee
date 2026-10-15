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
ligar criou a autorização no `roles-ipm`; repetir não duplicou; `core.user.get` no `roles-core` foi recusado
pelo Zitadel (`Unauthorized`); `ipm.organization.admin` no `roles-ipm` foi recusado (`Rejected`); desligar
removeu a autorização. A conta e o usuário de teste foram removidos.

## Processo

`engine/executor.py` e `main.py`: consomem as partições do `ACTION` (um laço por partição, 0 a 3, no mesmo processo; decisão 0018).
Cada `action` é revalidada contra o `desired` atual (leitura direta do Stream `DESIRED`): geração diferente é
ação velha e não é executada. Concede ou revoga as roles (desligar usa as do catálogo, porque o `desired` vem
vazio) e publica `completed` ou `failed`. Erro transitório volta à fila; erro permanente vira `failed`.

Verificado no dev, com quatro processos (uma por partição), no ciclo de ligar e desligar.

## Não está pronto

- A conta `sum-service-executor` definitiva no Zitadel de dev e sua chave no volume `identity-bootstrap`. Na
  verificação usou-se uma conta temporária, com o mesmo papel, criada e removida.

## Testes

```bash
uv run pytest     # unitários: lógica de ligar e desligar, e provider com Zitadel simulado
uv run ruff check . && uv run pyright
```
