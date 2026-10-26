-- Migração de core.account: novo estado de Operation `superseded` (decisão 0091).
-- Aditiva: a Operation de uma geração substituída por outra antes de convergir deixa de ser `failed`.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente.

ALTER TABLE core.account_operation
  DROP CONSTRAINT IF EXISTS account_operation_operation_status_check;
ALTER TABLE core.account_operation
  ADD CONSTRAINT account_operation_operation_status_check
  CHECK (operation_status IN ('accepted', 'in_progress', 'completed', 'failed', 'rejected', 'superseded'));

DROP INDEX IF EXISTS core.account_operation_retention;
CREATE INDEX account_operation_retention
  ON core.account_operation (updated_at)
  WHERE operation_status IN ('completed', 'failed', 'rejected', 'superseded');
