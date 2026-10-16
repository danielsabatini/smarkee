# ipm.organization: testes e2e

Esta suíte é um **teste**, e não um componente (decisão 0017).

Testes **black-box** do contrato de `ipm.organization` (`.decisions/0015-componentes-por-papel-autocontidos.md`):
exercitam o Receiver (HTTP), o transporte (NATS) e o SSOT pela rede, e validam as mensagens e as respostas contra
os JSON Schemas de `schemas/`. **Não importam o código dos componentes**, e por isso valem para qualquer
implementação, em qualquer linguagem.

Requer a stack de dev no ar (`infrastructure/dev`). Configuração, por variável de ambiente:

| Variável | Padrão | Uso |
|---|---|---|
| `CONFORMANCE_API_URL` | `http://localhost:8080` | Gateway do Receiver |
| `CONFORMANCE_API_HOST` | `api-dev.smarkee.com.br` | Cabeçalho `Host` do gateway |
| `CONFORMANCE_NATS_URL` | `nats://localhost:4222` | Servidor NATS |
| `CONFORMANCE_NATS_PASSWORD` | (sem padrão; sem ela, os testes de mensageria são pulados) | Senha do NATS (`NATS_PASSWORD` de `broker/.env`) |
| `CONFORMANCE_ACCESS_TOKEN` | (opcional) | Access token de um usuário com as roles de ação; sem ele, os testes autenticados são pulados |
| `CONFORMANCE_DATABASE_HOST` / `_PORT` | `localhost` / `5432` | Limpeza dos dados de teste (papéis de dev) |

```bash
uv sync
export CONFORMANCE_NATS_PASSWORD=$(grep ^NATS_PASSWORD= ../../../../../infrastructure/dev/broker/.env | cut -d= -f2)
uv run pytest
```
