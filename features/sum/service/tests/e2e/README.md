# sum.service: testes e2e

Esta suíte é um **teste**, e não um componente (decisão 0017).

Testes **black-box** do contrato de `sum.service` (decisões `0033` e `0098`): exercitam a API (HTTP)
e o SSOT pela rede, e validam os exemplos e as respostas contra os JSON Schemas de
`schemas/sum/service/` e `schemas/common/`. **Não importam o código dos componentes**.

## O que cada grupo cobre

| Grupo | Precisa de | Verifica |
|---|---|---|
| Exemplos (`test_example_is_valid_against_its_schema`) | Nada | Os exemplos versionados validam contra os schemas. |
| API sem token ou com token inválido | Gateway no ar (a API não precisa responder) | `401` com o contrato de erro. |
| Corpo inválido | Gateway, API e um token | `400` com `ValidationFailed`. |
| Loop completo (ligar, listar, duplicar, desligar, religar) | Stack do SUM no ar e um token com `sum.ipm.*` de um dono com conta de cobrança | `201`/`202` com o recurso, fases `Ready` com a geração confirmada, permissões concedidas e revogadas, `409 AlreadyEnabled` no duplicado, reaproveitamento do recurso na religação, e o recurso e a listagem validados contra os schemas. |
| Caos (`tests/test_chaos.py`, com `E2E_CHAOS=1`) | Stack do SUM no ar, um token e acesso ao `docker` | Derruba o Controller e o Publisher durante uma ligação e reinicia o Controller no meio dela; a ligação admitida converge. Restaura o componente e desliga o serviço ao final. |

Não cobre (declarado, não verificado):
- **Mensageria direta** (publicar o `desired` no NATS): não há teste. Publicar um `desired` com dono
  fictício faria o Controller tentar conceder permissões a um usuário inexistente e deixaria
  tentativas em dev. O loop completo cobre o mesmo caminho com um usuário real.
- **Remoção da conta** (o Controller apaga as ligações do dono, decisão 0044): coberta pelo teste de
  integração do Controller, não por esta suíte.
- **Operador** (`sum.service.admin`, visão de todas as ligações): fora do escopo.
- Esta suíte não foi executada contra a stack real nesta etapa (declarado em
  `docs/platform/IMPLEMENTATION-STATUS.md`).

## Configuração

Por variável de ambiente:

| Variável | Padrão | Uso |
|---|---|---|
| `CONFORMANCE_API_URL` | `http://localhost:8080` | Gateway da API |
| `CONFORMANCE_API_HOST` | `api-dev.smarkee.com.br` | Cabeçalho `Host` do gateway |
| `CONFORMANCE_ACCESS_TOKEN` | (opcional) | Access token de um solicitante com `sum.ipm.enable`, `sum.ipm.disable` e `sum.ipm.get`, com audience `roles-sum`. Sem ele, os testes autenticados são pulados |
| `CONFORMANCE_SUM_CONTROLLER_DATABASE_URL` | (opcional) | Conexão do papel `sum_service_controller_login` (apaga a ligação de teste já desligada) |
| `CONFORMANCE_SUM_MAINTENANCE_DATABASE_URL` | (opcional) | Conexão do papel `sum_service_maintenance_login` (apaga o outbox de teste). Sem as duas, a limpeza é pulada e as linhas ficam no SSOT |
| `E2E_CHAOS` | (vazio) | `1` habilita os testes de caos (derrubam contêineres do SUM) |

O token é de vida curta e não é gerado por esta suíte: obtenha-o de um solicitante de teste e nunca o cole em arquivos versionados. A CLI (`sk sum service`) renova o próprio token pelo refresh token, e a sessão dela não é usada aqui.

## Como rodar

```bash
uv sync
uv run pytest
```

O loop completo deixa a ligação desligada ao final. Se ele falhar no meio, a ligação pode ficar ligada:
desligue-a pela API antes de repetir o teste.
