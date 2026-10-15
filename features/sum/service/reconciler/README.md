# sum-service-reconciler

Reconciler de `sum.service` (`sum-service-reconciler`), componente autocontido (decisões 0015 e 0033).
Compara o `desired` (a ligação pedida) com o `observed` (as roles que o usuário tem) e publica a `action`
quando há divergência.

## Estado

- `domain/decision.py`: a decisão pura, com as guardas do loop.
- `engine/reconciler.py`: o motor. Recebe `desired`, `observed` e resultados (`completed` e `failed`), mantém
  o estado de cada recurso, decide e publica a `action` em `reconciler.action.sum.service.<resourceId>.<operação>`,
  com `Nats-Msg-Id` igual ao `actionId`. Reavalia os recursos periodicamente (validade e prazos dependem do tempo).
- `main.py`: o processo. Consome os consumers `sum-service-reconciler-{desired,observed,completed,failed}`
  (declarados por `sum-service-consumer`), com ACK depois do motor.
- Verificado no dev, com o processo no host, no ciclo de ligar e desligar com os outros componentes. Ver
  `docs/SUM-SERVICE-DATA-FLOW.md`.

Limite conhecido: o estado é mantido em memória. Ao reiniciar, o Reconciler só vê as mensagens novas: a
reconstrução a partir do último `desired` e `observed` de cada recurso não foi implementada.

## Decisão

- **Ligação ativa** (`lifecycle = present`): o usuário precisa ter as roles do serviço. Roles a mais não são
  divergência (`Drift`).
- **Ligação desligada** (`lifecycle = absent`): nenhuma role do serviço pode estar presente
  (`RolesRemovalRequested`).

Guardas do loop (`docs/RESOURCE-CONTROL-SECURITY.md` §7 e §8): sem os dois estados, não decide; `desired`
suspenso não decide; `observed` `unknown` ou vencido não decide; enquanto a observação causada por um
resultado não chega, não decide; ação pendente da mesma geração não é reemitida antes do prazo; após falha,
espera o backoff.

## Configuração

`SUM_SERVICE_RECONCILER_<SEÇÃO>_<CAMPO>`. Obrigatória: `NATS_PASSWORD`. Os parâmetros do loop estão em
`settings.py` e são os de `schemas/sum/service/desired.v1.schema.json`.

## Testes

```bash
uv run pytest           # decisão e motor (fluxo completo com publicador simulado)
uv run ruff check . && uv run pyright
```
