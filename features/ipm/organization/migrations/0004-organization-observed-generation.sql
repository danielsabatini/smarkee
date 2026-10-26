-- Migração 0004 de ipm.organization: geração confirmada pela observação (decisão 0072).
-- Aditiva e idempotente (expandir, `docs/data/POSTGRESQL.md` §15). `observed_generation` é a última
-- geração cuja convergência o Manager confirmou com uma observação feita depois dela, como o
-- `status.observedGeneration` do Kubernetes: nula até a primeira confirmação, só cresce e nunca
-- passa de `desired_generation`.

ALTER TABLE ipm.organization
  ADD COLUMN IF NOT EXISTS observed_generation bigint;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'organization_observed_generation_check'
       AND conrelid = 'ipm.organization'::regclass
  ) THEN
    ALTER TABLE ipm.organization
      ADD CONSTRAINT organization_observed_generation_check
      CHECK (observed_generation IS NULL
             OR (observed_generation >= 1 AND observed_generation <= desired_generation));
  END IF;
END
$$;

-- Registros existentes: a fase `Ready` só era gravada com a geração vigente convergida.
UPDATE ipm.organization
   SET observed_generation = desired_generation
 WHERE observed_generation IS NULL AND phase = 'Ready';
