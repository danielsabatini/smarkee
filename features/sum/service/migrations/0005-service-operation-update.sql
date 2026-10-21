-- Migração 0005 de sum."service": a Operation `update`, do rollout do catálogo (decisão 0079).
-- Quando o catálogo de um serviço muda, o Manager grava uma geração nova nas ligações afetadas, com
-- uma Operation `update` do sistema, e o loop aplica a mudança (como o rollout do Kubernetes).
-- Aditiva e idempotente: só acrescenta um valor permitido.

ALTER TABLE sum.service_operation
  DROP CONSTRAINT IF EXISTS service_operation_operation_type_check;
ALTER TABLE sum.service_operation
  ADD CONSTRAINT service_operation_operation_type_check
  CHECK (operation_type IN ('create', 'update', 'delete'));
