-- Migração de ipm.organization: novo estado de Operation `superseded` (decisão 0091).
-- Aditiva: a Operation de uma geração substituída por outra antes de convergir deixa de ser `failed`.
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente.

ALTER TABLE ipm.organization_operation
  DROP CONSTRAINT IF EXISTS organization_operation_operation_status_check;
ALTER TABLE ipm.organization_operation
  ADD CONSTRAINT organization_operation_operation_status_check
  CHECK (operation_status IN ('accepted', 'in_progress', 'completed', 'failed', 'rejected', 'superseded'));

DROP INDEX IF EXISTS ipm.organization_operation_retention;
CREATE INDEX organization_operation_retention
  ON ipm.organization_operation (updated_at)
  WHERE operation_status IN ('completed', 'failed', 'rejected', 'superseded');
