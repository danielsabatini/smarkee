# ipm.group: testes e2e

Esta suíte é um **teste**, e não um componente (decisão 0017).

Testes **black-box** do contrato de `ipm.group` (decisões `0015`, `0063`, `0088` e `0098`): exercitam a API (HTTP), o transporte (NATS) e o SSOT pela rede, e validam as mensagens e as respostas contra os JSON Schemas de `schemas/`. **Não importam o código dos componentes**, e por isso valem para qualquer implementação, em qualquer linguagem.

Requer a stack de dev no ar (`infrastructure/dev`). Configuração, por variável de ambiente:

| Variável | Padrão | Uso |
|---|---|---|
| `CONFORMANCE_API_URL` | `http://localhost:8080` | Gateway da API |
| `CONFORMANCE_API_HOST` | `api-dev.smarkee.com.br` | Cabeçalho `Host` do gateway |
| `CONFORMANCE_MESSAGING_URL` | `nats://localhost:4222` | Servidor NATS |
| `CONFORMANCE_MESSAGING_PASSWORD` | (sem padrão; sem ela, os testes de mensageria são pulados) | Senha do NATS (`SMARKEE_MESSAGING_PASSWORD` de `messaging/.env`) |
| `CONFORMANCE_ACCESS_TOKEN` | (sem padrão; sem ele, os testes autenticados são pulados) | Access token de um operador (decisão 0098: os pedidos entram pela API) |
| `CONFORMANCE_DATABASE_HOST` / `_PORT` | `localhost` / `5432` | Limpeza dos dados de teste (papéis de dev) |

```bash
uv sync
export CONFORMANCE_MESSAGING_PASSWORD=$(grep ^SMARKEE_MESSAGING_PASSWORD= ../../../../../infrastructure/dev/messaging/.env | cut -d= -f2)
export CONFORMANCE_ACCESS_TOKEN=<token de operador>
uv run pytest
```

- `tests/test_loop.py` exercita o fluxo completo pela API HTTP: o Grupo nasce `Ready` (`POST` 201), é atualizado (`PATCH` 200), a remoção é recusada enquanto protegida e, desprotegida, é apagada (`DELETE` 202); em cada passo confere o `desired` entregue pelo Publisher (inclusive o tombstone). Cada Grupo de teste é removido pela API ao final.
- `tests/test_conformance.py` confere a recusa sem token e o corpo com campo desconhecido, no contrato `api-error`.

O Grupo não tem Controller, Observer nem Executor (decisão 0098, S4): não há testes de resiliência de papéis além do Publisher, cobertos pelos testes de integração dele.
