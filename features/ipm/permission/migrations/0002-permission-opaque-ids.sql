-- Migração 0002 de ipm.permission: identidade opaca (UUIDv7) das sementes do catálogo (decisão 0089).
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente: em volume novo a 0001 já
-- semeia os UUIDv7 e esta migração não altera nada; em ambiente existente, troca os identificadores legados
-- (`perm-<módulo>-<tipo>-<ação>`) pelos UUIDv7 nas tabelas do tipo.

BEGIN;
CREATE TEMP TABLE legacy_permission_id (old_id text PRIMARY KEY, new_id text NOT NULL) ON COMMIT DROP;
INSERT INTO legacy_permission_id (old_id, new_id) VALUES
    ('perm-bsm-account-create', '01a1763d-eb05-7408-8945-8b7798b1f584'),
    ('perm-bsm-account-delete', '01a1763d-eb07-73a3-9238-cebddc755e48'),
    ('perm-bsm-account-get', '01a1763d-eb0a-73e6-ae87-09479da576ee'),
    ('perm-bsm-account-list', '01a1763d-eb0c-71d0-82c7-3010ed561cc5'),
    ('perm-bsm-account-update', '01a1763d-eb0f-75ea-8b0f-8bf1afb324fa'),
    ('perm-bsm-account-admin', '01a1763d-eb11-715e-96bb-90b4ab137e28'),
    ('perm-core-account-delete', '01a1763d-eb14-74eb-86dd-6f7f4b480783'),
    ('perm-core-account-get', '01a1763d-eb16-748d-bafc-dd2976ec27a4'),
    ('perm-core-account-admin', '01a1763d-eb19-737d-9a93-d95b72ff01c0'),
    ('perm-sum-ipm-disable', '01a1763d-eb1c-70bf-bf6c-8e2bb3bed9ec'),
    ('perm-sum-ipm-enable', '01a1763d-eb1e-7411-939c-a0f773e2f875'),
    ('perm-sum-ipm-get', '01a1763d-eb21-7647-aa8d-66b6fe110cf3'),
    ('perm-ipm-organization-create', '01a1763d-eb23-7095-9112-0b521899e026'),
    ('perm-ipm-organization-delete', '01a1763d-eb26-7392-b4a7-e3ed5a955cce'),
    ('perm-ipm-organization-get', '01a1763d-eb28-773d-804c-1779722fbb95'),
    ('perm-ipm-organization-list', '01a1763d-eb2a-716f-9417-5dc1e3d3264f'),
    ('perm-ipm-organization-update', '01a1763d-eb2d-726e-b505-3592ecdff4d6'),
    ('perm-ipm-organization-admin', '01a1763d-eb2f-73e4-8e15-29bb53ca2855'),
    ('perm-ipm-user-bind', '01a1763d-eb32-73e1-b31b-44a5a2a7669a'),
    ('perm-ipm-user-create', '01a1763d-eb34-7534-8d01-569b74847fcc'),
    ('perm-ipm-user-delete', '01a1763d-eb37-721a-8ac9-9aaa0550c7ea'),
    ('perm-ipm-user-get', '01a1763d-eb39-7341-8c3b-43b5c7f9ade5'),
    ('perm-ipm-user-list', '01a1763d-eb3c-747c-86fe-8f34692042e2'),
    ('perm-ipm-user-update', '01a1763d-eb3e-72dd-b96c-015c189af10b'),
    ('perm-ipm-user-admin', '01a1763d-eb40-71a5-ab70-96207a5b4d2d'),
    ('perm-ipm-permission-get', '01a1763d-eb43-703d-a168-aa3ade79c4f8'),
    ('perm-ipm-permission-list', '01a1763d-eb45-7247-ab1a-90fdc45b217d'),
    ('perm-ipm-permission-admin', '01a1763d-eb48-728c-ade2-0dbe753f70de'),
    ('perm-ipm-role-get', '01a1763d-eb4a-7168-981a-0862f72aeeca'),
    ('perm-ipm-role-list', '01a1763d-eb4d-750a-b163-4e082cff09ee'),
    ('perm-ipm-role-admin', '01a1763d-eb4f-71f6-ad10-991a7f90c40a'),
    ('perm-ipm-group-create', '01a17641-4895-761f-888f-24ca35143f79'),
    ('perm-ipm-group-delete', '01a17641-4897-73c9-adf3-a0ddcf0e27d3'),
    ('perm-ipm-group-get', '01a17641-489a-7615-848c-3263328fedc0'),
    ('perm-ipm-group-list', '01a17641-489c-75c9-81c4-34e1ce2459a7'),
    ('perm-ipm-group-update', '01a17641-489f-72ea-9647-b39cb4237b52'),
    ('perm-ipm-group-bind', '01a17641-48a1-77c5-9e35-69e7e1b1706f'),
    ('perm-ipm-group-admin', '01a17641-48a4-7790-9a6c-25f5aaea438c');

UPDATE ipm.permission x SET resource_id = m.new_id FROM legacy_permission_id m WHERE x.resource_id = m.old_id;
UPDATE ipm.permission_operation x SET resource_id = m.new_id FROM legacy_permission_id m WHERE x.resource_id = m.old_id;
UPDATE ipm.permission_action_result x SET resource_id = m.new_id FROM legacy_permission_id m WHERE x.resource_id = m.old_id;
-- Outbox: as linhas já publicadas ficam como histórico; as ainda não publicadas com o ID antigo são
-- descartadas. Cada recurso renomeado ganha uma mensagem `desired` nova (ID determinístico), para o loop
-- passar a conhecê-lo pela nova identidade.
DELETE FROM ipm.permission_outbox x
 USING legacy_permission_id m
 WHERE x.resource_id = m.old_id AND x.published_at IS NULL;

CREATE FUNCTION pg_temp.opaque_uuid(seed text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT substr(md5(seed), 1, 8) || '-' || substr(md5(seed), 9, 4) || '-7' ||
         substr(md5(seed), 14, 3) || '-8' || substr(md5(seed), 18, 3) || '-' || substr(md5(seed), 21, 12)
$$;

INSERT INTO ipm.permission_outbox (message_id, resource_id, subject, payload)
SELECT
  pg_temp.opaque_uuid('rename-desired-' || r.resource_id || '-' || r.desired_generation),
  r.resource_id,
  'desired.ipm.permission.' || r.resource_id,
  jsonb_build_object(
    'messageId', pg_temp.opaque_uuid('rename-desired-' || r.resource_id || '-' || r.desired_generation),
    'schemaVersion', '1.0',
    'messageType', 'desired',
    'emitter', 'api',
    'module', 'ipm',
    'resourceType', 'permission',
    'resourceId', r.resource_id,
    'operation', 'changed',
    'desiredGeneration', r.desired_generation,
    'requestedBy', 'system',
    'correlationId', pg_temp.opaque_uuid('rename-correlation-' || r.resource_id),
    'causationId', pg_temp.opaque_uuid('rename-causation-' || r.resource_id),
    'occurredAt', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'data', jsonb_build_object('reconciliation', r.reconciliation) || r.desired
  )
FROM ipm.permission r
JOIN legacy_permission_id m ON m.new_id = r.resource_id
ON CONFLICT (message_id) DO NOTHING;
COMMIT;
