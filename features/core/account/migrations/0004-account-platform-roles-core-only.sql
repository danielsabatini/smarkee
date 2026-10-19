-- Migração 0004 de core.account: o cadastro passa a conceder só roles do módulo `core` (decisão 0032).
-- Projeto: core-account-manager. Executada pela infraestrutura como o dono `smarkee`.
-- Remove de `desired.platformRoles` as roles que não são de `core` (as de `ipm.organization.*`
-- deixaram de ser concedidas no cadastro e saíram do projeto `roles-core`). Só o jsonb muda: sem nova
-- geração. Idempotente: depois da primeira execução nenhuma linha tem role fora de `core`.
-- Atenção: o `desired` já publicado no NATS não é reemitido; usuários existentes antes desta
-- migração devem ser recriados (não há usuários de produção).

UPDATE core.account
   SET desired = jsonb_set(
         desired,
         '{platformRoles}',
         (SELECT COALESCE(jsonb_agg(role ORDER BY role), '[]'::jsonb)
            FROM jsonb_array_elements_text(desired -> 'platformRoles') AS role
           WHERE role ~ '^core\.'))
 WHERE EXISTS (
         SELECT 1 FROM jsonb_array_elements_text(desired -> 'platformRoles') AS role
          WHERE role !~ '^core\.');
