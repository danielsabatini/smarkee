-- Migração de cam.account: novo estado de Operation `superseded` (decisão 0091).
-- Aditiva: a Operation de uma geração substituída por outra antes de convergir deixa de ser `failed`.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente.

ALTER TABLE cam.account_operation
  DROP CONSTRAINT IF EXISTS account_operation_operation_status_check;
ALTER TABLE cam.account_operation
  ADD CONSTRAINT account_operation_operation_status_check
  CHECK (operation_status IN ('accepted', 'in_progress', 'completed', 'failed', 'rejected', 'superseded'));

DROP INDEX IF EXISTS cam.account_operation_retention;
CREATE INDEX account_operation_retention
  ON cam.account_operation (updated_at)
  WHERE operation_status IN ('completed', 'failed', 'rejected', 'superseded');
