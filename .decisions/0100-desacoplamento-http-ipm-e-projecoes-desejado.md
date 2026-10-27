# 0100 — Desacoplamento HTTP entre features de IPM via projeções locais do stream DESIRED

- **Data:** 2026-10-27
- **Status:** Aceita. Consequência da etapa S5 do plano de evolução `ipm/*` (`~/.opencode/plan/ipm-resource-control-loop-evolution.md`). Revoga chamadas HTTP mútuas entre features estabelecidas nas decisões `0040`, `0077`, `0088`, `0092` e `0094`.

## Contexto

As features de `ipm/*` realizavam até 20 chamadas HTTP síncronas entre si para:
1. Validar dono e ciclo de vida da Organization (`OrganizationPeer` em `role`, `group`, `user`, `serviceaccount`).
2. Validar a Organization à qual o solicitante pertence (`UserPeer` consultando `users` e `serviceaccounts`).
3. Verificar uso de Roles antes da exclusão (`RoleUsagePeer` em `role` consultando `users`, `groups`, `serviceaccounts`).
4. Verificar vínculo de Grupos a Usuários antes da exclusão (`UserPeer` em `group` consultando `users`).
5. Verificar presença de dependentes da Organization antes da exclusão (`has_users` consultando `users` e `serviceaccounts`).

Esse acoplamento gerava ciclos de dependência temporal e falhas em cascata (`503 Service Unavailable`) quando um serviço parceiro reiniciava ou sofria instabilidade transitória de rede.

No modelo de controladores do Kubernetes (§2.7), cada componente consome streams/informers de recursos correlatos e constrói **projeções locais em memória**, sem consultar a API de terceiros para verificações operacionais rotineiras.

## Decisão

1. **Eliminação de chamadas HTTP mútuas em `ipm/*`:**
   - Nenhuma feature de `ipm/*` pode realizar chamadas HTTP síncronas para outra feature de `ipm/*`. O CI local (`scripts/dev/check`) passa a auditar e impedir chamadas HTTP cruzadas e configurações de peers internos entre features de `ipm/*`.
2. **Projeções locais em memória alimentadas pelo stream `DESIRED`:**
   - **`OrganizationProjection`:** `role`, `group`, `user` e `serviceaccount` mantêm em memória o dono (`ownerAccountId`) e o ciclo de vida (`lifecycle == "present"`) das Organizations a partir de `manager.desired.ipm.organization.>`.
   - **`MemberProjection`:** `organization`, `role`, `group`, `user` e `serviceaccount` mantêm o pertencimento de membros (usuários e service accounts) a Organizations a partir de `manager.desired.ipm.user.>` e `manager.desired.ipm.serviceaccount.>`.
   - **`RoleUsageProjection`:** `role` rastreia atribuições ativas de roles em `user`, `serviceaccount` e `group`. O `DELETE` em `ipm/role` recusa sincronamente com `409 Conflict` (`ResourcesAttached`) caso a Role esteja em uso.
   - **`GroupUsageProjection`:** `group` rastreia vínculos ativos de usuários a grupos via `user`. O `DELETE` em `ipm/group` recusa sincronamente com `409 Conflict` (`ResourcesAttached`) se houver usuários no grupo.
   - **`DependentsProjection`:** `organization` rastreia todos os recursos dependentes ativos (`user`, `serviceaccount`, `group`, `role`).
3. **Bloqueio de exclusão por dependentes no Controller:**
   - Na API de `organization`, o `DELETE` recusa sincronamente com `409 Conflict` (`ResourcesAttached`) se houver dependentes ativos no momento da admissão.
   - No `OrganizationController`, se o recurso estiver em `lifecycle == "absent"` mas possuir dependentes remanescentes no cache, o controller não apaga no Zitadel nem no SSOT e atualiza o recurso com a condition `DeletionBlockedByDependents=True` (motivo `DependentsRemaining`, fase `Deleting`).
   - A `DependentsProjection` re-enfileira a Organization na workqueue do controller assim que dependentes são removidos (`on_change`).
4. **Prontidão (`/health/ready`):**
   - As APIs e Controllers só reportam prontidão (`200 OK`) após a sincronização inicial das projeções (`StateConsumer.is_synced`), garantindo consistência eventual antes de atender tráfego de requisições.

## Consequências

- Acoplamento temporal eliminado entre as 6 features de `ipm/*`.
- Respostas de admissão em milissegundos sem I/O de rede redundante.
- Garantia de que recursos não são excluídos deixando órfãos ou vínculos inválidos no sistema externo (Zitadel).
