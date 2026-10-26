-- Migração de ipm.group: novo estado de Operation `superseded` (decisão 0091).
-- Aditiva: a Operation de uma geração substituída por outra antes de convergir deixa de ser `failed`.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente.

ALTER TABLE ipm.group_operation
  DROP CONSTRAINT IF EXISTS group_operation_operation_status_check;
ALTER TABLE ipm.group_operation
  ADD CONSTRAINT group_operation_operation_status_check
  CHECK (operation_status IN ('accepted', 'in_progress', 'completed', 'failed', 'rejected', 'superseded'));

DROP INDEX IF EXISTS ipm.group_operation_retention;
CREATE INDEX group_operation_retention
  ON ipm.group_operation (updated_at)
  WHERE operation_status IN ('completed', 'failed', 'rejected', 'superseded');
