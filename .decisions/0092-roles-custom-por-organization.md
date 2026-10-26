# 0092 — Roles `custom` por Organization

- **Data:** 2026-10-26
- **Status:** Aceita.
- **Origem:** pendência da `0089`, que separou `roleType` (`predefined` | `custom`) e deixou em aberto quem cria as Roles `custom` e com que alcance.

## Contexto

- Hoje `ipm.role` é um catálogo global: só o operador (`ipm.role.admin`) cria Roles e o nome é único na plataforma. Uma Organization não consegue definir uma composição própria de permissões.
- O `ipm.group` (decisões `0085` e `0088`) já resolve o mesmo problema para grupos: recurso preso a uma Organization, criado por operador, pelo dono (root) ou por membro com permissão, com cota e exclusão protegida.
- Referência de mercado (§2.7): `Role` (de namespace) e `ClusterRole` (global) do Kubernetes. A Role vive no namespace, referencia só o que o criador pode conceder (teto contra escalada: o `escalate` do RBAC) e o nome é único por namespace.

## Decisão

1. **Escopo.** Toda Role tem `organizationId`. As `predefined` (da plataforma) pertencem à Organization de sistema **`core`**; as `custom` pertencem a uma Organization real e são imutáveis nesse vínculo. `core` é reservada: o Manager recusa `custom` com `organizationId = core`. Mensagens antigas sem `organizationId` equivalem a `core`.
2. **Quem cria.** Mesmo modelo do `ipm.group`: operador (`ipm.role.admin`, qualquer Organization), dono (root) da Organization (confirmado no Receiver de `ipm/organization`) ou membro (confirmado no Receiver de `ipm/user`) com `ipm.role.create|update|delete|bind`. Leitura exige `ipm.role.get|list`. O Receiver recusa o que está fora da Organization do solicitante com `404`.
3. **Permissões novas.** `ipm.role.create|update|delete|bind` (delegáveis, `grantable = true`). `ipm.role.get|list` passam a delegáveis, para o membro enxergar as Roles que pode atribuir. `ipm.role.admin` segue só do operador.
4. **Teto contra escalada.** Uma Role `custom` só pode conter permissões delegáveis à Organization (`grantable`). O Receiver valida contra o catálogo de permissões (semente do contrato `GrantablePermission` mais as mudanças de `ipm.permission`, como no `ipm/user`). O operador também respeita o teto: a Role é da Organization e é expandida em `UserGrant` dela.
5. **Nome.** Único por Organization (`UNIQUE (organizationId, name)` entre as ativas) e **proibido** igual a uma `predefined`. Cada Organization vê as `predefined` mais as próprias, nunca as de outra.
6. **Cota e exclusão.** 10 `custom` por Organization (`OwnerQuota`, advisory lock, igual ao `group`). A exclusão é recusada com `409 ResourcesAttached` se algum usuário ou grupo da Organization usa a Role.
7. **Catálogos.** O catálogo de Roles de `ipm/user` (Receiver e Manager) e de `ipm/group` (Receiver e Manager) passa a indexar por `(organização, nome)`: `predefined` valem em qualquer Organization; `custom`, só na própria. A expansão de `roles` de usuário e de grupo considera a Organization do recurso.
8. **Plano de dados.** O Executor grava `organization_id` na tabela `ipm.role` do banco `platform` (já tem a coluna e `UNIQUE (organization_id, name)`, decisão `0086`).
9. **Correção do consumer do Receiver de `group`.** O `RoleCatalogConsumer` fazia `pull_subscribe_bind` num durable que ninguém criava e falhava a cada segundo (`ServiceUnavailableError`): o catálogo dinâmico de Roles do Receiver de `group` nunca funcionou. Passa a usar o `StateConsumer` (como o `ipm/user`). O Manager de `group` ganha o mesmo consumer, porque a regra `invalid` precisa conhecer as Roles `custom`.

## O que permanece, o que se acrescenta, o que se substitui (§2.6)

- Permanece: o loop, o `roleType`, os `resourceId` opacos, as `predefined` e o plano `platform`.
- Acrescenta: `organizationId`, cota, `ResourcesAttached`, as quatro permissões, o escopo nos catálogos e o consumer no Manager de `group`.
- Substitui: a unicidade global de nome (`role_active_name`) por unicidade por Organization, e o consumer defeituoso do Receiver de `group`.

## Migração e compatibilidade

- Migração `0004-role-organization.sql` (SSOT): grava `organizationId = core` no `desired` das `predefined`, troca o índice único e **falha** se existir Role `custom` sem Organization (não há como atribuí-la; nenhuma existe no dev). Não republica `desired`: leitores tratam a ausência como `core`.
- `ipm.permission`: as quatro permissões novas entram por migração e semente; a mudança `grantable` de `ipm.role.get|list` em ambiente existente é um `update` pela API (a semente cobre volumes novos).
- Contrato aditivo e tolerante na leitura. `organizationId` é obrigatório em criar (API e `requested`).

## Lacunas declaradas

- ~~Catálogos sem `ipm.group.*` e `ipm.role.*`~~ **(fechada)**: o Grant da Organization já acompanha `grantable = true` em tempo real (`PermissionCatalogWatcher`, `0083`), então só dois pontos estavam defasados: o catálogo do SUM (`SUM_SERVICE_MANAGER_CATALOG_PERMISSIONS`), de onde o root tira as permissões no token, e o enum semente `GrantablePermission`. Os dois foram estendidos, e um teste em `ipm/permission` compara o enum com as permissões `grantable` da semente. Em `stg`/`prd` falta apenas o provisionamento das roles `ipm.role.*` e `ipm.group.*` no Zitadel (Grant da `register` e autorização do operador), coberto pela suíte de conformidade da identidade.
- Roles `custom` removidas ou alteradas enquanto um usuário/grupo as referencia ficam sujeitas à corrida entre a checagem do Receiver e o pedido (mesma janela do `group`; o Manager reconfere cota e unicidade sob lock, e a checagem de permissão do Receiver é a de qualquer autorização por token); o rollout do catálogo reexpande as `permissions` dos usuários.
