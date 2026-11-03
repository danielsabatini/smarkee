-- Migração 0006 de cam.account: novo motivo de rejeição `protected` (decisão 0043).
-- Aditiva: a Operation rejeitada pela proteção contra exclusão guarda `protected` como motivo.
-- Idempotente: pode ser reaplicada sem erro.

ALTER TABLE cam.account_operation
  DROP CONSTRAINT IF EXISTS account_operation_operation_status_reason_check;
ALTER TABLE cam.account_operation
  ADD CONSTRAINT account_operation_operation_status_reason_check
  CHECK (operation_status_reason IN ('conflict', 'validation', 'not_found', 'protected'));
