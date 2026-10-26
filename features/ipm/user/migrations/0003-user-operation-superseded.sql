-- Migração de ipm.user: novo estado de Operation `superseded` (decisão 0091).
-- Aditiva: a Operation de uma geração substituída por outra antes de convergir deixa de ser `failed`.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente.

ALTER TABLE ipm.user_operation
  DROP CONSTRAINT IF EXISTS user_operation_operation_status_check;
ALTER TABLE ipm.user_operation
  ADD CONSTRAINT user_operation_operation_status_check
  CHECK (operation_status IN ('accepted', 'in_progress', 'completed', 'failed', 'rejected', 'superseded'));

DROP INDEX IF EXISTS ipm.user_operation_retention;
CREATE INDEX user_operation_retention
  ON ipm.user_operation (updated_at)
  WHERE operation_status IN ('completed', 'failed', 'rejected', 'superseded');
