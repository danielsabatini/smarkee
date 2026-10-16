-- Migração 0005 de core.account: o cadastro passa a conceder as roles base do SUM (decisão 0033).
-- Projeto: core-account-manager. Executada pela infraestrutura como o dono `smarkee`.
-- Acrescenta a `desired.platformRoles` de quem tem acesso concedido (`platformAccess = granted`) as
-- roles que permitem pedir a ligação de um serviço: `sum.ipm.disable`, `sum.ipm.enable` e
-- `sum.ipm.get`. Só o jsonb muda: sem nova geração. Idempotente: a união não repete role.
-- Atenção: o `desired` já publicado no NATS não é reemitido; usuários existentes antes desta
-- migração devem ser recriados (não há usuários de produção).

UPDATE core.account
   SET desired = jsonb_set(
         desired,
         '{platformRoles}',
         (SELECT jsonb_agg(role ORDER BY role)
            FROM (SELECT jsonb_array_elements_text(desired -> 'platformRoles') AS role
                  UNION
                  SELECT unnest(ARRAY['sum.ipm.disable', 'sum.ipm.enable', 'sum.ipm.get'])) AS roles))
 WHERE desired ->> 'platformAccess' = 'granted'
   AND NOT (desired -> 'platformRoles' ?& ARRAY['sum.ipm.disable', 'sum.ipm.enable', 'sum.ipm.get']);
