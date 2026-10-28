-- Migração 0002 de ipm.role: identidade opaca (UUIDv7) das sementes do catálogo e `roleType` (decisão 0089).
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente: em volume novo a 0001 já
-- semeia os UUIDv7 e esta migração não altera nada; em ambiente existente, troca os identificadores legados
-- (`role-<módulo>-<tipo>-<papel>`) pelos UUIDv7 nas tabelas do tipo.

BEGIN;
CREATE TEMP TABLE legacy_role_id (old_id text PRIMARY KEY, new_id text NOT NULL) ON COMMIT DROP;
INSERT INTO legacy_role_id (old_id, new_id) VALUES
    ('role-core-account-viewer', '01a1763d-eb52-748b-84c3-10fa2192a062'),
    ('role-core-account-admin', '01a1763d-eb54-762f-813e-15a4667086f1'),
    ('role-sum-service-viewer', '01a1763d-eb57-7009-9196-741d0a8702ab'),
    ('role-sum-service-admin', '01a1763d-eb59-715e-bfd5-129f757b2768'),
    ('role-ipm-organization-viewer', '01a1763d-eb5c-75f1-b729-da3469748023'),
    ('role-ipm-organization-admin', '01a1763d-eb5e-76c7-9ee2-ff8583f80d5f'),
    ('role-ipm-user-viewer', '01a1763d-eb61-7251-90a6-ba7f921db3f1'),
    ('role-ipm-user-admin', '01a1763d-eb63-7386-90c5-388bcb125747'),
    ('role-ipm-permission-viewer', '01a1763d-eb66-72a8-b4e3-b67bddd33abb'),
    ('role-ipm-permission-admin', '01a1763d-eb68-74e5-a6ad-678e9ae3beed'),
    ('role-ipm-role-viewer', '01a1763d-eb6b-7741-9f74-08d54a0347d0'),
    ('role-ipm-role-admin', '01a1763d-eb6d-73a1-bdc9-a3f97c7560aa'),
    ('role-bsm-account-viewer', '01a1763d-eb70-73f1-84a5-b0ffa6a01b3a'),
    ('role-bsm-account-admin', '01a1763d-eb72-714d-b94d-651adccd509f'),
    ('role-ipm-group-viewer', '01a17641-48a6-7106-88be-dc31ff14f340'),
    ('role-ipm-group-admin', '01a17641-48a9-7074-a84a-6ae0dc0651c4');

UPDATE ipm.role x SET resource_id = m.new_id FROM legacy_role_id m WHERE x.resource_id = m.old_id;
UPDATE ipm.role_operation x SET resource_id = m.new_id FROM legacy_role_id m WHERE x.resource_id = m.old_id;
UPDATE ipm.role_action_result x SET resource_id = m.new_id FROM legacy_role_id m WHERE x.resource_id = m.old_id;
-- Outbox: as linhas já publicadas ficam como histórico; as ainda não publicadas com o ID antigo são
-- descartadas. Cada recurso renomeado ganha uma mensagem `desired` nova (ID determinístico), para o loop
-- passar a conhecê-lo pela nova identidade.
DELETE FROM ipm.role_outbox x
 USING legacy_role_id m
 WHERE x.resource_id = m.old_id AND x.published_at IS NULL;

CREATE FUNCTION pg_temp.opaque_uuid(seed text) RETURNS text LANGUAGE sql IMMUTABLE AS $$
  SELECT substr(md5(seed), 1, 8) || '-' || substr(md5(seed), 9, 4) || '-7' ||
         substr(md5(seed), 14, 3) || '-8' || substr(md5(seed), 18, 3) || '-' || substr(md5(seed), 21, 12)
$$;

INSERT INTO ipm.role_outbox (message_id, resource_id, subject, payload)
SELECT
  pg_temp.opaque_uuid('rename-desired-' || r.resource_id || '-' || r.desired_generation),
  r.resource_id,
  'desired.ipm.role.' || r.resource_id,
  jsonb_build_object(
    'messageId', pg_temp.opaque_uuid('rename-desired-' || r.resource_id || '-' || r.desired_generation),
    'schemaVersion', '1.0',
    'messageType', 'desired',
    'emitter', 'api',
    'module', 'ipm',
    'resourceType', 'role',
    'resourceId', r.resource_id,
    'operation', 'changed',
    'desiredGeneration', r.desired_generation,
    'requestedBy', 'system',
    'correlationId', pg_temp.opaque_uuid('rename-correlation-' || r.resource_id),
    'causationId', pg_temp.opaque_uuid('rename-causation-' || r.resource_id),
    'occurredAt', to_char(now() AT TIME ZONE 'UTC', 'YYYY-MM-DD"T"HH24:MI:SS"Z"'),
    'data', jsonb_build_object('reconciliation', r.reconciliation) || r.desired
  )
FROM ipm.role r
JOIN legacy_role_id m ON m.new_id = r.resource_id
ON CONFLICT (message_id) DO NOTHING;

-- Classificação: as Roles do catálogo da plataforma são `predefined`; as demais, criadas por pedido, `custom`.
UPDATE ipm.role SET desired = desired || '{"roleType": "predefined"}'::jsonb
 WHERE resource_id IN (SELECT new_id FROM legacy_role_id) AND NOT desired ? 'roleType';
UPDATE ipm.role SET desired = desired || '{"roleType": "custom"}'::jsonb
 WHERE NOT desired ? 'roleType';
COMMIT;
