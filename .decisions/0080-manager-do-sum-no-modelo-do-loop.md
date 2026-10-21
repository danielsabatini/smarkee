# 0080 — Manager do SUM no modelo do loop

- **Data:** 2026-10-21
- **Status:** Aceita e implementada em dev (etapa 3 do plano que veio do incidente da decisão 0078). Completa no `sum/service` a decisão 0078 (condition `Progressing`) e leva a ele a decisão 0072 (geração confirmada pela observação).
- **Origem:** o Manager do SUM tinha handlers próprios de `observed` e de resultados. A fase era só `Ready` ou `Reconciling`, sem geração confirmada, sem `updated`, sem limite de falhas e sem prazo de progresso. Uma ligação que não convergia não suspendia nem ficava `Failed` por prazo, e uma leitura anterior à geração podia concluí-la.

## Decisão

1. **O `sum/service` declara o perfil `manager-handlers`** (`templates/feature/sync.py`). O Manager passa a aplicar `observed`, `completed` e `failed` pelos handlers do template, os mesmos dos outros tipos: geração confirmada (`observed_generation`), `updated` no outbox, limite de falhas com suspensão (`failureLimit`, 5), condition `Progressing` com o prazo (`progressDeadline`, `PT5M`) e Operations concluídas só na confirmação. A política da ligação (`ServicePolicy`, `manager/domain/service.py`) diz quando ela converge: todas as `serviceRoles` e nenhuma sobra de `managedRoles` (decisão 0079).
2. **A convergência e os erros do Manager passam do perfil `loop-engines` para o `manager-handlers`.** Eles só servem aos handlers do Manager, e o SUM usa os handlers sem usar os motores do Observer e do Executor do template.
3. **`ResourceKind.removes_absent`** (padrão `True`). Com `False`, a remoção convergida não apaga o registro e, enquanto não converge, a fase é `Reconciling`, e não `Deleting`. O SUM usa `False`, porque a ligação desfeita continua existindo (decisão 0033). É a única diferença do SUM no modelo, declarada no tipo.
4. **O Observer do SUM envia `observedGeneration`:** a geração conhecida antes da leitura, como o motor do template.
5. **Uma geração nova zera o `failure_count`** (ligar, desligar e rollout do catálogo), como nos outros tipos. Sem isso, uma ligação suspensa e ligada de novo herdaria as falhas da geração anterior.
6. **Migração aditiva `0006`:** a coluna `observed_generation`, com a mesma restrição dos outros tipos. As linhas `Ready` recebem a geração vigente.

## Onde diverge do modelo anterior do SUM

- **Operation de uma geração substituída antes de convergir:** passa a `failed`, como nos outros tipos. Antes, ela era `completed` junto com a geração seguinte. O estado próprio (`superseded`) fica para a etapa 4 do plano.
- **Ligação desligada que não converge:** continua em `Reconciling` (item 3). O handler genérico a levaria a `Deleting`.

## Compatibilidade

- `updated` de `sum.service` é mensagem nova no stream `UPDATED` (`manager.updated.sum.service.<resourceId>.changed`), com o contrato comum (`schemas/common/updated.v1.schema.json`). O consumer `sum-service-manager-account-removed` filtra `manager.updated.core.account.>` e não a recebe.
- A configuração ganha `SUM_SERVICE_MANAGER_LOOP_FAILURE_LIMIT` e `SUM_SERVICE_MANAGER_LOOP_PROGRESS_DEADLINE_SECONDS` (`docs/CONFIGURATION.md` da feature, gerado).
- O `observed` sem `observedGeneration` (Observer antigo) não confirma geração: a ligação fica `Reconciling` até o Observer novo subir. Por isso a imagem é uma só e os papéis sobem juntos.

## Verificação (dev, 2026-10-21)

- Migração aplicada: a ligação real do dev (`01a15ec2-…`) ficou com `observed_generation = 2`. Depois da troca dos contêineres, voltou a `Ready` com as conditions `Ready/Reconciled` e `Progressing/Converged`, e o `updated` saiu no NATS com `desiredGeneration = observedGeneration = 2`, sem nenhum `WARN` ou `ERROR` nos seis papéis.
- Os testes de integração do Manager passam contra o SSOT real: fase e geração confirmada, leitura anterior à geração, ligação desligada mantida, falhas uma vez por `actionId` com suspensão no limite e Operations da geração vigente. Os testes unitários cobrem a política, o prazo e o envio do `observedGeneration`.
- **Não verificado:** a ida e volta completa pela API (ligar e desligar), porque ela precisa do token de um solicitante e hoje só sai de um login interativo. Isso fica com a jornada e2e da etapa 5.
