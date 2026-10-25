-- Migração 0005 de ipm.organization: renomeia `grantRoles` para `grantPermissions` e
-- `administrators[].roles` para `administrators[].permissions` em `desired.userAccess` e
-- `observed.userAccess` (docs/identity/PERMISSION.md).
-- Executada pela infraestrutura como `ssot` no banco `ssot`; idempotente.

UPDATE ipm.organization
   SET desired = jsonb_set(
         desired,
         '{userAccess}',
         ((desired -> 'userAccess') - 'grantRoles')
           || jsonb_build_object('grantPermissions', desired -> 'userAccess' -> 'grantRoles')
       ),
       updated_at = now()
 WHERE desired ? 'userAccess'
   AND (desired -> 'userAccess') ? 'grantRoles'
   AND NOT ((desired -> 'userAccess') ? 'grantPermissions');

UPDATE ipm.organization
   SET observed = jsonb_set(
         observed,
         '{userAccess}',
         ((observed -> 'userAccess') - 'grantRoles')
           || jsonb_build_object('grantPermissions', observed -> 'userAccess' -> 'grantRoles')
       ),
       updated_at = now()
 WHERE observed IS NOT NULL
   AND observed ? 'userAccess'
   AND (observed -> 'userAccess') ? 'grantRoles'
   AND NOT ((observed -> 'userAccess') ? 'grantPermissions');

UPDATE ipm.organization
   SET observed = jsonb_set(
         observed,
         '{userAccess,administrators}',
         COALESCE(
           (SELECT jsonb_agg(
                     CASE
                       WHEN entry ? 'roles' AND NOT (entry ? 'permissions')
                         THEN (entry - 'roles') || jsonb_build_object('permissions', entry -> 'roles')
                       ELSE entry
                     END
                   )
              FROM jsonb_array_elements(observed -> 'userAccess' -> 'administrators') AS entry),
           '[]'::jsonb
         )
       ),
       updated_at = now()
 WHERE observed IS NOT NULL
   AND observed ? 'userAccess'
   AND (observed -> 'userAccess') ? 'administrators'
   AND EXISTS (
         SELECT 1
           FROM jsonb_array_elements(observed -> 'userAccess' -> 'administrators') AS entry
          WHERE entry ? 'roles' AND NOT (entry ? 'permissions')
       );
