-- Migração 0007 de sum."service": renomeia `serviceRoles`/`managedRoles` para `servicePermissions`/`managedPermissions` (decisão 0083).
-- Idempotente: pode ser reaplicada sem erro.

ALTER TABLE sum.service
  DROP CONSTRAINT IF EXISTS service_check1;

UPDATE sum.service
   SET desired = jsonb_set(desired - 'serviceRoles', '{servicePermissions}', desired -> 'serviceRoles')
 WHERE desired ? 'serviceRoles'
   AND NOT (desired ? 'servicePermissions');

UPDATE sum.service
   SET desired = jsonb_set(desired - 'managedRoles', '{managedPermissions}', desired -> 'managedRoles')
 WHERE desired ? 'managedRoles'
   AND NOT (desired ? 'managedPermissions');

UPDATE sum.service
   SET observed = jsonb_set(observed - 'serviceRoles', '{servicePermissions}', observed -> 'serviceRoles')
 WHERE observed IS NOT NULL
   AND observed ? 'serviceRoles'
   AND NOT (observed ? 'servicePermissions');

ALTER TABLE sum.service
  ADD CONSTRAINT service_check1
  CHECK (lifecycle = 'present' OR jsonb_array_length(desired -> 'servicePermissions') = 0);
