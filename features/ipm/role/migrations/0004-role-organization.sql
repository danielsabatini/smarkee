-- Migração de ipm.role: Roles `custom` por Organization (decisão 0092).
-- Toda Role passa a ter `organizationId` no `desired`; as predefinidas da plataforma pertencem à
-- Organization de sistema `core`. A unicidade de `name` passa a ser por Organization (a recusa de
-- nome igual ao de uma predefinida é feita pelo Manager, na mesma unidade atômica do pedido).
-- Executada pela infraestrutura como o dono `ssot`, no banco `ssot`. Idempotente.
-- Não republica `desired`: a ausência de `organizationId` já vale `core` nos consumidores, e a
-- mensagem seguinte de cada Role (qualquer alteração) já leva o campo.

BEGIN;

-- Uma `custom` sem Organization não tem dono possível: a migração falha em vez de adivinhar.
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM ipm.role
     WHERE desired ->> 'organizationId' IS NULL
       AND COALESCE(desired ->> 'roleType', 'custom') <> 'predefined'
  ) THEN
    RAISE EXCEPTION 'ipm.role: existe Role custom sem organizationId; defina a Organization antes de migrar';
  END IF;
END
$$;

UPDATE ipm.role
   SET desired = jsonb_set(desired, '{organizationId}', '"core"'::jsonb)
 WHERE desired ->> 'organizationId' IS NULL;

DROP INDEX IF EXISTS ipm.role_active_name;
CREATE UNIQUE INDEX IF NOT EXISTS role_active_organization_name
  ON ipm.role ((desired ->> 'organizationId'), (desired ->> 'name'))
  WHERE lifecycle = 'present';

COMMIT;
