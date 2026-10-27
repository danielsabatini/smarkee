# ipm.user: testes e2e

Esta suíte é um **teste**, e não um componente (decisão 0017).

Testes **black-box** do contrato de `ipm.user` (decisões `0063` e `0077`): exercitam o gateway, o transporte (NATS) e o SSOT pela rede, e validam as mensagens contra os JSON Schemas de `schemas/`. **Não importam o código dos componentes**.

Requer a stack de dev no ar (`infrastructure/dev`) e uma Organization `Ready`: o loop da `ipm/organization` já a prepara (Project Grant de `roles-ipm` e os papéis do Controller do User, decisão 0081). Configuração, por variável de ambiente:

| Variável | Padrão | Uso |
|---|---|---|
| `CONFORMANCE_API_URL` | `http://localhost:8080` | Gateway do Receiver |
| `CONFORMANCE_API_HOST` | `api-dev.smarkee.com.br` | Cabeçalho `Host` do gateway |
| `CONFORMANCE_MESSAGING_URL` | `nats://localhost:4222` | Servidor NATS |
| `CONFORMANCE_MESSAGING_PASSWORD` | (sem padrão; sem ela, os testes de mensageria são pulados) | Senha do NATS (`SMARKEE_MESSAGING_PASSWORD` de `messaging/.env`) |
| `CONFORMANCE_ORGANIZATION_ID` | (sem padrão; sem ela, o loop é pulado) | Organization preparada pelo operador |
| `CONFORMANCE_DATABASE_HOST` / `_PORT` | `localhost` / `5432` | Limpeza dos dados de teste (papéis de dev) |

```bash
uv sync
export CONFORMANCE_MESSAGING_PASSWORD=$(grep ^SMARKEE_MESSAGING_PASSWORD= ../../../../../infrastructure/dev/messaging/.env | cut -d= -f2)
export CONFORMANCE_ORGANIZATION_ID=<resourceId da Organization preparada>
uv run pytest
```

- `tests/test_loop.py` fecha o loop com os componentes reais e o Zitadel de dev: os pedidos entram direto no NATS (como o Receiver os publicaria), o usuário é criado na Organization sem senha, recebe e troca de permissões, é protegido e, ao final, removido pelo próprio loop. Também confirma que o Project Grant é o teto: uma permissão do `roles-ipm` fora do Grant é recusada pelo Zitadel (`Rejected`).
- `tests/test_conformance.py` confere a recusa sem token, no contrato `api-error`.

Os testes de resiliência (derrubar papéis) não são repetidos aqui: os motores do Controller e os handlers do Manager vêm do template (decisões 0075 e 0096) e são exercitados pelos e2e de `core/account` e `ipm/organization`.
