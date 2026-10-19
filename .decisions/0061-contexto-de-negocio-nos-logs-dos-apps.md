# 0061 — Contexto de negócio nos logs dos apps (quem, recurso, ação, dono, organização)

- **Data:** 2026-10-19
- **Status:** Aceita e implementada em desenvolvimento para os **logs**. Os spans do gateway e as métricas seguem nas etapas 2 e 3 do plano. Estende as decisões 0045, 0055 e 0059.
- **Origem:** pedido do responsável: a observabilidade dos **apps** deve ter identificação de quem pediu, recurso e ação em todos os sinais, para o drill-down; a **infra** não, porque atende vários clientes; e isso **não é auditoria**.

## Contexto

Em 2026-10-18 verificou-se que a telemetria não era multitenant: nenhum evento de log trazia o ator (o `user.id` era permitido pelo schema e nunca usado), o recurso e a ação apareciam só em alguns eventos e de forma desigual entre as três features (o `sum` registrava menos), e não havia dono nem organização. Numa simulação com três donos, só 48% dos logs de app eram atribuíveis a um dono, e por heurística.

## Decisão

- **Um contexto único por requisição ou mensagem** no `logging_config.py` (a fonte única, decisão 0046), que estende o mecanismo do `traceparent` (decisão 0055): ator, tipo do ator, recurso, ação, dono e organização, emitidos como atributos de log. O que o evento informa explicitamente prevalece sobre o contexto.
- **Atributos:** `user.id` (já permitido), `smarkee.actor.type` (`user|anonymous|service|system`), `smarkee.resource.id`, `smarkee.operation.name`, `smarkee.owner.id` e `smarkee.organization.id`. O schema valida o formato: identificador opaco (sem `@` nem `.`), então e-mail e nome nunca passam.
- **Preenchimento:** o Receiver, na autenticação e ao publicar; Manager, Reconciler e Executor, a partir do envelope, no ponto em que já ligavam o `traceparent`; o Publisher, a partir da linha do outbox; o Reconciler guarda e restaura o contexto ao reavaliar. Mensagem sem solicitante registrado é `system`; o Observer é sempre `system`.
- **Desconhecido é omitido** (padrão OpenTelemetry); o tipo do ator, de baixa cardinalidade, é sempre explícito quando há contexto. **`anonymous` quer dizer não autenticado**, e não anonimizado.
- **Privacidade:** o ator é **pseudonimizado** (id opaco, o `sub`), porque o drill-down exige identificador estável; o que não precisa ligar a ninguém é **anonimizado** (e-mail, nome, código: nunca em sinal de app). Hash com chave (HMAC) fica como passo aditivo posterior.
- **Em métricas, só o tipo do ator** e dimensões de baixa cardinalidade: id de ator, recurso e organização viram série ilimitada.
- **Quem executou** não ganha atributo: o `service.name` do Resource já é o nome da conta de serviço.

## Justificativa

- **Segurança:** o ator vem só do dado validado; o formato proíbe e-mail e nome; verificado por teste.
- **Simplicidade e evolução aditiva (§2.6):** reaproveita o mecanismo do `traceparent` e os pontos de ligação existentes; nenhum componente novo; `bind_traceparent` continua iniciando um contexto novo, então os `finally` dos 18 componentes não mudaram.
- **Robustez:** o contexto é auxílio de diagnóstico: uma mensagem ilegível é ignorada, nunca causa falha; igualou as três features.

## Verificação (2026-10-19)

- 18 componentes com `ruff`, `pyright` e testes unitários verdes; a suíte de conformidade da telemetria (7 testes) confere, para um cadastro anônimo, ator `anonymous`, recurso e ação `create` em cada hop e nenhum e-mail nem `user.id` fora do formato; jornada com a CLI real 12 de 12 e as e2e dos três módulos nos mesmos números de antes.
- Simulação com três donos e cinco organizações: **99% dos logs de app com tipo de ator** (sistema 51%, usuário 33%, anônimo 12%), `user.id` por conta e `smarkee.organization.id` por organização, nenhum `user.id` com formato de e-mail. A primeira medição (63%) apontou três lacunas, corrigidas: o `evaluate` do Reconciler apagava o contexto (agora restaura), mensagens sem solicitante ficavam sem tipo (agora `system`) e o ator só era ligado ao publicar (agora na autenticação).

## Consequências

- **Limites:** o span do gateway e as métricas ainda não têm o contexto. Nas mensagens de estado, a ação do envelope é `changed`; o fato `updated` não traz `requestedBy` e fica `system`; o dono só aparece onde a mensagem o traz.
- **Cuidado operacional descoberto:** depois de recriar um Receiver (novo IP), o gateway pode seguir para o IP antigo até o cache de DNS expirar; houve `405` vindo de outro contêiner. Reinicie o gateway ou aguarde (nota no README da infra).
- Mais dado pessoal pseudonimizado na telemetria: a retenção curta e a base legal em prd precisam ser definidas antes de guardar (ator e IP), com confirmação do jurídico.
