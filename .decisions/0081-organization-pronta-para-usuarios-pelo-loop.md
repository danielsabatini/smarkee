# 0081 — Organization pronta para usuários pelo loop, com o catálogo no contrato

- **Data:** 2026-10-21
- **Status:** Aceita e implementada em dev (etapa 7 do plano do incidente do catálogo do SUM). Fecha a lacuna declarada da decisão 0077 ("Roles e Project Grant são atividade do operador nesta etapa") e revisa a decisão 0038 ("o Executor escreve só a organização e não cria Project Grant") e a 0077 no catálogo do Receiver do User (`IPM_USER_RECEIVER_API_GRANTABLE_ROLES`).
- **Origem:** a jornada e2e de 2026-10-21 parou na criação de usuário: a Organization nova não tinha o Project Grant de `roles-ipm` nem os papéis das contas do `ipm/user`, e o Executor do User recebia `Rejected` do Zitadel. Direção do responsável: resolver pelo loop; o catálogo é definição do produto, e **não** fica em arquivo de configuração.

## Evidência (Zitadel de dev, v4.19.4, 2026-10-21)

Sonda descartável (`.workspace/org-grant/`), só com as chaves do Executor e do Observer da Organization, com a organização `probe-*` removida ao final:

- o papel de instância do Executor (`IAM_ORG_MANAGER`, decisão 0060) já tem `project.grant.write`, `org.member.write` e `project.grant.member.write` (`defaults.yaml` da v4.19.4): ele criou o Grant (`CreateProjectGrant`), mudou as roles (`UpdateProjectGrant`) e deu `ORG_USER_CREATOR` e `ORG_OWNER_VIEWER` na organização e `PROJECT_GRANT_OWNER` no Grant (`CreateAdministrator`). **Nenhum privilégio novo**;
- criar de novo responde `409 already_exists`; `UpdateProjectGrant` com as mesmas roles responde `200`;
- o Observer (`IAM_OWNER_VIEWER`) lê o Grant (`ListProjectGrants` com `inProjectIdsFilter.ids` e `grantedOrganizationIdFilter.id`, nomes do `query.proto` da v4.19.4) e os papéis (`ListAdministrators`, `user.id`);
- remover a organização leva o Grant e os papéis junto (0 restantes);
- pelo proto oficial, `UpdateProjectGrant` e `UpdateAdministrator` **substituem** o conjunto, e uma role retirada do Grant sai também das autorizações dos usuários.

## Decisão

1. **A Organization nasce pronta para usuários.** Como o namespace do Kubernetes que já vem com os RoleBindings dos controladores, e a conta nova da AWS que já vem com o papel de acesso da organização (referência de mercado, decisão 0071), o loop da `ipm/organization` cria, observa e repara:
   - o **Project Grant** de `roles-ipm` para a organização, com exatamente o catálogo;
   - os **papéis das contas do `ipm/user`**: o Executor do User com `ORG_USER_CREATOR` na organização e `PROJECT_GRANT_OWNER` no Grant; o Observer do User com `ORG_OWNER_VIEWER` na organização.
