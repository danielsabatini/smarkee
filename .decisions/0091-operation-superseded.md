# 0091 — Operation `superseded`

- **Data:** 2026-10-26
- **Status:** Aceita e implementada nas 8 features com Operation, na CLI e no console.
- **Origem:** pendência das decisões `0078` e `0090`. Uma geração substituída por outra antes de convergir terminava `failed`, o que misturava dois fatos diferentes.

## Contexto

- O Manager encerrava como `failed` toda Operation aberta de geração anterior quando chegava uma geração nova (`settle_operations`). Quem lia a Operation não distinguia "o pedido falhou" de "outro pedido o sobrepôs".
- Com a `0090`, `failed` passou a significar limite de falhas ou prazo esgotado. Manter a substituição nele tornaria o estado ambíguo.
- O Kubernetes não usa o mesmo estado: o ReplicaSet antigo é escalado a zero e o rollout só marca falha pelo `progressDeadlineSeconds`. Aqui a Operation descreve o pedido, e não o recurso; a substituição é um fim próprio do pedido.

## Decisão

1. `operationStatus` ganha o valor **`superseded`** (enum fechado em `schemas/common/operation.v1.schema.json`). É terminal, não tem `operationStatusReason` e mantém `desiredGeneration`.
2. O Manager grava `superseded` (e não mais `failed`) nas Operations `accepted`/`in_progress` de geração anterior à atual, no mesmo passo de `settle_operations`.
3. O `CHECK` de `operation_status` de cada tipo e o índice de retenção (`*_operation_retention`) passam a incluir `superseded`, por migração aditiva e idempotente por feature.
4. A CLI trata `superseded` como fim sem sucesso, com a mensagem "The Operation ended as superseded". O console o trata como terminal, com o selo "Substituído" (tom de aviso).
5. O significado de `failed` fica restrito a `failureLimit` e prazo esgotado (`0090`).

## O que permanece, o que se acrescenta (§2.6)

- Permanece: todos os demais estados, motivos e a regra da `0090` de encerrar por prazo.
- Acrescenta: o valor `superseded` e o seu tratamento nos clientes.
- Substitui: apenas o uso de `failed` para geração substituída.

## Consequências

- Contrato **aditivo** no schema. Quem tratava o enum como fechado precisa conhecer o novo valor; a CLI e o console foram atualizados. Operations antigas gravadas como `failed` por substituição ficam como estão (histórico), sem reescrita.
- Um `update` seguido de outro antes da convergência passa a mostrar a primeira Operation `superseded` e a última `completed`. Validado no dev em 2026-10-26 com três pedidos seguidos em uma permission.
