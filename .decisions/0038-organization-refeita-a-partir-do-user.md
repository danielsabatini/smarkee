# 0038 — Organization refeita a partir do User: só a organização no Zitadel

- **Data:** 2026-10-16
- **Status:** Aceita e implementada em dev (loop completo, verificado contra o Zitadel v4.19.4).

## Contexto

A feature `features/ipm/organization` era o desenho anterior: Receiver e Manager só para `requested`, `relay/` em vez de `publisher/`, `conformance/` em vez de `tests/e2e`, sem Reconciler, Observer e Executor. A feature `features/core/user` já estava no padrão das decisões 0015, 0017, 0018, 0019 e 0020, e o SUM já havia sido refeito a partir dela. O desenho original da Organization (decisão 0010 e `docs/loop/RESOURCE-CONTROL-LOOP.md`, seção 46) previa dois passos no Executor: criar a organização e criar o Project Grant do projeto da plataforma para ela.

## Decisão

- **A Organization segue a estrutura do User:** seis papéis (`receiver`, `manager`, `publisher`, `reconciler`, `observer`, `executor`) e `tests/e2e`, cada um autocontido, com a saúde `/health/live|ready|startup` e a documentação no padrão da decisão 0024. O `relay/` virou `publisher/` e o papel de banco `ipm_organization_relay`, `ipm_organization_publisher`.
- **O Executor escreve só a organização no Zitadel**, e não cria Project Grant. O Grant só terá sentido quando houver usuários da Organization com roles da plataforma (a Organization de hoje só tem o dono, que vive na organização `core` e já tem as roles de ação). Sem ele, o Executor também não autoriza ninguém.
- **O `resourceId` é o ID da organização no Zitadel** (`organizationId` informado na criação), então repetir a criação não duplica. Verificado na v4.19.4: ID repetido e nome repetido respondem `409`; o Executor então lê a organização pelo ID e só considera sucesso se ela existe com o nome esperado.
- **`platformAccess` vira o estado da organização:** `granted` mantém a organização ativa e `revoked` a desativa (`DeactivateOrganization`, reversível por `ActivateOrganization`). O `observed` informa `platformAccess` por esse estado (`active` ↔ `granted`) e `organizationState`. Com isso, `platformAccess` continua sendo a intenção de acesso do contrato comum, sem depender de um Grant.
- **Operações, pela API v2 de organizações** (`zitadel.org.v2.OrganizationService`, a mais nova e estável, `AGENTS.md` §24.2): criar (`POST /v2/organizations`), renomear (`POST /v2/organizations/{id}`), ativar e desativar (`.../activate`, `.../deactivate`), remover (`DELETE /v2/organizations/{id}`) e ler (`ListOrganizations`, pela rota Connect, consulta pelo ID). Comportamentos medidos: renomear para o mesmo nome, ativar uma ativa e desativar uma desativada respondem `400` (`FailedPrecondition`) com ID de erro estável (`ORG-4VSdf`, `EVENT-bfnrh`, `EVENT-Dbs2g`), tratados como "já feito"; remover uma ausente responde `200`; a rota REST `POST /v2/organizations/search` colide com a de atualização (trata `search` como ID), por isso a leitura usa a rota Connect.
- **O Observer lê, e `absent` só com uma consulta bem-sucedida e vazia:** qualquer erro (permissão, indisponibilidade, limite) e um estado desconhecido são `unknown`, nunca `absent`.
- **Contas de serviço** (na organização `core`, chaves no volume `identity-bootstrap`, uma por componente):

  | Conta | Papel | Observação |
  |---|---|---|
  | `ipm-organization-executor` | `IAM_ORG_MANAGER` (instância) | a antiga `core-organization-executor`, renomeada (mesmo ID e mesma chave) |
  | `ipm-organization-observer` | `IAM_OWNER_VIEWER` (instância) | nova, somente leitura |

- **Mensageria:** o `ACTION` já cobre `ipm.organization` (partição pelo `resourceId`); o Manager usa os consumers `ipm-organization-manager-{requested,observed,result}` e o Executor, `ipm-organization-executor-action-p0..p3`.

## Justificativa

- **Segurança:** menor escrita possível (só a organização), sem criar usuário nem conceder roles. O dono, o nome e a posse ficam no SSOT; o Zitadel só guarda o que precisa (ID, nome e estado).
- **Simplicidade:** a Organization reaproveita a estrutura e os testes do User e do SUM; sem Grant, o Executor tem três operações e nenhuma ordem de passos.
- **Robustez e resiliência:** a idempotência vem do ID informado e da leitura antes de escrever; o estado é reconstruído da mensageria; os testes de caos derrubam cada papel e o loop converge.
- **Alternativas descartadas:** manter o Project Grant (sem usuários da Organization não há o que delegar, e o Executor ganharia um segundo sistema de escrita e uma ordem de passos para reparar); representar `revoked` removendo a organização (destrutivo e irreversível); estreitar já os papéis de instância (o Zitadel v4.19.4 não tem papel menor para criar e listar organizações, e papéis customizados ficam para antes de prd).

## Consequências

- **Papéis largos:** `IAM_ORG_MANAGER` e `IAM_OWNER_VIEWER` são de instância e enxergam mais que as organizações da plataforma; estreitar com papéis customizados antes de prd (decisões 0010 e 0015).
- **`docs/loop/RESOURCE-CONTROL-LOOP.md` §46** passa a descrever só a organização (sem o passo do Project Grant); o contrato `schemas/ipm/organization/observed` tem a descrição de `platformAccess` ajustada (ativa ↔ `granted`).
- **Limitação:** o nome `register` (organização do Zitadel) não está entre os nomes reservados, então o pedido é aceito pelo Manager e falha no Executor (`Rejected`).
- **Fora do escopo:** administradores, usuários e Agents, Project Grant por organização, recursos derivados (OpenBao, Kubernetes) e retenção da remoção.
