-- Migração 0002 de ipm.user: renomeia `roles` para `permissions` em `desired` e `observed`
-- (docs/identity/PERMISSION.md).
-- Idempotente: só altera linhas que ainda possuem `roles` e não possuem `permissions`.

UPDATE ipm.user
   SET desired = (desired - 'roles') || jsonb_build_object('permissions', desired->'roles'),
       resource_version = resource_version + 1,
       desired_generation = desired_generation + 1,
       updated_at = now()
 WHERE desired ? 'roles'
   AND NOT (desired ? 'permissions');

UPDATE ipm.user
   SET observed = (observed - 'roles') || jsonb_build_object('permissions', observed->'roles'),
       updated_at = now()
 WHERE observed IS NOT NULL
   AND observed ? 'roles'
   AND NOT (observed ? 'permissions');
