-- Migração de sum.service: novo estado de Operation `superseded` (decisão 0091).
-- Aditiva: a Operation de uma geração substituída por outra antes de convergir deixa de ser `failed`.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente.

ALTER TABLE sum.service_operation
  DROP CONSTRAINT IF EXISTS service_operation_operation_status_check;
ALTER TABLE sum.service_operation
  ADD CONSTRAINT service_operation_operation_status_check
  CHECK (operation_status IN ('accepted', 'in_progress', 'completed', 'failed', 'rejected', 'superseded'));

DROP INDEX IF EXISTS sum.service_operation_retention;
CREATE INDEX service_operation_retention
  ON sum.service_operation (updated_at)
  WHERE operation_status IN ('completed', 'failed', 'rejected', 'superseded');
