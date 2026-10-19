# Memória Operacional do Projeto (AI Context)

Em conformidade com o `AGENTS.md` (§35.1): só o que o próximo agente precisa saber agora. Histórico em `.journal/` (local, não versionado); regras e decisões em `AGENTS.md`, `docs/` e `.decisions/`.

## Estado atual (2026-10-19)
- **Sem commit (dev):** contexto de recurso nos logs dos observers das 3 features (`observation_context` em `observer/engine/observer.py`, com testes), `scripts/dev/telemetry-reset` (novo) e entradas no `CHANGELOG.md`. Rode ruff/pyright/pytest nas features antes de commitar.
- **Organização ativa na CLI:** feita e enviada (`sk config set ipm.organizationId`; `create --wait` grava se não houver ativa).

## Próximos passos
1. ADR `.decisions/0066-ipm-member.md` (fecha 0039 §5): membro = vínculo Account↔Organization só no SSOT (sem escrita no Zitadel), identificação por e-mail com resposta neutra, só papel `admin`, última admin não removível (409), dono vira o primeiro membro, `organization delete` exige org vazia. Depois a feature `features/ipm/member` (roteiro `docs/FEATURE-BOOTSTRAP.md`) e `sk ipm organization member add|list|remove` usando a org ativa.
2. Telemetria (achados da auditoria): 401 do gateway como warn; rodar o caos do `sum` com token de teste.

## Pendências herdadas (não reverificadas hoje)
- Antes de stg/prd: `pinned_client`; controle de versão das migrações (`*-migrate` reaplicam tudo); allowlist de caminhos do Zitadel; substituir papéis de instância dos executors; `restore/reset --apply` do backup nunca rodados no dev ativo.
- Decisão 0006: regras de nome de namespace do OpenBao. Validar em ambiente real as ACLs/Streams do `docs/NATS.md`.

## Armadilhas
- Recriar um Receiver exige reiniciar o gateway (cache de DNS).
- `docker compose up --build` numa feature falha ao reconstruir `*-migrate` (apk sem rede); use `docker compose build <feature>-observer` e `up -d --no-build <papéis>`.
- Resíduo de testes: `scripts/dev/cleanup`; sinais em disco: `scripts/dev/telemetry-reset --apply`.
