# 0099 — Fim do banco `platform`: Role e Grupo viram dado do SSOT

- **Data:** 2026-10-27
- **Status:** Aceita. **Revoga** as decisões `0086` (banco `platform`) e `0088` no que diz respeito ao plano de dados no banco `platform`; o restante da `0088` (identificação, nome, `roles`, vínculo com usuários, cota, `bind`) permanece. Consequência da `0098` (API síncrona) aplicada a `ipm/role` e `ipm/group` (etapa S4 do plano de evolução).
- **Origem:** o plano de dados `platform` existia para que um Executor aplicasse o estado de Role e Grupo e um Observer o lesse de volta. Role e Grupo não têm sistema externo: o próprio `desired` é o dado. O loop (Reconciler, Executor, Observer) só copiava o `desired` do SSOT para outro banco.

## Contexto

Conforme a `0086`, o banco `platform` seria o "sistema externo" de recursos próprios da Smarkee (Role, Grupo, e depois User, Group-member etc.). Na prática, só `ipm.role` e `ipm.group` o usaram. Para eles, o estado "real" era uma cópia normalizada do `desired`, sem divergência possível além da falha da própria cópia. O custo: um banco extra, 4 papéis de banco, 4 papéis de loop por tipo, backup, telemetria e uma classe de falhas (`ObservationStale`, `ExternalError`) para um dado que nunca saiu do nosso controle.

No modelo do Kubernetes (§2.7), um objeto cujo estado é só a sua especificação (ex.: `ConfigMap`, `Role`/`ClusterRole` do RBAC) é admitido e persistido pelo API server e não tem controlador: está pronto ao ser gravado.

## Decisão

1. **O banco `platform` deixa de existir.** `ipm.role` e `ipm.group` vivem só no SSOT (`ssot`), com `api` + `publisher` (decisão `0098`). O recurso nasce `Ready` com `observedGeneration = generation`; o `DELETE` remove a linha e publica o tombstone (`lifecycle = "absent"`).
2. **Consultas relacionais** (usuários de um Grupo, Roles de um Grupo, permissões de uma Role) são feitas sobre o `desired` (`jsonb`) no SSOT, ou por leitura na API do tipo dono. Se uma carga futura exigir um modelo relacional normalizado, ele nasce como **projeção derivada do SSOT**, reconstruível a partir do outbox, e não como fonte de verdade paralela.
3. **Papéis:** `ipm_role_{executor,observer,reconciler,manager,receiver}` e `ipm_group_{...}` do loop antigo deixam de ser usados; os de plano de dados (`*_executor`, `*_observer`) são removidos de `infrastructure/dev/database/bootstrap/ipm.sql`.
4. **Infraestrutura:** removidos `bootstrap/platform.sql`, o `GRANT CONNECT` do papel `telemetry`, o banco na coleta de métricas (`telemetry-agent`) e no backup (`scripts/dev/backup`).
5. **Dev ativo:** `DROP DATABASE platform` (com dump prévio em `.workspace/`) e `DROP ROLE` do dono e dos papéis de plano de dados.

## Compatibilidade (§10, §31)

- O estado do banco `platform` era derivado do SSOT (o `desired` de cada recurso), então não há dado exclusivo a migrar.
- Contratos HTTP e de mensageria de Role e Grupo seguem a `0098`; o `observed` deixa de ser publicado para esses tipos.
- `bsm/account` não é afetado (decisão `0082`).

## Consequências

- Um banco, um conjunto de papéis, um backup e uma classe de falhas a menos.
- Em `stg`/`prd` nunca será criado: nada a provisionar.
- As lacunas declaradas da `0086` (senhas triviais, mesmo servidor, `CONNECT` público) deixam de existir; sai a linha correspondente de `docs/platform/IMPLEMENTATION-STATUS.md`.

## Referência

Kubernetes: objetos cujo estado é só a especificação não têm controlador e são persistidos na admissão. Sem divergência em relação a isso.
