# sum-service-reconciler

Reconciler de `sum.service` (`sum-service-reconciler`), um dos seis papéis da imagem única `sum-service` (decisão 0063; decisões 0015 e 0033), com processo e contêiner próprios. Veja o [README da feature](../../../README.md).
Compara o `desired` (a ligação pedida) com o `observed` (as roles que o usuário tem) e publica a `action`
quando há divergência.

## Estado

- `domain/decision.py`: a decisão pura, com as guardas do loop.
- `engine/reconciler.py`: o motor. Recebe `desired`, `observed` e resultados (`completed` e `failed`), mantém
  o estado de cada recurso, decide e publica a `action` em `reconciler.action.sum.service.<resourceId>.<operação>`,
  com `Nats-Msg-Id` igual ao `actionId`. Reavalia os recursos periodicamente (validade e prazos dependem do tempo).
- `transport/streams.py`: os consumers de estado da instância, a publicação da `action` e a reavaliação periódica, com jitter.
- `main.py`: o processo. Cria um consumer por Stream (`DESIRED`, `OBSERVED` e `RESULT`) com nome único por execução,
  `DeliverLastPerSubject` e `inactive_threshold`, confirma (ACK) depois do motor e devolve à fila (`nak`) a mensagem
  que o motor não conseguiu processar. Não há manifesto de consumer: a instância cria os próprios.
- No ar no dev (Compose), no ciclo de ligar e desligar com os outros componentes, inclusive reiniciando o Reconciler no meio
  de uma ligação pendente (`../../../tests/e2e`). Ver `docs/SUM-SERVICE-DATA-FLOW.md`.

O estado em memória é um cache descartável (`docs/RESOURCE-CONTROL-LOOP.md` §3.8): ao iniciar, o consumer da instância
entrega o último `desired`, `observed` e resultado de cada ligação, e o Reconciler volta a decidir.

## Decisão

- **Ligação ativa** (`lifecycle = present`): o usuário precisa ter as roles do serviço. Roles a mais não são
  divergência (`Drift`).
- **Ligação desligada** (`lifecycle = absent`): nenhuma permissão do serviço pode estar presente
  (`PermissionsRemovalRequested`).

Guardas do loop (`docs/RESOURCE-CONTROL-SECURITY.md` §7 e §8): sem os dois estados, não decide; `desired`
suspenso não decide; `observed` `unknown` ou vencido não decide; enquanto a observação causada por um
resultado não chega, não decide; ação pendente da mesma geração não é reemitida antes do prazo; após falha,
espera o backoff.

## Configuração

`SUM_SERVICE_RECONCILER_<SEÇÃO>_<CAMPO>`. Obrigatória: `MESSAGING_PASSWORD`. Os parâmetros do loop (`LOOP_*`) estão em
`settings.py` e são os de `schemas/sum/service/desired.v1.schema.json`, mais o período e o jitter da reavaliação.
`MESSAGING_CONSUMER_INACTIVE_THRESHOLD_SECONDS` define quando o servidor remove o consumer de uma instância parada.

## Testes

```bash
uv run pytest           # decisão, motor (publicador simulado), consumer de estado e configurações
uv run ruff check . && uv run pyright
```
