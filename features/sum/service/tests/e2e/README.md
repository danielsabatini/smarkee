# sum.service: testes e2e

Esta suíte é um **teste**, e não um componente (decisão 0017).

Testes **black-box** do contrato de `sum.service` (decisão 0033): exercitam o Receiver (HTTP) e o SSOT
pela rede, e validam os exemplos e as respostas contra os JSON Schemas de `schemas/sum/service/` e
`schemas/common/`. **Não importam o código dos componentes**.

## O que cada grupo cobre

| Grupo | Precisa de | Verifica |
|---|---|---|
| Exemplos (`test_example_is_valid_against_its_schema`) | Nada | Os exemplos versionados validam contra os schemas. |
| Receiver sem token ou com token inválido | Gateway no ar (o Receiver não precisa responder) | `401` com o contrato de erro. |
| Corpo inválido | Gateway, Receiver e um token | `400` com `ValidationFailed`. |
| Loop completo (ligar, listar, duplicar, desligar) | Stack do SUM no ar e um token com `sum.ipm.*` | Operation até `completed`, fases `Ready`, roles concedidas e revogadas, `409` no duplicado, e a Operation, a ligação e a listagem validadas contra os schemas. |
| Caos (`tests/test_chaos.py`, com `E2E_CHAOS=1`) | Stack do SUM no ar, um token e acesso ao `docker` | Derruba o Manager, o Executor e o Publisher durante um pedido de ligação, e reinicia o Reconciler e o Observer no meio de uma ligação pendente; o pedido aceito converge. Restaura o componente e desliga o serviço ao final. |

Não cobre (declarado, não verificado):
- **Mensageria direta** (publicar `requested` no NATS): não há teste. Publicar um `requested` com dono
  fictício faria o Executor tentar conceder roles a um usuário inexistente e deixaria retries em dev.
  O loop completo cobre o mesmo caminho com um usuário real.
- **Operador** (`sum.service.admin`, visão de todas as ligações): fora do escopo.

## Configuração

Por variável de ambiente:

| Variável | Padrão | Uso |
|---|---|---|
| `CONFORMANCE_API_URL` | `http://localhost:8080` | Gateway do Receiver |
| `CONFORMANCE_API_HOST` | `api-dev.smarkee.com.br` | Cabeçalho `Host` do gateway |
| `CONFORMANCE_ACCESS_TOKEN` | (opcional) | Access token de um solicitante com `sum.ipm.enable`, `sum.ipm.disable` e `sum.ipm.get`, com audience `roles-sum`. Sem ele, os testes autenticados são pulados |
| `CONFORMANCE_SUM_MANAGER_DATABASE_URL` | (opcional) | Conexão do papel `sum_service_manager_login` (apaga a ligação de teste) |
| `CONFORMANCE_SUM_MAINTENANCE_DATABASE_URL` | (opcional) | Conexão do papel `sum_service_maintenance_login` (apaga as linhas de apoio). Sem as duas, a limpeza é pulada e as linhas ficam no SSOT |
| `E2E_CHAOS` | (vazio) | `1` habilita os testes de caos (derrubam contêineres do SUM) |

O token é de vida curta e não é gerado por esta suíte: obtenha-o de um solicitante de teste e nunca o cole em arquivos versionados. A CLI (`sk sum service`) renova o próprio token pelo refresh token, e a sessão dela não é usada aqui.

## Como rodar

```bash
uv sync
uv run pytest
```

O loop completo deixa a ligação desligada ao final. Se ele falhar no meio, a ligação pode ficar ligada:
desligue-a pela API antes de repetir o teste.
