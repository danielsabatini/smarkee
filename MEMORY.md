# Memória Operacional do Projeto (AI Context)

Em conformidade com o `AGENTS.md` (§35.1): só o que o próximo agente precisa saber agora. Histórico em `.journal/` (local, não versionado); regras e decisões em `AGENTS.md`, `docs/` e `.decisions/`.

## Estado atual (2026-10-21)
- Enviado para `origin/dev` até a decisão 0075. **Sem commit:** decisões 0076 e 0077, a feature `features/ipm/user` (loop, CLI `sk ipm user`, e2e, docs), a `ipm/organization` aceitando usuários e só removendo vazia, o catálogo do SUM com `ipm.user.*`, a correção do `deletionProtection` na visão `resource` (Organization e Account) e da espera do `--wait` em pedido recusado.
- Zitadel de dev já provisionado para o `ipm.user` (roles, Grant da `register`, contas `ipm-user-*` e chaves no volume). Script do operador por organização: `.workspace/ipm-user/provision.py organization <roles-ipm> <org>` (descartável; o passo a passo oficial está em `infrastructure/dev/README.md`).

## Próximos passos
1. Commit e push do `ipm/user`, quando o responsável pedir.
2. Verificar ponta a ponta o caminho do root no `ipm/user` e o `delete` da Organization com usuários (exigem o token de um root real; hoje só testes unitários).
3. Telemetria (achados da auditoria): 401 do gateway como warn; rodar o caos do `sum` com token de teste.

## Pendências herdadas (não reverificadas hoje)
- Antes de stg/prd: `pinned_client`; controle de versão das migrações (`*-migrate` reaplicam tudo); allowlist de caminhos do Zitadel; substituir papéis de instância dos executors; `restore/reset --apply` do backup nunca rodados no dev ativo.
- Decisão 0006: regras de nome de namespace do OpenBao. Validar em ambiente real as ACLs/Streams do `docs/NATS.md`.

## Armadilhas
- Recriar um Receiver exige reiniciar o gateway (cache de DNS).
- `docker compose up --build` numa feature falha ao reconstruir `*-migrate` (apk sem rede); use `docker compose build <feature>-observer` e `up -d --no-build <papéis>`.
- Resíduo de testes: `scripts/dev/cleanup`; sinais em disco: `scripts/dev/telemetry-reset --apply`.
