-- Migração 0001 de ipm.group no banco `platform` (plano de dados; decisões 0086 e 0088).
-- Guarda o Grupo que o Executor grava e o Observer lê, SEPARADO do SSOT (`ssot`, migrations/0001-group.sql).
-- Executada pela infraestrutura como o dono `platform`, no banco `platform`; serviços de runtime não
-- executam DDL. Os papéis `ipm_group_executor` e `ipm_group_observer` são criados por
-- infrastructure/dev/database/bootstrap/ipm.sql.
-- Multi-tenant: `organization_id` identifica a Organization proprietária do grupo.
-- Idempotente: pode ser reaplicada sem erro.

CREATE SCHEMA IF NOT EXISTS ipm;

CREATE TABLE IF NOT EXISTS ipm.group (
  resource_id         text        PRIMARY KEY
                      CHECK (resource_id ~ '^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$'),
  organization_id     text        NOT NULL
                      CHECK (organization_id ~ '^[a-z0-9]([a-z0-9-]{0,62}[a-z0-9])?$'),
  name                text        NOT NULL
                      CHECK (name ~ '^[a-z][a-z0-9-]{0,61}[a-z0-9]$'),
  description         text        NOT NULL
                      CHECK (length(description) >= 1 AND length(description) <= 256
                              AND description !~ '[\u0000-\u001f\u007f]'),
  deletion_protection boolean     NOT NULL DEFAULT false,
  created_at          timestamptz NOT NULL DEFAULT now(),
  updated_at          timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT group_organization_name_key UNIQUE (organization_id, name)
);

CREATE TABLE IF NOT EXISTS ipm.group_role (
  group_id  text NOT NULL REFERENCES ipm.group (resource_id) ON DELETE CASCADE,
  role_name text NOT NULL
            CHECK (role_name ~ '^[a-z][a-z0-9]*\.[a-z][a-zA-Z0-9]*$'
                   AND length(role_name) BETWEEN 5 AND 128),
  PRIMARY KEY (group_id, role_name)
);

-- Privilégios: o Executor é o único com escrita; o Observer só lê. Nenhum papel do SSOT conecta aqui.
GRANT CONNECT ON DATABASE platform TO ipm_group_executor, ipm_group_observer;

REVOKE ALL ON SCHEMA ipm FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA ipm FROM PUBLIC;
GRANT USAGE ON SCHEMA ipm TO ipm_group_executor, ipm_group_observer;

GRANT SELECT, INSERT, UPDATE, DELETE ON ipm.group      TO ipm_group_executor;
GRANT SELECT, INSERT, DELETE         ON ipm.group_role TO ipm_group_executor;
GRANT SELECT ON ipm.group, ipm.group_role TO ipm_group_observer;
