-- Migração 0006 de sum."service": geração confirmada pela observação (decisões 0072 e 0080).
-- Aditiva e idempotente (expandir, `docs/POSTGRESQL.md` §15). `observed_generation` é a última
-- geração cuja convergência o Manager confirmou com uma observação feita depois dela, como o
-- `status.observedGeneration` do Kubernetes: nula até a primeira confirmação, só cresce e nunca
-- passa de `desired_generation`.

ALTER TABLE sum.service
  ADD COLUMN IF NOT EXISTS observed_generation bigint;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
     WHERE conname = 'service_observed_generation_check'
       AND conrelid = 'sum.service'::regclass
  ) THEN
    ALTER TABLE sum.service
      ADD CONSTRAINT service_observed_generation_check
      CHECK (observed_generation IS NULL
             OR (observed_generation >= 1 AND observed_generation <= desired_generation));
  END IF;
END
$$;

-- Registros existentes: a fase `Ready` só era gravada com a geração vigente convergida.
UPDATE sum.service
   SET observed_generation = desired_generation
 WHERE observed_generation IS NULL AND phase = 'Ready';
