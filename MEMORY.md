# Memória Operacional do Projeto (AI Context)

Em conformidade com o `AGENTS.md` (§35.1): só o que o próximo agente precisa saber agora. Histórico em `.journal/` (local, não versionado); regras e decisões em `AGENTS.md`, `docs/` e `.decisions/`.

## Estado atual (2026-10-21)
- Enviado para `origin/dev` até a decisão 0079 (`470f417`: etapas 1 e 2 do plano). **Sem commit:** etapa 3 (decisão 0080).
- Zitadel de dev já provisionado para o `ipm.user` (roles, Grant da `register`, contas `ipm-user-*` e chaves no volume). Script do operador por organização: `.workspace/ipm-user/provision.py organization <roles-ipm> <org>` (descartável; o passo a passo oficial está em `infrastructure/dev/README.md`).

## Próximos passos
Plano de 7 etapas aceito em 2026-10-21 (incidente do catálogo do SUM). Etapas 1 (decisão 0078) e 2 (decisão 0079) feitas e enviadas. Próximas, na ordem:
3. ~~SUM no modelo do loop~~: feito (decisão 0080: perfil `manager-handlers`, `removes_absent`, migração 0006 aplicada no dev), **sem commit**. Falta a ida e volta pela API, que fica com a etapa 5.
5. e2e da jornada com a CLI real (conta → ipm → Organization → 5 usuários → cota → "só vazia" → apagar), com login sem navegador para teste.
4. Operation `failed` no limite/prazo e `superseded` na substituída (contrato aditivo).
6. Higiene: testes de integração sem vazar para o loop no ar; limpeza reconhecer usuário removido; lint antigo (`cleanup/main.py`, `backup/model.py`); READMEs "sem arquivo de configuração"; procedimento de troca de catálogo; supressão de logs repetitivos por recurso; trace novo por tentativa com link (quando houver spans).
7. Project Grant por Organization pelo loop (fecha a lacuna da 0077).

## Pendências herdadas (não reverificadas hoje)
- Antes de stg/prd: `pinned_client`; controle de versão das migrações (`*-migrate` reaplicam tudo); allowlist de caminhos do Zitadel; substituir papéis de instância dos executors; `restore/reset --apply` do backup nunca rodados no dev ativo.
- Decisão 0006: regras de nome de namespace do OpenBao. Validar em ambiente real as ACLs/Streams do `docs/NATS.md`.

## Armadilhas
- Recriar um Receiver exige reiniciar o gateway (cache de DNS).
- `docker compose up --build` numa feature falha ao reconstruir `*-migrate` (apk sem rede); use `docker compose build <feature>-observer` e `up -d --no-build <papéis>`.
- Resíduo de testes: `scripts/dev/cleanup`; sinais em disco: `scripts/dev/telemetry-reset --apply`.
