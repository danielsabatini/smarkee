-- Migração 0003 de cam.account: nomes das roles em `desired.platformRoles` (decisão 0028).
-- Projeto: cam-account-manager. Executada pela infraestrutura como o dono `ssot`.
-- Troca `organization.*` por `ipm.organization.*` e `account.*` por `cam.account.*`. Só o jsonb muda: sem
-- nova geração. Idempotente: os nomes novos não casam com os antigos, então a reaplicação não altera nada.

UPDATE cam.account
   SET desired = jsonb_set(
         desired,
         '{platformRoles}',
         (SELECT COALESCE(jsonb_agg(renamed ORDER BY renamed), '[]'::jsonb)
            FROM (SELECT CASE
                           WHEN role ~ '^organization\.' THEN 'ipm.' || role
                           WHEN role ~ '^account\.'         THEN 'cam.' || role
                           ELSE role
                         END AS renamed
                    FROM jsonb_array_elements_text(desired -> 'platformRoles') AS role) AS roles))
 WHERE desired ? 'platformRoles'
   AND EXISTS (
         SELECT 1 FROM jsonb_array_elements_text(desired -> 'platformRoles') AS role
          WHERE role ~ '^(organization|account)\.');
