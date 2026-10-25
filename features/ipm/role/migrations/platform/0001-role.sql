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
                      CHECK (length(description) BETWEEN 1 AND 256 AND description !~ '[\u0000-\u001f\u007f]'),
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
    ('role-core-account-viewer', 'core.accountViewer',
     'Leitura de conta pessoal em core.account.',
     ARRAY['core.account.get']),
    ('role-core-account-admin', 'core.accountAdmin',
     'Administração da própria conta em core.account.',
     ARRAY['core.account.delete', 'core.account.get']),
    ('role-sum-service-viewer', 'sum.serviceViewer',
     'Leitura de serviços habilitados em sum.service.',
     ARRAY['sum.ipm.get']),
    ('role-sum-service-admin', 'sum.serviceAdmin',
     'Administração de serviços habilitados em sum.service.',
     ARRAY['sum.ipm.disable', 'sum.ipm.enable', 'sum.ipm.get']),
    ('role-ipm-organization-viewer', 'ipm.organizationViewer',
     'Leitura de Organizations em ipm.organization.',
     ARRAY['ipm.organization.get', 'ipm.organization.list']),
    ('role-ipm-organization-admin', 'ipm.organizationAdmin',
     'Administração de Organizations em ipm.organization.',
     ARRAY['ipm.organization.create', 'ipm.organization.delete', 'ipm.organization.get',
           'ipm.organization.list', 'ipm.organization.update']),
    ('role-ipm-user-viewer', 'ipm.userViewer',
     'Leitura de usuários organizacionais em ipm.user.',
     ARRAY['ipm.user.get', 'ipm.user.list']),
    ('role-ipm-user-admin', 'ipm.userAdmin',
     'Administração completa e delegação de permissões de usuários em ipm.user.',
     ARRAY['ipm.user.bind', 'ipm.user.create', 'ipm.user.delete', 'ipm.user.get',
           'ipm.user.list', 'ipm.user.update']),
    ('role-ipm-permission-viewer', 'ipm.permissionViewer',
     'Leitura do catálogo de permissões atômicas em ipm.permission.',
     ARRAY['ipm.permission.get', 'ipm.permission.list']),
    ('role-ipm-permission-admin', 'ipm.permissionAdmin',
     'Administração do catálogo de permissões atômicas em ipm.permission.',
     ARRAY['ipm.permission.admin', 'ipm.permission.get', 'ipm.permission.list']),
    ('role-ipm-role-viewer', 'ipm.roleViewer',
     'Leitura do catálogo de Roles compostas em ipm.role.',
     ARRAY['ipm.role.get', 'ipm.role.list']),
    ('role-ipm-role-admin', 'ipm.roleAdmin',
     'Administração do catálogo de Roles compostas em ipm.role.',
     ARRAY['ipm.role.admin', 'ipm.role.get', 'ipm.role.list']),
    ('role-bsm-account-viewer', 'bsm.accountViewer',
     'Leitura de Billing Accounts em bsm.account.',
     ARRAY['bsm.account.get', 'bsm.account.list']),
    ('role-bsm-account-admin', 'bsm.accountAdmin',
     'Administração de Billing Accounts em bsm.account.',
     ARRAY['bsm.account.create', 'bsm.account.delete', 'bsm.account.get',
           'bsm.account.list', 'bsm.account.update'])
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
