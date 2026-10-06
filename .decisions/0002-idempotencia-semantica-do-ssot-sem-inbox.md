# 0002 — Idempotência semântica do SSOT, sem inbox

- **Data:** 2026-10-06
- **Status:** Aceita

## Contexto

O modelo anterior do SSOT tinha uma tabela de inbox (identidades de mensagens recebidas) declarada como otimização, sem papel na correção. A idempotência dos resultados (`completed` e `failed`) era atribuída ao `actionId`, mas nenhuma tabela o registrava. A idempotência de `requested` dependia de uma chave opcional, única por tipo de recurso e não escopada ao solicitante, e a chave não era transportada até o Manager.

Consequências identificadas na revisão:

- um `failed` reentregue era contado duas vezes, o que podia suspender o recurso antes da hora;
- um `failed` atrasado de uma geração anterior era contado contra a geração atual;
- um `update` reentregue depois do `COMMIT` falhava na conferência da `resourceVersion` e virava um conflito falso;
- um cliente que reutilizasse a chave de idempotência de outro receberia a Operation alheia.

## Decisão

- **Remover o inbox.** A correção é garantida pelas regras semânticas, e o transporte já deduplica por `Nats-Msg-Id` dentro da sua janela.
- **`requested`:** a identidade da Operation (`operationId`) é atribuída pela API e transportada no `requested`. Ela é derivada de forma determinística da chave de idempotência do cliente, no escopo do solicitante e do tipo de recurso, ou é aleatória sem chave. A API também transporta o `requestDigest`, para detectar o reuso da chave com outro conteúdo. A chave primária da Operation é a garantia de idempotência.
- **`completed` e `failed`:** nova tabela `<tipo>_action_result`, com o `actionId` como chave primária, registrada antes de qualquer efeito. Um resultado de geração diferente da atual não altera `failureCount` nem `phase`.
- **Rejeição:** a Operation ganha o estado `rejected` com motivo (`conflict`, `validation`, `not_found`), porque a API responde de forma assíncrona e o conflito só é conhecido pelo Manager.

## Justificativa

Cada garantia passa a ter um registro durável com retenção definida, em vez de depender de uma janela de deduplicação. O inbox exigia uma escrita por mensagem, uma tabela, privilégios e um job de retenção sem acrescentar correção (`AGENTS.md`, simplicidade).

## Consequências

- O número de tabelas por tipo continua quatro: `<tipo>`, `<tipo>_operation`, `<tipo>_action_result` e `<tipo>_outbox`.
- O contrato `requested` passa a ter os campos `operationId` e `requestDigest` (`docs/SCHEMA.md`).
- A retenção da Operation precisa ser maior que o prazo máximo de reentrega do `requested`, e a de `ActionResult`, maior que a retenção dos resultados no transporte.
