# Memória Operacional do Projeto (AI Context)

Em conformidade com o `AGENTS.md` (§35.1): só o que o próximo agente precisa saber agora. Histórico em `.journal/` (local, não versionado); regras e decisões em `AGENTS.md`, `docs/` e `.decisions/`.

## Estado atual (2026-10-21)
- Etapas 1, 2, 3, 5 e 7 do plano feitas e enviadas para `origin/dev`. Etapa 7 = decisão 0081: a Organization nasce pronta para usuários pelo loop (Grant de `roles-ipm` e papéis das contas `ipm-user-*`), catálogo no enum `grantableRole` (`schemas/ipm/definitions.v1.schema.json`). Jornada `tests/e2e` 12/12 contra o dev.
- O script do operador `.workspace/ipm-user/provision.py organization` não é mais necessário (o loop faz).
- `.opencode/opencode.json` é local e ignorado: traz a URL do Postgres com o superusuário em texto puro e `npx -y` sem versão. Decisão pendente do responsável: papel de leitura para o MCP (não existe papel de leitura de dados no dev). A alteração da skill `postgresql` que cita o MCP está sem commit (não verificada).
- Último backup do dev: `~/.smarkee/backups/20261021T224500Z` (depois da 0081, ambiente limpo). O banco `gateway` (resto do Kong) foi removido; o dump está em `~/.smarkee/gateway-kong-leftover-20261021.dump`.

## Próximos passos
Plano de 7 etapas aceito em 2026-10-21 (incidente do catálogo do SUM). Faltam, na ordem:
4. Operation `failed` no limite/prazo e `superseded` na substituída (contrato aditivo).
6. Higiene: testes de integração sem vazar para o loop no ar (os do Manager da Organization criam organizações `acme-*`/`org-*`/`dup-*` no Zitadel pelo loop no ar); limpeza reconhecer usuário removido; lint antigo (`cleanup/main.py`, `backup/model.py`); READMEs "sem arquivo de configuração"; procedimento de troca de catálogo; supressão de logs repetitivos por recurso; trace novo por tentativa com link (quando houver spans).
- Não rodado depois da 0081: o e2e da feature `ipm/user` (`features/ipm/user/tests/e2e`) e os testes de caos da Organization (`E2E_CHAOS=1`).

## Pendências herdadas (não reverificadas hoje)
- Antes de stg/prd: `pinned_client`; controle de versão das migrações (`*-migrate` reaplicam tudo); allowlist de caminhos do Zitadel; substituir papéis de instância dos executors; `restore/reset --apply` do backup nunca rodados no dev ativo.
- Decisão 0006: regras de nome de namespace do OpenBao. Validar em ambiente real as ACLs/Streams do `docs/NATS.md`.

## Armadilhas
- Recriar um Receiver exige reiniciar o gateway (cache de DNS).
- `docker compose up --build` numa feature falha ao reconstruir `*-migrate` (apk sem rede); use `docker compose build <feature>-observer` e `up -d --no-build <papéis>`.
- Resíduo de testes: `scripts/dev/cleanup`; sinais em disco: `scripts/dev/telemetry-reset --apply`.