2. **Campo gerenciado `userAccess`** (aditivo e opcional) no `desired` (`grantRoles`, `userExecutorAccountId` e `userObserverAccountId`) e no `observed` (`grantRoles`, ausente sem Grant, e `administrators`). Só é reconciliado enquanto `platformAccess` é `granted`. Papéis a mais numa conta não são divergência: o Executor acrescenta o que falta e não retira o que a plataforma não gerencia.
3. **O catálogo é contrato, e não configuração:** o enum `grantableRole` em `schemas/ipm/definitions.v1.schema.json` (definições do módulo `ipm`, para não levar a um tipo as definições do outro), gerado nos modelos dos dois tipos. O Manager da Organization grava o catálogo no `desired`; o Receiver do User recusa antes do loop as roles fora dele. A configuração `IPM_USER_RECEIVER_API_GRANTABLE_ROLES` deixa de existir. Mudar o catálogo é mudar o schema, regerar os modelos e implantar: as duas cópias geradas não divergem, porque o teste de cada feature exige o modelo regerado.
4. **As contas são configuração de ambiente** (os IDs mudam por instância): só o Manager as recebe (`IPM_ORGANIZATION_MANAGER_USER_ACCESS_USER_EXECUTOR_ACCOUNT_ID` e `..._USER_OBSERVER_ACCOUNT_ID`) e as grava no `desired`; o Observer e o Executor só precisam do projeto (`IPM_ORGANIZATION_<PAPEL>_IDENTITY_PROJECT_ID`). Como na decisão 0079, o Executor lê o que fazer só do `desired`.
5. **Rollout na partida do Manager** (modelo da 0079): antes dos consumers, cada Organization presente cujo `desired` difere do `userAccess` de agora ganha geração nova, com Operation `update` de `system:catalog`. As Organizations de antes desta decisão ficam prontas sem o operador.
6. **Fora da visão pública:** o `observed.userAccess` traz IDs de contas de serviço da plataforma e fica fora da visão `resource` do Receiver (`x-resourceView: omitted`, conferido pelo teste dos schemas). O Receiver passa a montar o `observed` da visão campo a campo.

## Justificativa

- **Segurança:** nenhum privilégio novo (o Executor só usa o que a exceção da 0060 já concede); o Grant continua sendo o teto, e o Zitadel, a última barreira; o operador deixa de usar a conta de bootstrap para cada Organization.
- **Simplicidade:** um campo gerenciado a mais no loop que já existe, com a regra pura em `common/user_access.py`, usada pelo Manager e pelo Reconciler; o catálogo numa fonte só, sem leitura do provedor em runtime.
- **Robustez:** cada passo é idempotente (`409` tratado como já feito; união de papéis antes de `UpdateAdministrator`); o Grant vem antes do papel no Grant; a observação inconclusiva vira `unknown`.
- **Resiliência:** o rollout é idempotente por Organization, com a linha bloqueada; a remoção da organização leva o Grant e os papéis.
- **Alternativas descartadas:** o catálogo no `config.toml` (o responsável não quer catálogo em configuração; duas cópias divergiriam, como no incidente da 0079); o Receiver do User ler o Grant da Organization (exigiria `ipm.organization.get` dos usuários e exporia o catálogo e as contas na visão pública); ler o catálogo das roles do projeto no Zitadel (regra implícita e leitura a mais no provedor); um componente novo com papéis próprios (mais complexidade sem ganho de privilégio, porque o `IAM_ORG_MANAGER` já tem as permissões).

## Compatibilidade

- Contrato aditivo: `userAccess` é opcional no `desired` e no `observed`; um `desired` sem o campo não é reconciliado nesse ponto até o rollout acrescentá-lo. A versão dos schemas continua `1.0`, como na 0074 e na 0079.
- Configuração: o Receiver do User perde `api.grantable_roles` (sai do `config.toml`); a Organization ganha três variáveis no `.env` (`IPM_ORGANIZATION_IDENTITY_PROJECT_ID`, `IPM_ORGANIZATION_USER_EXECUTOR_ACCOUNT_ID` e `IPM_ORGANIZATION_USER_OBSERVER_ACCOUNT_ID`), conferidas pela suíte de conformidade da identidade.
- O índice `schemas/ipm.user.index.json` passa a aceitar um fragmento (`#/$defs/grantableRole`) para gerar o enum, que nenhum contrato do User referencia.

## Limitações declaradas

- Trocar a conta de uma das duas contas do `ipm/user` não retira os papéis da conta antiga: o Executor só acrescenta. A retirada é do operador, até haver necessidade.
- Com a organização desativada (`platformAccess = revoked`), o preparo não é reconciliado; volta a ser na reativação.

## Verificação (dev, 2026-10-21)

- Testes unitários de cada papel (regra pura, decisão do Reconciler, ações do Executor, observação, política e rollout do Manager, visão do Receiver), integração do rollout contra o SSOT real (só nas Organizations do teste) e o e2e do loop da Organization contra o Zitadel real: a Organization nova chega a `Ready` com o Grant do catálogo e os papéis das duas contas.
- Suíte de conformidade da identidade com os IDs novos dos `.env`.
