-- Migração 0002 de ipm.role no banco `platform`: identidade opaca (UUIDv7) das Roles pré-definidas (decisão 0089).
-- Executada pela infraestrutura como o dono `platform`. Idempotente: em volume novo a 0001 já semeia os UUIDv7.
-- Em ambiente existente, troca os identificadores legados pelos mesmos UUIDv7 do SSOT, propagando a
-- troca a `ipm.role_permission` (a chave estrangeira passa a `ON UPDATE CASCADE`).

BEGIN;
ALTER TABLE ipm.role_permission DROP CONSTRAINT IF EXISTS role_permission_role_id_fkey;
ALTER TABLE ipm.role_permission
  ADD CONSTRAINT role_permission_role_id_fkey FOREIGN KEY (role_id)
  REFERENCES ipm.role (resource_id) ON DELETE CASCADE ON UPDATE CASCADE;

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
COMMIT;
