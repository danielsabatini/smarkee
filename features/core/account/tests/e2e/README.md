# core.account: testes e2e

Esta suíte é um **teste**, e não um componente (decisão 0017).

Testes **black-box** do contrato de `core.account` (decisões `0063` e `0098`):
exercitam o gateway, a API (HTTP), o transporte (NATS) e o SSOT pela rede, e validam as mensagens e as respostas contra
os JSON Schemas de `schemas/`. **Não importam o código dos componentes**, e por isso valem para qualquer
implementação, em qualquer linguagem.

Requer a stack de dev no ar (`infrastructure/dev`). Configuração, por variável de ambiente:

| Variável | Padrão | Uso |
|---|---|---|
| `CONFORMANCE_API_URL` | `http://localhost:8080` | Gateway da API |
| `CONFORMANCE_API_HOST` | `api-dev.smarkee.com.br` | Cabeçalho `Host` do gateway |
| `CONFORMANCE_MESSAGING_URL` | `nats://localhost:4222` | Servidor NATS |
| `CONFORMANCE_MESSAGING_PASSWORD` | (sem padrão; sem ela, os testes de mensageria são pulados) | Senha do NATS (`SMARKEE_MESSAGING_PASSWORD` de `messaging/.env`) |
| `CONFORMANCE_ACCESS_TOKEN` | (opcional) | Access token de um operador (`core.account.admin`); sem ele, os testes autenticados são pulados |
| `CONFORMANCE_MAILPIT_URL` | (opcional) | Interface do Mailpit (por exemplo, `http://localhost:8025`); sem ela, a verificação dos e-mails do Zitadel é pulada |
| `CONFORMANCE_DATABASE_HOST` / `_PORT` | `localhost` / `5432` | Leitura do `observed` e limpeza dos dados de teste (papéis de dev: `core_account_controller_login` e `core_maintenance_login`) |
| `E2E_CHAOS` | (vazio) | `1` habilita os testes de resiliência (derrubam contêineres) |

O gateway limita o cadastro anônimo a 10 por minuto por IP: o cliente de teste repete até 3 vezes um pedido recusado com `429`, esperando o `Retry-After`, e a suíte completa leva por isso alguns minutos.

A limpeza apaga o registro e o outbox direto no SSOT: a exclusão pela API só vale para a própria conta (`ResourcesNotVerifiable`, decisão 0100), e o token da suíte é de operador. O usuário no Zitadel sai por `scripts/dev/cleanup`.

Testes de resiliência (opt-in, `E2E_CHAOS=1`): `tests/test_chaos.py` derruba, com o `docker`, o Controller e o Publisher durante um cadastro e verifica que o trabalho não se perde e o loop converge quando o componente volta. Restauram o componente ao final.

```bash
uv sync
export CONFORMANCE_MESSAGING_PASSWORD=$(grep ^SMARKEE_MESSAGING_PASSWORD= ../../../../../infrastructure/dev/messaging/.env | cut -d= -f2)
uv run pytest
```
