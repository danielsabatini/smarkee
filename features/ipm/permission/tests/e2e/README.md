# ipm.permission: testes e2e

Esta suíte é um **teste**, e não um componente (decisão 0017).

Testes **black-box** do contrato de `ipm.permission` (decisões `0015`, `0063`, `0083`, `0096` e `0098`): exercitam a API (HTTP), o transporte (NATS) e o SSOT pela rede, e validam as mensagens e as respostas contra os JSON Schemas de `schemas/`. **Não importam o código dos componentes**, e por isso valem para qualquer implementação, em qualquer linguagem.

Requer a stack de dev no ar (`infrastructure/dev`). Configuração, por variável de ambiente:

| Variável | Padrão | Uso |
|---|---|---|
| `CONFORMANCE_API_URL` | `http://localhost:8080` | Gateway da API |
| `CONFORMANCE_API_HOST` | `api-dev.smarkee.com.br` | Cabeçalho `Host` do gateway |
| `CONFORMANCE_MESSAGING_URL` | `nats://localhost:4222` | Servidor NATS |
| `CONFORMANCE_MESSAGING_PASSWORD` | (sem padrão; sem ela, os testes de mensageria são pulados) | Senha do NATS (`SMARKEE_MESSAGING_PASSWORD` de `messaging/.env`) |
| `CONFORMANCE_ACCESS_TOKEN` | (sem padrão; sem ele, os testes autenticados são pulados) | Access token de um operador com `ipm.permission.admin` (decisão 0098: os pedidos entram pela API) |
| `CONFORMANCE_DATABASE_HOST` / `_PORT` | `localhost` / `5432` | Limpeza dos dados de teste (papéis de dev) |
| `E2E_CHAOS` | (vazio) | `1` habilita os testes de resiliência (derrubam contêineres) |

```bash
uv sync
export CONFORMANCE_MESSAGING_PASSWORD=$(grep ^SMARKEE_MESSAGING_PASSWORD= ../../../../../infrastructure/dev/messaging/.env | cut -d= -f2)
export CONFORMANCE_ACCESS_TOKEN=<token de operador>
uv run pytest
```

- `tests/test_loop.py` exercita o fluxo completo pela API HTTP e pelo Zitadel de dev: a Permission nasce `Pending` (`POST` 201), o Publisher entrega o `desired` e o Controller cria a role no projeto `roles-<módulo>`; em seguida é atualizada (`PATCH` 200), a remoção é recusada enquanto protegida e, desprotegida, é removida (`DELETE` 202) até o registro sair do SSOT. Cada Permission de teste é removida pela API ao final; sem isso, sobrariam roles no Zitadel.
- `tests/test_conformance.py` confere a recusa sem token e o corpo com campo desconhecido, no contrato `api-error`.
- Resiliência (opt-in, `E2E_CHAOS=1`): `tests/test_chaos.py` derruba, com o `docker`, o Publisher e o Controller durante a criação e verifica que o loop converge quando o componente volta.
