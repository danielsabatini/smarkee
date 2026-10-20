# 0074 — Proteção contra exclusão como metadado no provedor de identidade

- **Data:** 2026-10-20
- **Status:** Aceita e implementada em `ipm.organization` (metadado da organização) e `core.account` (metadado do usuário). Detalha a decisão 0043 e usa a estrutura de drivers da decisão 0073.
- **Origem:** pedido do responsável pelo projeto: olhando para o Zitadel, não havia nenhum sinal de que o recurso está protegido; o objeto no provedor deve ficar coerente com o SSOT, e controles que não são nativos do Zitadel devem poder ser acrescentados.

## Contexto

Depois da decisão 0072, a proteção percorria o loop, mas era campo da plataforma (`x-managed: false`): o provedor não a tinha, o Reconciler nunca agia e a observação só confirmava a geração. No console do Zitadel não aparecia nada sobre a proteção.

## Evidência da API (AGENTS §9, §24.2)

- **Documentação oficial:** a API v2 tem `SetOrganizationMetadata` (`POST /v2/organizations/{id}/metadata`), `ListOrganizationMetadata` (`POST …/metadata/search`) e `DeleteOrganizationMetadata`, e os equivalentes do usuário em `zitadel.user.v2.UserService` (`/v2/users/{id}/metadata`). As APIs v1 de metadado estão marcadas como obsoletas. A gravação sobrescreve só as chaves enviadas, e o valor vai em base64.
- **Verificado no Zitadel de dev (v4.19.4), 2026-10-20**, com sondas descartáveis, recursos temporários e limpeza ao final:
  - o corpo é `{"metadata": [{"key", "value"}]}`; repetir a gravação responde 200 (idempotente);
  - a leitura devolve o valor em base64, e o filtro `{"keyFilter": {"key": …}}` funciona;
  - apagar uma chave inexistente responde `Rejected` com `META-2npds`;
  - as contas atuais bastam, sem mudar permissão: o Executor de Organization (`IAM_ORG_MANAGER`) e o de Account (`ORG_USER_CREATOR` na `register`) gravam; os Observers (`IAM_OWNER_VIEWER` e `ORG_OWNER_VIEWER`) leem.

## Decisão

- **`deletionProtection` passa a `x-managed: true`** no `desired` da Organization e da Account, e entra no `observed` (campo opcional).
- **Chave e valor no provedor:** metadado `deletionProtection` com o texto `true` ou `false`, o mesmo nome do campo do contrato.
- **Executor:** depois de `create` e de `update`, as `actions` gravam o metadado a partir do `desired` (registro sem o campo vale `true`). O `delete` não grava: a organização ou o usuário sai com o metadado.
- **Observer:** lê o metadado junto com o recurso. `true`/`false` viram o booleano do `observed`. Ausente, ou com outro valor, fica **fora** do `observed`: o Reconciler o vê como divergência e o Executor o regrava. Não se inventa valor. Falha de leitura é `unknown`, como qualquer leitura.
- **Reconciler e Manager:** a comparação e a convergência passam a incluir `deletionProtection`. Uma divergência gera `update` (`Drift`).
- **Drivers:** `executor/drivers/metadata.py` (`set_value`) e `observer/drivers/metadata.py` (`get_value`), um para organização e usuário (o dono é informado na construção: `organizations` ou `users`). São idênticos nas duas features e vivem no template, perfil `identity-metadata` (decisão 0064).
- **Fonte da verdade e segurança:** o SSOT continua sendo a fonte. O `delete` continua verificado no Receiver e no Manager a partir do `desired` (decisão 0043). O metadado **informa** o provedor e é corrigido pelo loop se alguém o alterar no console; ele **não impede** que um administrador do Zitadel apague o recurso direto no console.

## Justificativa

- **Um único modo (decisão 0072):** a proteção agora é reconciliada como qualquer campo gerenciado: o Executor age, o Observer lê e o Reconciler compara.
- **Explícito (§3):** o console do Zitadel mostra a particularidade, e quem olha o provedor sabe que o recurso está protegido.
- **Robustez:** um metadado alterado ou apagado fora do loop é detectado como drift e corrigido.
- **Caminho aditivo (§2.6):** os recursos que já existem não têm o metadado e são corrigidos pelo próprio loop na primeira observação. Nada a migrar à mão.

## Consequências

- **Contrato (aditivo):** `deletionProtection` opcional no `observed` da Organization e da Account; anotação `x-managed` alterada no `desired`.
- **Comportamento:** um recurso existente sem o metadado passa por uma reconciliação (`update`) logo depois da implantação, até gravar o metadado.
- **Outros controles da plataforma** que precisem aparecer no provedor seguem o mesmo caminho: campo gerenciado, metadado com o nome do campo e o mesmo driver.
- O metadado `deletionProtection` da organização `register` (bootstrap, fora do loop) foi gravado à mão e não é reconciliado.
