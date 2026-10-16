-- Migração 0002 de ipm.organization: novo motivo de rejeição `protected` (decisão 0043).
-- Aditiva: a Operation rejeitada pela proteção contra exclusão guarda `protected` como motivo.
-- Idempotente: pode ser reaplicada sem erro.

ALTER TABLE ipm.organization_operation
  DROP CONSTRAINT IF EXISTS organization_operation_operation_status_reason_check;
ALTER TABLE ipm.organization_operation
  ADD CONSTRAINT organization_operation_operation_status_reason_check
  CHECK (operation_status_reason IN ('conflict', 'validation', 'not_found', 'protected'));
