# 0097 — `desired` puro e permissões efetivas calculadas pelo Controller

- **Data:** 2026-10-27
- **Status:** Aceita. Substitui o rollout de Roles por mutação do `desired` (decisão 0083, parte do rollout; decisões 0088 e 0091 no que dizem respeito a `system:catalog`). Conforme AGENTS.md §2.1 (#2 Simplicidade, #3 Robustez), §2.7 (Kubernetes: `spec` é intenção, `status` é o calculado/observado) e §25.1.

## Contexto

`ipm/user` e `ipm/serviceaccount` gravavam no `desired` as `permissions` expandidas das `roles` (e, no `user`, dos `groups`). Quando uma Role, um Grupo ou uma permissão delegável mudava, o Manager reescrevia o `desired` de **todos** os recursos afetados: uma geração nova por recurso, uma Operation `update` com `requestedBy = system:catalog` (que podia substituir, como `superseded`, Operations reais do usuário) e uma mensagem `desired` por recurso. Misturava **intenção** (o que o cliente pediu: `roles`, `groups`) com **estado calculado** (o resultado da expansão), contra o §13 do AGENTS.md.

## Decisão

1. **`desired` só tem intenção.** `permissions` sai do `desired` de `ipm/user` e `ipm/serviceaccount`; ficam `roles` e, no `user`, `groups`. Mudar uma Role ou um Grupo não altera mais o `desired`, a `desired_generation` nem as Operations.
2. **`observed.effectivePermissions`** (novo) traz as permissões que o Controller calculou do catálogo (`roles` + `groups` → permissões delegáveis) e que reconcilia no provedor. `observed.permissions` continua sendo o que o provedor tem de fato; as duas coincidem quando o recurso converge.
3. **O Controller consome os catálogos.** Além do `DESIRED` do próprio tipo, o Controller consome `DESIRED` de `ipm.permission`, `ipm.role` e `ipm.group` (um consumer por instância, `DeliverLastPerSubject`), mantém o `AccessCatalog` em memória e **só inicia os workers depois que todos os consumers sincronizaram**: um catálogo incompleto revogaria permissões no provedor.
4. **Índices reversos.** O Controller mantém, só dos recursos da própria partição, `role -> {resourceId}` e `(organização, grupo) -> {resourceId}`, atualizados pelas mensagens `desired` do tipo. Um evento de catálogo reenfileira apenas os afetados (Role: quem a tem direta ou por Grupo; Grupo: seus membros; permissão: quem tem uma Role que a contém). O `reconcile` recalcula `effectivePermissions` a partir do `desired` lido do SSOT e do catálogo, decide contra o provedor e grava o resultado: geração e Operations ficam intactas.
5. **Fim do `role_rollout`.** `manager/handlers/role_rollout.py` e os consumers de catálogo do Manager saem. A regra `invalid` (permissão fora do módulo `ipm.`) deixa de existir no Manager: o catálogo só contém permissões `ipm.` e o Receiver já recusa Roles não atribuíveis.

## Compatibilidade (§10, §31)

- **Contrato `desired` e `resource` (API):** o campo `permissions` é removido. Consumidores no repositório: CLI `sk` e Console, ambos migrados para `observed.effectivePermissions`. Cliente externo que lia `desired.permissions` deve ler `observed.effectivePermissions`.
- **Dados já gravados:** a migração `0006` remove `permissions` do `desired` no SSOT. O Manager também descarta a chave legada se a encontrar (leitor tolerante), de modo que a ordem entre migração e *deploy* não importa.
- **Evento `updated` e Stream `UPDATED`:** inalterados.
- **Mensagens `desired` antigas** no Stream (com `permissions`) continuam legíveis: o Controller as lê como mapa, sem modelo estrito.

## Consequências

- Editar uma Role ou um Grupo converge os usuários e service accounts afetados sem tocar o `desired`: `desired_generation` permanece.
- Uma edição de Role passa a custar uma reconciliação por afetado no Controller (observa o provedor), e não uma escrita de `desired` mais um ciclo completo.
- O Controller passa a depender dos Streams de catálogo (ACL de consumo em `docs/messaging/NATS.md`, a revisar na S6).
- Com a decisão 0096, o Manager de `user` e `serviceaccount` só trata pedidos (`requested`).

## Referência

Kubernetes: `spec` é a intenção do usuário e `status` o observado/calculado pelo controller; os controllers usam *informers* de objetos relacionados e mapeiam seus eventos para a chave do objeto dono (`EnqueueRequestsFromMapFunc`). Diverge ao manter o índice reverso em memória por partição, sem `Owns`/campo indexado de cache, porque o estado completo já é reconstruído da mensageria na partida.
