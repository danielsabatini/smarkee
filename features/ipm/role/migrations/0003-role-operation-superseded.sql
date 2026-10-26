-- Migração de ipm.role: novo estado de Operation `superseded` (decisão 0091).
-- Aditiva: a Operation de uma geração substituída por outra antes de convergir deixa de ser `failed`.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente.

ALTER TABLE ipm.role_operation
  DROP CONSTRAINT IF EXISTS role_operation_operation_status_check;
ALTER TABLE ipm.role_operation
  ADD CONSTRAINT role_operation_operation_status_check
  CHECK (operation_status IN ('accepted', 'in_progress', 'completed', 'failed', 'rejected', 'superseded'));

DROP INDEX IF EXISTS ipm.role_operation_retention;
CREATE INDEX role_operation_retention
  ON ipm.role_operation (updated_at)
  WHERE operation_status IN ('completed', 'failed', 'rejected', 'superseded');
