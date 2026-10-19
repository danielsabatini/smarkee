-- Migração 0003 de sum."service": a Operation sempre tem o `resourceId`. O Receiver atribui o id ao
-- recurso novo antes de publicar o pedido, e a recusa de criação grava esse mesmo id: o cliente já o
-- recebeu no `202` e precisa dele para consultar a Operation (`docs/RESOURCE-CONTROL-LOOP.md`, §6.1.1).
-- Desfaz a relaxação da 0002, que partia da premissa errada. Não há linhas com `resource_id` nulo
-- (a 0002 nunca gravou nulo em produção; o dev foi limpo antes desta migração).
-- Idempotente: definir NOT NULL numa coluna que já é NOT NULL não falha.

ALTER TABLE sum.service_operation ALTER COLUMN resource_id SET NOT NULL;
