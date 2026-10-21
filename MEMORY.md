# Memória Operacional do Projeto (AI Context)

Em conformidade com o `AGENTS.md` (§35.1): só o que o próximo agente precisa saber agora. Histórico em `.journal/` (local, não versionado); regras e decisões em `AGENTS.md`, `docs/` e `.decisions/`.

## Estado atual (2026-10-21)
- Enviado para `origin/dev` até a decisão 0075. **Sem commit:** decisões 0076 e 0077, a feature `features/ipm/user` (loop, CLI `sk ipm user`, e2e, docs), a `ipm/organization` aceitando usuários e só removendo vazia, o catálogo do SUM com `ipm.user.*`, a correção do `deletionProtection` na visão `resource` (Organization e Account) e da espera do `--wait` em pedido recusado.
- Zitadel de dev já provisionado para o `ipm.user` (roles, Grant da `register`, contas `ipm-user-*` e chaves no volume). Script do operador por organização: `.workspace/ipm-user/provision.py organization <roles-ipm> <org>` (descartável; o passo a passo oficial está em `infrastructure/dev/README.md`).

## Próximos passos
Plano de 7 etapas aceito em 2026-10-21 (incidente do catálogo do SUM). Feito, **sem commit**: etapa 1 (decisão 0078: ação sem efeito com backoff, `Progressing`/`progressDeadline` nas 3 features do template), log-level por processo e resumo da configuração na partida, mais os nomes de exibição das roles no Zitadel e a regra na conformidade. Próximas, na ordem:
2. ~~Catálogo do SUM com fonte única~~: feito (decisão 0079, `managedRoles` e rollout na partida do Manager), **sem commit**.
3. SUM no modelo do loop (`observed_generation`, `Progressing`; medir a entrada nos perfis do template).
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
