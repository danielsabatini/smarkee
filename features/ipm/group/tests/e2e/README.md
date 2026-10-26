# ipm.group: testes e2e

Esta suíte é um **teste**, e não um componente (decisão 0017).

Testes **black-box** do contrato de `ipm.group` (decisões `0015`, `0063` e `0088`):
exercitam o Receiver (HTTP), o transporte (NATS) e o SSOT pela rede, e validam as mensagens e as respostas contra
os JSON Schemas de `schemas/`. **Não importam o código dos componentes**, e por isso valem para qualquer
implementação, em qualquer linguagem.

Requer a stack de dev no ar (`infrastructure/dev`). Configuração, por variável de ambiente:

| Variável | Padrão | Uso |
|---|---|---|
| `CONFORMANCE_API_URL` | `http://localhost:8080` | Gateway do Receiver |
| `CONFORMANCE_API_HOST` | `api-dev.smarkee.com.br` | Cabeçalho `Host` do gateway |
| `CONFORMANCE_MESSAGING_URL` | `nats://localhost:4222` | Servidor NATS |
| `CONFORMANCE_MESSAGING_PASSWORD` | (sem padrão; sem ela, os testes de mensageria são pulados) | Senha do NATS (`SMARKEE_MESSAGING_PASSWORD` de `messaging/.env`) |
| `CONFORMANCE_ACCESS_TOKEN` | (opcional) | Access token de um usuário com as permissões de ação; sem ele, os testes autenticados são pulados |
| `CONFORMANCE_DATABASE_HOST` / `CONFORMANCE_DATABASE_PORT` | `localhost` / `5432` | PostgreSQL (limpeza ao final do teste) |
| `CONFORMANCE_DATABASE_PASSWORD` / `CONFORMANCE_MAINTENANCE_PASSWORD` | (opcional) | Senha de `ipm_group_manager_login` ou `ipm_maintenance_login`; com uma delas, os registros de teste são removidos ao final |

```bash
cd features/ipm/group/tests/e2e
uv sync
set -a; source ../../../../../infrastructure/dev/messaging/.env; source ../../../../../infrastructure/dev/database/.env; set +a
CONFORMANCE_MESSAGING_PASSWORD="$SMARKEE_MESSAGING_PASSWORD" \
CONFORMANCE_MAINTENANCE_PASSWORD="$SMARKEE_POSTGRES_IPM_MAINTENANCE_PASSWORD" \
  uv run pytest
```
