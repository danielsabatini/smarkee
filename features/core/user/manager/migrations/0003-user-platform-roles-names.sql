-- Migração 0003 de core."user": nomes das roles em `desired.platformRoles` (decisão 0028).
-- Projeto: core-user-manager. Executada pela infraestrutura como o dono `smarkee`.
-- Troca `organization.*` por `ipm.organization.*` e `user.*` por `core.user.*`. Só o jsonb muda: sem
-- nova geração. Idempotente: os nomes novos não casam com os antigos, então a reaplicação não altera nada.

UPDATE core."user"
   SET desired = jsonb_set(
         desired,
         '{platformRoles}',
         (SELECT COALESCE(jsonb_agg(renamed ORDER BY renamed), '[]'::jsonb)
            FROM (SELECT CASE
                           WHEN role ~ '^organization\.' THEN 'ipm.' || role
                           WHEN role ~ '^user\.'         THEN 'core.' || role
                           ELSE role
                         END AS renamed
                    FROM jsonb_array_elements_text(desired -> 'platformRoles') AS role) AS roles))
 WHERE EXISTS (
         SELECT 1 FROM jsonb_array_elements_text(desired -> 'platformRoles') AS role
          WHERE role ~ '^(organization|user)\.');
