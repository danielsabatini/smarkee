# Telemetria de dev: conformidade

Esta suíte é um **teste**, não um componente. Caixa-preta: faz um cadastro pelo gateway e lê os arquivos que o
`telemetry-gateway` grava (`logs/`, `traces/`). Exige a plataforma de dev no ar e o `docker` disponível para o último
teste. O cadastro cria um usuário `conf.telemetry-*@example.com`, que o `smarkee-dev-cleanup` remove.

| O que confere | Decisão |
|---|---|
| Um cadastro produz **um** span do gateway sem span pai e o **mesmo `trace_id`** nos logs de Receiver, Manager, Publisher, Reconciler e Executor | 0050, 0054, 0055 |
| `traceparent` e `tracestate` forjados pelo cliente são ignorados: o `trace_id` forjado não aparece em nenhum log nem span | 0054 |
| Os spans não têm `args`, `http.target` nem `url.full`, e todo valor de `url.query` é `REDACTED` | 0050 |
| Os logs de infra criados durante o teste não têm e-mail nem código de verificação | 0059 |
| Um cadastro anônimo carrega o contexto de negócio em cada hop: `smarkee.actor.type = anonymous`, sem `user.id`, `smarkee.resource.id` e `smarkee.operation.name = create` (Receiver, Manager, Reconciler e Executor) | 0061 |
| Os logs de app não têm e-mail e todo `user.id` é um identificador opaco | 0061 |
| Redação provada de forma determinística: um contêiner sintético de infra tem o e-mail trocado por `<redacted-email>`, e o `WARN` "missing translation" do Zitadel é descartado | 0059 |

Execução, na raiz deste diretório: `uv run pytest -q`. Variáveis opcionais: `CONFORMANCE_API_URL` (padrão
`http://localhost:8080`), `CONFORMANCE_API_HOST` (padrão `api-dev.smarkee.com.br`) e `CONFORMANCE_TELEMETRY_DIR`.

**Limite declarado:** os testes de dados sensíveis dos spans e dos logs de infra olham só o que foi gravado desde o início
do teste; o último teste existe justamente para o caso de o Zitadel deixar de gerar o aviso que o cadastro costuma
provocar.
