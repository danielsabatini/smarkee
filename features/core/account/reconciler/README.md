# core-account-reconciler

Reconciler de `core.account` (`core-account-reconciler`), componente autocontido (`.decisions/0015-componentes-por-papel-autocontidos.md`).

Compara o último `desired` e o último `observed` de cada Account e decide a `action` (`create`, `update` ou `delete`), publicada em `reconciler.action.core.account.<id>.<operação>` com `Nats-Msg-Id` igual ao `actionId` (determinístico: `<id>.<geração>.<operação>.<observação>`). **Não executa** e **não acessa o SSOT**: o estado é um cache em memória, reconstruído da mensageria por consumers de estado da própria instância (`DeliverLastPerSubject`, nome único por execução, `inactive_threshold`).

Regras (`docs/RESOURCE-CONTROL-LOOP.md` e `docs/RESOURCE-CONTROL-SECURITY.md`): não decide sem os dois estados, com `observed` inconclusivo (`unknown`) ou desatualizado (mais estrito para `delete`), nem com `desired` suspenso; não reemite `action` pendente antes do prazo; espera a observação causada por `completed` ou `failed`; aplica *backoff* após falha; reavalia periodicamente, com jitter. A decisão é uma função pura (`domain/decision.py`); `engine/reconciler.py` mantém o estado e publica; `transport/nats.py` fala com o NATS; `http/health.py` expõe `/health/*` (decisões 0017 e 0018).

A `action` é publicada no Subject canônico `reconciler.action.core.account.<id>.<operação>`; o Stream `ACTION` o armazena com o token da partição (decisão 0018).

Campos gerenciados da Account: `lifecycle`, `platformAccess` e `platformRoles` (as desejadas contidas nas observadas) (`schemas/core/account/desired.v1.schema.json`).

## Configuração

Variáveis `CORE_ACCOUNT_RECONCILER_<SEÇÃO>_<CAMPO>`. Obrigatória, sem default: `CORE_ACCOUNT_RECONCILER_NATS_PASSWORD`. Os parâmetros do loop (`LOOP_*`) têm como padrão os `x-resourceParameters` do contrato.

## Desenvolvimento

```bash
uv sync
uv run ruff check . && uv run ruff format --check . && uv run pyright
uv run pytest
uv run datamodel-codegen   # regera contracts/generated.py a partir de schemas/
```
