# 0033 — Service Usage Manager (SUM): uso de serviços por usuário

- **Data:** 2026-10-15
- **Status:** Aceita (desenho). Depende da decisão 0032 (um projeto de roles por módulo e o `ORG_USER_CREATOR`).

## Contexto

O cadastro de usuário não concede mais as roles de `ipm.organization.*` (decisão 0032): o usuário passa a usar um serviço (hoje, a Organization do módulo `ipm`) só quando liga esse serviço. O SUM é o recurso que representa essa ligação e concentra a concessão e a revogação das roles de cada serviço, sem que o Executor do User conceda roles de outros módulos.

## Decisão

- **Módulo e tipo:** `sum` / `service`. O recurso é **o uso de um serviço por um usuário**: o par `ownerUserId` + `service`. Não há recurso por serviço compartilhado.
- **Escopo por usuário**, decidido pelo usuário. Um serviço ligado para um usuário não liga para os outros.
- **`resourceId`:** atribuído pelo Receiver (UUIDv7), como todo recurso (`docs/RESOURCE-CONTROL-LOOP.md`). A unicidade do par `ownerUserId` + `service` é regra do Receiver, que consulta o SSOT antes de aceitar o pedido.
- **API** (`/v1/sum/services`):

  | Método e rota | Efeito | Resposta |
  |---|---|---|
  | `POST /v1/sum/services` com `{"service": "ipm"}` | liga o serviço para o solicitante (`lifecycle = present`) | `202` com `resourceId` e `operationId`; `409` se o par já está ligado (com o `resourceId` existente) |
  | `GET /v1/sum/services/{resourceId}` | lê a ligação | `200`, `404` |
  | `GET /v1/sum/services` | lista as ligações do solicitante, paginada | `200` |
  | `DELETE /v1/sum/services/{resourceId}?resourceVersion=` | desliga (`lifecycle = absent`) | `202`, `409` com versão desatualizada |

  O solicitante só lê, lista e desliga as **próprias** ligações. A visão de operador (ler ligações de outros usuários) fica para depois, com a role `sum.service.admin`.
- **Catálogo serviço → roles:** fica na configuração do Manager do SUM (`SUM_MANAGER_SERVICE_ROLES`, JSON), como o `platformRoles` do User (decisão 0025). Exemplo: `{"ipm": ["ipm.organization.create", "ipm.organization.delete", "ipm.organization.get", "ipm.organization.list", "ipm.organization.update"]}`. O Manager copia as roles do catálogo para `desired.serviceRoles` no momento da ligação; o Executor não tem lista própria.
- **Roles base:** o cadastro concede `sum.ipm.enable`, `sum.ipm.disable` e `sum.ipm.get` (no projeto `roles-sum`, pelo Executor do User, que é `PROJECT_GRANT_OWNER` nesse Grant). Elas só permitem **pedir** a ligação; quem concede as roles do serviço (`ipm.organization.*`, no projeto `roles-ipm`) é o **Executor do SUM**, que é `PROJECT_GRANT_OWNER` só no Grant de `roles-ipm` (decisão 0032).
- **Administração fora desta fatia:** o kill switch (desligar um serviço para todos os usuários), a visão de operador e a revogação de acesso de um usuário são ações de operador e ficam para as ferramentas de administração (decisão 0025). O catálogo do Manager lista só os serviços disponíveis; não há campo para desligar um serviço.
- **Roles por ação, sem curinga:** o Receiver exige a role de ação (`sum.ipm.enable` para ligar, `sum.ipm.disable` para desligar, `sum.ipm.get` para ler e listar) e, além dela, que a ligação seja do solicitante. Nesta fatia não há operador do SUM: `sum.service.admin` e a regra de escopo da decisão 0031 ficam para depois.
- **Listar:** `GET /v1/sum/services` usa `sum.ipm.get`, porque não existe role `sum.ipm.list`. Se quiser uma role separada, ela entra no projeto `roles-sum` antes da implementação.
- **Consistência com a 0028:** `sum.<serviço>.<ação>` é a exceção documentada (o segundo segmento é o serviço). O `group` no Zitadel é `sum`.

- **Desligar um serviço desativa, não apaga:** desligar o serviço (`DELETE /v1/sum/services/{id}`) só revoga as roles do serviço. Os recursos que o usuário criou nele (por exemplo, as Organizations do `ipm`) **continuam existindo**, mas ficam inacessíveis até ele ligar o serviço de novo, e então voltam como estavam. Apagar esses recursos é uma estratégia à parte, a definir depois, e não faz parte desta fatia.
- **Token depois de ligar ou desligar (opção B):** o access token traz as roles da hora do login ou do refresh e vale 12 horas por padrão, então uma revogação só chega ao token no próximo refresh. Verificado no Zitadel de dev (2026-10-15): o refresh recalcula as roles, tanto na concessão quanto na revogação, e o token antigo mantém as roles até expirar. Decisão: encurtar o access token da instância para 15 minutos e fazer a CLI renovar sozinha pelo refresh token (hoje ela guarda o refresh token e não o usa, então depois de 12 horas o `sk whoami` pede novo login). A renovação automática entra com os comandos `sk sum`, e a validade só é encurtada junto com ela, para o `sk` não pedir login a cada 15 minutos. A validade é uma configuração de instância: `ZITADEL_DEFAULTINSTANCE_OIDCSETTINGS_ACCESSTOKENLIFETIME` na criação e, numa instância existente, a Admin API **v1** (`/admin/v1/settings/oidc`), porque não existe API v2 para essa configuração (exceção da seção 24.2 do `AGENTS.md`). Efeito: uma revogação vale em até 15 minutos, no pior caso. **Aplicado no dev em 2026-10-16** (`accessTokenLifetime` de `43200s` para `900s`, pela Admin API v1; os demais valores de OIDC ficaram como estavam), junto com a renovação automática da CLI (`sk auth whoami` e a espera de `--wait` também renovam). A suíte `identity/conformance` confere o valor.

## Consequências

- O Executor do User nunca concede `ipm.*`: as roles de serviço saem do Executor do SUM.
- Ligar um serviço vira um fluxo de duas etapas (o Manager decide, o Executor do SUM concede). O usuário vê a ligação `Ready` quando as roles aparecem no token, e a CLI renova o token depois de ligar ou desligar (`--wait`, ou `sk auth refresh`).
- Pendentes: os contratos de `requested-*`, o Executor do SUM, o Receiver e o restante da feature, a infraestrutura, a renovação automática na CLI e a estratégia de apagar os recursos do serviço.

## Atualização (2026-10-16): religar reaproveita o recurso

O recurso é o par `ownerUserId` + `service`, e não cada ligar. Ao pedir `POST /v1/sum/services` para um par que já tem uma linha **desligada**, o Receiver reaproveita o `resourceId` dela e o Manager liga a mesma linha de novo (`lifecycle = present`, geração e versão + 1); não nasce linha nova. Uma linha ligada continua `409` (`already_exists`), e o `resourceId` de outro dono ou serviço é recusado (`conflict`). Motivo: a implementação inicial criava um recurso por ligar, e a listagem acumulava uma linha desligada por ciclo. O histórico de cada ligar e desligar fica nas Operations. As linhas duplicadas que existiam antes, no dev, foram removidas na limpeza do ambiente.
