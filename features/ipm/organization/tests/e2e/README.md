# ipm.organization: testes e2e

Esta suíte é um **teste**, e não um componente (decisão 0017).

Testes **black-box** do contrato de `ipm.organization` (`.decisions/0015-componentes-por-papel-autocontidos.md` e `.decisions/0063-um-componente-por-feature-com-um-entrypoint-por-papel.md`):
exercitam o Receiver (HTTP), o transporte (NATS) e o SSOT pela rede, e validam as mensagens e as respostas contra
os JSON Schemas de `schemas/`. **Não importam o código dos componentes**, e por isso valem para qualquer
implementação, em qualquer linguagem.

Requer a stack de dev no ar (`infrastructure/dev`). Configuração, por variável de ambiente:

| Variável | Padrão | Uso |
|---|---|---|
| `CONFORMANCE_API_URL` | `http://localhost:8080` | Gateway do Receiver |
| `CONFORMANCE_API_HOST` | `api-dev.smarkee.com.br` | Cabeçalho `Host` do gateway |
| `CONFORMANCE_MESSAGING_URL` | `nats://localhost:4222` | Servidor NATS |
| `CONFORMANCE_MESSAGING_PASSWORD` | (sem padrão; sem ela, os testes de mensageria são pulados) | Senha do NATS (`MESSAGING_PASSWORD` de `messaging/.env`) |
| `CONFORMANCE_ACCESS_TOKEN` | (opcional) | Access token de um usuário com as roles de ação; sem ele, os testes autenticados são pulados |
| `CONFORMANCE_DATABASE_HOST` / `_PORT` | `localhost` / `5432` | Limpeza dos dados de teste (papéis de dev) |
| `E2E_CHAOS` | (vazio) | `1` habilita os testes de resiliência (derrubam contêineres) |

```bash
uv sync
export CONFORMANCE_MESSAGING_PASSWORD=$(grep ^MESSAGING_PASSWORD= ../../../../../infrastructure/dev/messaging/.env | cut -d= -f2)
uv run pytest
```

`tests/test_loop.py` fecha o loop com os componentes reais e o Zitadel de dev: os pedidos entram direto no NATS (como o Receiver os publicaria, sem token), a organização é criada, renomeada, desativada e reativada (`platformAccess`) e removida pelo próprio loop, e o Observer confirma cada passo. Cada Organization de teste é removida pelo loop ao final; sem isso, sobrariam organizações no Zitadel.

Testes de resiliência (opt-in, `E2E_CHAOS=1`): `tests/test_chaos.py` derruba, com o `docker`, cada um dos papéis (Manager, Publisher, Reconciler, Observer e Executor) durante um pedido e verifica que o trabalho não se perde e o loop converge quando o componente volta. Restauram o componente ao final.
