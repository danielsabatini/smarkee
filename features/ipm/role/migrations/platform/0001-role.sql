-- Migração 0001 de ipm.role no banco `platform` (plano de dados; decisão 0086).
-- Guarda a Role que o Executor grava e o Observer lê, SEPARADA do SSOT (`smarkee`, migrations/0001-role.sql).
-- Executada pela infraestrutura como o dono `platform`, no banco `platform`; serviços de runtime não
-- executam DDL. Os papéis `ipm_role_executor` e `ipm_role_observer` são criados por
-- infrastructure/dev/database/bootstrap/ipm.sql.
-- Multi-tenant: `organization_id` usa o mesmo identificador da Organization do Zitadel; as Roles globais
-- predefinidas da plataforma ficam na organização `core`.
-- Idempotente: pode ser reaplicada sem erro.

CREATE SCHEMA IF NOT EXISTS ipm;

CREATE TABLE IF NOT EXISTS ipm.role (
  resource_id         text        PRIMARY KEY
                      CHECK (resource_id ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
  organization_id     text        NOT NULL DEFAULT 'core'
                      CHECK (organization_id ~ '^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$'),
  name                text        NOT NULL
                      CHECK (name ~ '^[a-z][a-z0-9]*\.[a-z][a-zA-Z0-9]*$' AND length(name) BETWEEN 3 AND 128),
  description         text        NOT NULL
                      CHECK (length(description) >= 1 AND length(description) <= 256
                              AND description !~ '[\u0000-\u001f\u007f]'),
  deletion_protection boolean     NOT NULL DEFAULT true,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT role_organization_name_key UNIQUE (organization_id, name)
);

CREATE TABLE IF NOT EXISTS ipm.role_permission (
  role_id        text NOT NULL REFERENCES ipm.role (resource_id) ON DELETE CASCADE,
  permission_key text NOT NULL
                 CHECK (permission_key ~ '^[a-z][a-z0-9]*\.[a-z][a-z0-9]*\.[a-z][a-z0-9]*$'
                        AND length(permission_key) BETWEEN 5 AND 128),
  PRIMARY KEY (role_id, permission_key)
);

-- Roles pré-definidas da plataforma (mesmos `resource_id` e `name` do SSOT; decisão 0083). Protegidas
-- contra exclusão por padrão. O Executor reconverge o restante pelo loop.
WITH predefined(resource_id, role_name, description, permissions) AS (
  VALUES
    ('01a1763d-eb52-748b-84c3-10fa2192a062', 'core.accountViewer',
     'Leitura de conta pessoal em core.account.',
     ARRAY['core.account.get']),
    ('01a1763d-eb54-762f-813e-15a4667086f1', 'core.accountAdmin',
     'Administração da própria conta em core.account.',
     ARRAY['core.account.delete', 'core.account.get']),
    ('01a1763d-eb57-7009-9196-741d0a8702ab', 'sum.serviceViewer',
     'Leitura de serviços habilitados em sum.service.',
     ARRAY['sum.ipm.get']),
    ('01a1763d-eb59-715e-bfd5-129f757b2768', 'sum.serviceAdmin',
     'Administração de serviços habilitados em sum.service.',
     ARRAY['sum.ipm.disable', 'sum.ipm.enable', 'sum.ipm.get']),
    ('01a1763d-eb5c-75f1-b729-da3469748023', 'ipm.organizationViewer',
     'Leitura de Organizations em ipm.organization.',
     ARRAY['ipm.organization.get', 'ipm.organization.list']),
    ('01a1763d-eb5e-76c7-9ee2-ff8583f80d5f', 'ipm.organizationAdmin',
     'Administração de Organizations em ipm.organization.',
     ARRAY['ipm.organization.create', 'ipm.organization.delete', 'ipm.organization.get',
           'ipm.organization.list', 'ipm.organization.update']),
    ('01a1763d-eb61-7251-90a6-ba7f921db3f1', 'ipm.userViewer',
     'Leitura de usuários organizacionais em ipm.user.',
     ARRAY['ipm.user.get', 'ipm.user.list']),
    ('01a1763d-eb63-7386-90c5-388bcb125747', 'ipm.userAdmin',
     'Administração completa e delegação de permissões de usuários em ipm.user.',
     ARRAY['ipm.user.bind', 'ipm.user.create', 'ipm.user.delete', 'ipm.user.get',
           'ipm.user.list', 'ipm.user.update']),
    ('01a1763d-eb66-72a8-b4e3-b67bddd33abb', 'ipm.permissionViewer',
     'Leitura do catálogo de permissões atômicas em ipm.permission.',
     ARRAY['ipm.permission.get', 'ipm.permission.list']),
    ('01a1763d-eb68-74e5-a6ad-678e9ae3beed', 'ipm.permissionAdmin',
     'Administração do catálogo de permissões atômicas em ipm.permission.',
     ARRAY['ipm.permission.admin', 'ipm.permission.get', 'ipm.permission.list']),
    ('01a1763d-eb6b-7741-9f74-08d54a0347d0', 'ipm.roleViewer',
     'Leitura do catálogo de Roles compostas em ipm.role.',
     ARRAY['ipm.role.get', 'ipm.role.list']),
    ('01a1763d-eb6d-73a1-bdc9-a3f97c7560aa', 'ipm.roleAdmin',
     'Administração do catálogo de Roles compostas em ipm.role.',
     ARRAY['ipm.role.admin', 'ipm.role.get', 'ipm.role.list']),
    ('01a1763d-eb70-73f1-84a5-b0ffa6a01b3a', 'bsm.accountViewer',
     'Leitura de Billing Accounts em bsm.account.',
     ARRAY['bsm.account.get', 'bsm.account.list']),
    ('01a1763d-eb72-714d-b94d-651adccd509f', 'bsm.accountAdmin',
     'Administração de Billing Accounts em bsm.account.',
     ARRAY['bsm.account.create', 'bsm.account.delete', 'bsm.account.get',
           'bsm.account.list', 'bsm.account.update']),
    ('01a17641-48a6-7106-88be-dc31ff14f340', 'ipm.groupViewer',
     'Leitura de grupos de usuários em ipm.group.',
     ARRAY['ipm.group.get', 'ipm.group.list']),
    ('01a17641-48a9-7074-a84a-6ae0dc0651c4', 'ipm.groupAdmin',
     'Administração de grupos de usuários em ipm.group.',
     ARRAY['ipm.group.bind', 'ipm.group.create', 'ipm.group.delete', 'ipm.group.get', 'ipm.group.list', 'ipm.group.update'])
),
inserted AS (
  INSERT INTO ipm.role (resource_id, organization_id, name, description, deletion_protection)
  SELECT resource_id, 'core', role_name, description, true
    FROM predefined
  ON CONFLICT DO NOTHING
  RETURNING resource_id
)
INSERT INTO ipm.role_permission (role_id, permission_key)
SELECT p.resource_id, permission_key
  FROM predefined p
  JOIN inserted i USING (resource_id)
  CROSS JOIN LATERAL unnest(p.permissions) AS permission_key
ON CONFLICT DO NOTHING;

-- Privilégios: o Executor é o único com escrita; o Observer só lê. Nenhum papel do SSOT conecta aqui.
GRANT CONNECT ON DATABASE platform TO ipm_role_executor, ipm_role_observer;

REVOKE ALL ON SCHEMA ipm FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA ipm FROM PUBLIC;
GRANT USAGE ON SCHEMA ipm TO ipm_role_executor, ipm_role_observer;

GRANT SELECT, INSERT, UPDATE, DELETE ON ipm.role            TO ipm_role_executor;
GRANT SELECT, INSERT, DELETE         ON ipm.role_permission TO ipm_role_executor;
GRANT SELECT ON ipm.role, ipm.role_permission TO ipm_role_observer;
