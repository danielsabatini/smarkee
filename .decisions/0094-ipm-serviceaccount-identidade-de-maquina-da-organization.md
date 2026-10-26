# 0094 — `ipm.serviceaccount`: identidade de máquina da Organization, com chave gerada no cliente

- **Data:** 2026-10-26
- **Status:** Aceita em 2026-10-26 ("pode seguir"), com teto de **3 chaves** e `key add|remove` já na etapa 1 (sugestão da comparação com as clouds). A implementação segue por blocos (A a F), um commit por bloco.
- **Origem:** direção do responsável: a última feature do serviço `ipm` é a service account, para fechar a automação (`--output json` e `--raw`, decisão `0093`) com uma identidade que não seja uma pessoa. Escolhas dele: **feature própria** `ipm/serviceaccount` (e não um tipo dentro de `ipm/user`) e **`sk auth login --key-file` já na primeira entrega**.

## Contexto

- Hoje só há acesso humano: o `ipm.user` entra pela aplicação `cli` (OIDC com PKCE). Um pipeline só chama a API com o login de uma pessoa.
- As service accounts que existem (`<módulo>-<tipo>-<papel>`, decisões `0011`, `0014`, `0084`) são da **plataforma** (Executors e Observers), na organização `core`. Não pertencem a uma Organization de cliente e não têm roles do `roles-*`.
- Referência de mercado (§2.7): `ServiceAccount` do Kubernetes e as service accounts do GCP e da AWS (identidade própria, sem senha, credencial rotacionável e com prazo) e, no próprio Zitadel, o **machine user** com chave JWT (RFC 7523, *JWT profile*).

## Evidência (documentação oficial do Zitadel, consultada em 2026-10-26)

- `POST /v2/users/{user_id}/keys` (`AddKey`) só vale para usuário `machine`. Aceita `expirationDate` e, **opcionalmente, `publicKey` de uma chave RSA gerada pelo cliente**; sem `publicKey` o Zitadel gera o par e devolve o `keyContent` **uma única vez** ("não pode ser lido de novo"). Resposta: `keyId`, `creationDate` (e `keyContent` só no modo gerado).
- Token: `POST /oauth/v2/token` com `grant_type=urn:ietf:params:oauth:grant-type:jwt-bearer`, `scope` com `openid`, a audience de cada projeto (`urn:zitadel:iam:org:project:id:<projeto>:aud`) e as roles (`urn:zitadel:iam:org:projects:roles`), e `assertion` = JWT assinado com a chave privada.
- Da `0077`: `AddKey` exige `expirationDate`; a autorização do usuário no Project Grant da Organization é o teto das roles; papéis entre organizações funcionam.

### Sonda no Zitadel de dev (v4.19.4, 2026-10-26)

Script descartável em `.workspace/`, executado no contêiner do Executor da Organization (papel de instância, no lugar do operador). Criou uma organização de cliente, o Project Grant de `roles-ipm` e um **executor temporário** na `core` com **só** `ORG_USER_CREATOR` na organização e `PROJECT_GRANT_OWNER` no Grant. Tudo foi removido no fim (o `smarkee-dev-cleanup` confirmou ambiente limpo). Nenhuma chave privada, token ou segredo foi impresso.

| # | Pergunta | Resultado |
|---|---|---|
| 1 | `AddKey` aceita a `publicKey` do cliente? | **Sim.** O campo é `bytes`, então no JSON vai o **PEM em base64** (SubjectPublicKeyInfo, RSA 2048). A resposta traz só `creationDate` e `keyId`: **nenhuma chave privada**. Sem `expirationDate`, `400` ("value is required"): o prazo é obrigatório. |
| 2 | Tipo do token | Com `accessTokenType = ACCESS_TOKEN_TYPE_JWT` na criação do machine user, o `access_token` é **JWT** (3 segmentos), `expires_in` 899 s. O gateway (JWKS, `0052`) o valida sem mudança. **Não testado:** o padrão do Zitadel sem o campo (o `accessTokenType` é, portanto, obrigatório no Executor). |
| 3 | Papéis mínimos | `ORG_USER_CREATOR` + `PROJECT_GRANT_OWNER` bastam para: criar o machine user na organização do cliente **com `userId` informado** (o ID devolvido é o informado, então `resourceId` = ID do Zitadel), `AddKey`, `ListKeys`, `DeleteKey`, `CreateAuthorization` no Grant e remover o usuário. Criar machine user na `core` é recusado (`403 AUTH-AWfge`). Não exige `ORG_USER_MANAGER` nem papel de instância. |
| 4 | Token e login | `jwt-bearer` com a chave gerada no cliente: `200`. `sub` = ID do machine user; `iss` = issuer; `aud` contém `roles-ipm`; roles em `urn:zitadel:iam:org:project:<id>:roles` ligadas à organização; `resourceowner:id` = organização (mesmo formato do usuário humano, `0077`). Assertion assinada com **outra** chave: `400`. Depois de `DeleteKey`: `400` (remoção revoga o login). |

### Mini-sonda (parte 2, 2026-10-26)

Mesmo método, tudo removido no fim (`smarkee-dev-cleanup` limpo, `/tmp` do contêiner vazio, script apagado).

| # | Pergunta | Resultado |
|---|---|---|
| 5 | PEM cru no `publicKey` | **`400`** (`invalid value for bytes field publicKey`). O PEM vai **sempre em base64**. |
| 6 | `accessTokenType` padrão | Sem o campo, o login funciona mas o `access_token` **não é JWT** (opaco). O Executor **deve sempre** enviar `ACCESS_TOKEN_TYPE_JWT`, e o Observer deve conferi-lo. |
| 7 | `ListKeys` | O filtro é `{"userIdFilter": {"id": <userId>}}` (com `userId` no lugar de `id`, volta **vazio** sem erro). Há também `organizationIdFilter.id` e `keyIdFilter.id`. Cada item traz `id` (= `keyId`), `userId`, `organizationId`, `creationDate`, `changeDate`, `expirationDate` e **nenhum material privado**. |
| 8 | Chave expirada | O login da chave vencida dá `400 invalid assertion`, e a chave **some do `ListKeys`**. Logo `expired` no `observed` = chave do `desired` ausente no Zitadel com `expiresAt` no passado. |
| 9 | Gateway e Receivers | Token de machine user JWT **passa no gateway** (sem token: `401`). No `ipm/user` chegou ao Receiver (`400` por parâmetro obrigatório ausente); no `ipm/organization` voltou `403`: **confirma o Bloco C**, porque o `sub` da máquina não é reconhecido como dono ou membro. |

**Não verificado:** o Receiver do `ipm` aceitando o token de máquina com a Organization informada (depende do Bloco C).

## Decisão

### 1. Recurso próprio `ipm.serviceaccount`

- Feature `features/ipm/serviceaccount`, pelo roteiro `docs/platform/FEATURE-BOOTSTRAP.md`, com os mesmos quatro perfis do `ipm/user` (decisão `0075`). É o 6º tipo do `ipm`.
- Humano e máquina têm ciclos de vida diferentes (e-mail e verificação de um lado, chave do outro): misturar violaria o §26.
- É um **machine user do Zitadel criado dentro da organização do cliente**, sem senha e sem e-mail. `resourceId` opaco (UUIDv7, decisão `0089`), igual ao ID no Zitadel.
- Campos do `desired`: `organizationId` (imutável), `name` (único por Organization entre as ativas; identificador legível da máquina), `description`, `roles` (as roles do `ipm`, predefinidas e `custom` da própria Organization, como no usuário), `deletionProtection` (**nasce `true`**, §4 da `0043`: remover uma identidade de máquina em uso derruba automação) e `keys`.
- `keys` é uma lista de **chaves públicas** (PEM RSA) com `expiresAt`. A chave pública **não é segredo** e pode viver no SSOT e no NATS. Máximo de **3** chaves por service account (rotação sem parada, como GCP e Azure).
- O `observed` traz, por chave, o `keyId` que o Zitadel devolveu e a situação (`active` | `expired`). Nunca traz material privado.

### 2. A chave privada nasce e fica no cliente (decisão central)

- A CLI gera o par RSA localmente (2048 bits, mínimo aceito pelo Zitadel), grava o **arquivo de chave** no caminho escolhido (`--key-file`, permissão `0600`, criação exclusiva: recusa sobrescrever) e envia **só a chave pública** no pedido.
- O Receiver, o Manager, o Publisher, o Reconciler, o SSOT e o NATS **nunca** veem material privado. Não existe "mostrar a chave uma vez": quem perde o arquivo gera outra chave (rotação).
- Referência: `ssh-keygen` + `authorized_keys`, `gcloud iam service-accounts keys upload` e `az ad sp create-for-rbac --create-cert/--cert`, o CSR do Kubernetes (ver "Como as clouds fazem pela CLI"). Descarta-se o modo "o Zitadel gera e devolve": a chave privada atravessaria o Executor, o barramento e a persistência, contra o §4.1.
- **Chave própria (BYO):** `--public-key-file F.pub` registra uma chave pública que o usuário já tem (par de HSM, KMS ou gerado por outra ferramenta). Nesse caso a CLI não gera nem grava nada, e o `sk auth login` aponta para a chave privada do próprio usuário (`--key-file` com `keyId`/`userId`, ou `--private-key-file` + `--key-id`). É o mesmo contrato: o servidor só vê a chave pública.
- O formato do arquivo é o do Zitadel (`{"type":"serviceaccount","keyId","key","userId"}`), para funcionar também com qualquer cliente OIDC padrão. Como o `keyId` só existe depois que o Zitadel registra a chave, o `sk ipm serviceaccount create --key-file F --wait` **completa o arquivo** (preenche `keyId` e `userId`) quando o recurso converge. Sem `--wait`, grava `userId` e deixa `keyId` vazio, e `sk ipm serviceaccount key-file --resource-id X --key-file F` completa depois (comando de leitura do `observed`, idempotente).
- Prazo obrigatório (`--expires-in`, padrão **90 dias**, máximo 365): a chave sempre expira. O Zitadel exige `expirationDate`.

### 3. Permissões e quem pode o quê (modelo do `ipm.user`, `0077`)

- Permissões: `ipm.serviceaccount.create|get|list|update|delete|bind` (delegáveis, `grantable = true`) e `ipm.serviceaccount.admin` (só do operador).
- `bind`: atribuir ou retirar qualquer role dentro do teto da Organization. Sem `bind`, só as roles que o solicitante tem. Mesma semântica da `0077`.
- **Teto contra escalada:** as roles de uma service account respeitam o `grantable` da Organization, igual ao usuário. Uma service account com `ipm.serviceaccount.create` e `bind` pode criar outras, dentro do mesmo teto e sem ultrapassar o que ela tem (sem `bind`).
- **Escopo por Organization:** operador (qualquer), root (dono, via Receiver da `ipm/organization`) ou identidade da própria Organization com a permissão. Fora da Organization, `404`.
- **Reconhecimento positivo (como na `0077`):** a service account é reconhecida pelo **próprio registro** no SSOT (`resourceId` = `sub`, `lifecycle present`), e lê o próprio registro sem permissão.

### 4. Reconhecimento como membro nos demais Receivers do `ipm`

- Hoje `ipm/group` e `ipm/role` perguntam ao Receiver de `ipm/user` se o `sub` é membro da Organization (`get_user_organization`), e a Organization pergunta se o `sub` é dono ou membro. Um `sub` de service account hoje retorna `404` e seria tratado como estranho: **o token dele não funcionaria** nesses Receivers.
- Decisão: cada um desses pontos passa a perguntar também ao Receiver de `ipm/serviceaccount` quando o de `ipm/user` não reconhece o `sub`. Sem tipo nenhum de membro novo no contrato: é o mesmo `GET .../{id}` com o token de quem pede (padrão da `0040`).
- Escopo: Receivers de `ipm/user`, `ipm/group`, `ipm/role` e `ipm/organization`. É a maior parte do custo da feature fora da pasta nova.

### 5. Cota, exclusão e Organization só vazia

- **Cota:** 5 service accounts por Organization (provisório, configurável no Receiver e reconferido pelo Manager sob trava, como a dos usuários). O operador não tem cota.
- **Exclusão protegida** desde o início (`unprotect` antes de `delete`, como grupos e roles).
- **Organization só vazia:** apagar a Organization passa a exigir que ela não tenha service accounts (`409 ResourcesAttached`, na dúvida `503`/`409 ResourcesNotVerifiable`), como já faz para usuários e grupos.
- **Role em uso:** a exclusão de uma role `custom` (decisão `0092`) também considera as service accounts que a usam.

### 6. Entrar pela CLI: `sk auth login --key-file`

- `sk auth login --key-file F` lê o arquivo, assina a assertion (RS256, `iss`/`sub` = `userId`, `aud` = issuer, `kid` = `keyId`, curta duração) e troca no endpoint de token do Zitadel (`jwt-bearer`), pedindo as audiences e as roles dos projetos configurados (`[core]`, `[sum]`, `[ipm]`, `[bsm]`, `[operator]`), igual ao login humano.
- **Sem navegador e sem refresh token.** Ao vencer, a sessão **reassina** a assertion com a chave do arquivo (o mesmo ponto onde hoje há o `refresh_token`). O arquivo é **referenciado por caminho**; o conteúdo da chave não é copiado para `credentials.json`.
- **O login por chave não usa `client_id`** (a identidade é o `userId` do arquivo); o `SK_AUTH_CLIENT_ID` continua só para o login humano. Em prd, com os padrões da CLI preenchidos, o arquivo de chave basta; em dev e stg exige também as variáveis `SK_*` (URL da API, issuer e `projectId` dos módulos).
- Variável `SK_AUTH_KEY_FILE` para pipelines (resolução: opção → ambiente → arquivo de configuração → default, como o restante). O erro de chave expirada, ausente ou revogada é explícito e diz como rotacionar.
- **Dependência nova:** `cryptography` (geração de par RSA e assinatura RS256). Justificativa (§21): é o que a biblioteca padrão não oferece; é a base de PyJWT e das SDKs do Zitadel; sem ela seria preciso implementar RSA à mão. Monta-se o JWT sem PyJWT (três segmentos base64url), para não somar uma segunda dependência.

### 7. CLI do recurso

`sk ipm serviceaccount create|get|list|update|delete|protect|unprotect|key-file`, com `--wait`, `--timeout`, `--role` (repetível), `--no-roles`, `--organization-id` (ou a ativa) e o padrão de saída da `0093`. Textos em inglês (`0035`). O `list` segue `name | resourceId | phase | description`.

## Como as clouds fazem pela CLI (documentação oficial, consultada em 2026-10-26)

| Aspecto | Google Cloud (`gcloud iam service-accounts`) | Azure (`az ad sp`) | Decisão aqui |
|---|---|---|---|
| Recurso | `create`, `describe`, `list`, `disable`, `enable`, `delete`; chaves em subgrupo `keys` | `create-for-rbac`, `show`, `list`, `update`, `delete`; credenciais em `credential` | Recurso `serviceaccount` + subcomando de chave na etapa 2 |
| Chave gerada no servidor | `keys create OUTPUT-FILE`: grava a privada localmente e **a mostra uma vez** | `create-for-rbac` devolve a senha **uma vez** ("proteja estas credenciais") | **Não adotado** (a privada atravessaria o loop) |
| Chave gerada no cliente | `keys upload PUBLIC_KEY_FILE` (RSA X509 PEM) | `--create-cert` (gera e grava local, só o dono lê) e `--cert` (envia só a pública) | **Padrão aqui**: a CLI gera e grava (`0600`); `--public-key-file` para chave própria |
| Listar credenciais | `keys list` (só metadados) | `credential list` ("o conteúdo não é recuperável") | `get` mostra `keyId` e validade, **nunca** material |
| Várias chaves | Sim (rotação sem parada) | Sim (`credential reset`) | Lista `keys` desde o início; teto 3 |
| Prazo | Opcional | `--years`, padrão 1 ano | **Obrigatório** (exigência do Zitadel), padrão 90 dias |
| Papéis na criação | Separado (`add-iam-policy-binding`) | `--role` + `--scopes` no mesmo comando | `--role` no `create` (como o `ipm user`) |
| Saída | `--format` global | `--output` global (`json`, `table`, `tsv`, `yaml`) | `--output`/`--raw` globais (`0093`) |
| Falha de chave | Erro explícito | Erro explícito | Erro explícito com instrução de rotação |

Pontos adotados a partir da comparação: (a) a credencial nunca volta em `get`/`list`; (b) o fluxo de chave gerada no cliente é o caminho recomendado pelas duas clouds para quem não quer a privada no servidor; (c) rotação exige mais de uma chave viva: o teto de 3 chaves e o `key add|remove` entram já na etapa 1 (as duas clouds permitem várias desde o início).

## Como fatiar (§2.2) e o caminho aditivo (§2.6)

| Etapa | Entrega | Mantém na seguinte | Acrescenta |
|---|---|---|---|
| **1 (patinete)** | Criar, ler, listar, atualizar roles, proteger e remover; até 3 chaves (gerada no cliente), `key add|remove`; `sk auth login --key-file`; reconhecimento da identidade nos Receivers do `ipm`; cota; Organization só vazia | contrato, nomes, a lista `keys`, o formato do arquivo | — |
| **2** | Grupos (`groups` no `desired`, como no usuário) | tudo da etapa 1 | grupos |
| **3** | Operação: expiração visível/alertada, política de prazo por Organization | tudo | opções de política |

A etapa 1 já serve a quem a usa: um pipeline cria a identidade, recebe o arquivo de chave e chama a API sem pessoa. Nada da etapa 1 é descartado na 2. Substituições: nenhuma.

## Segurança (piso do §2.1 em dev)

- Material privado nunca sai do cliente; o arquivo é `0600` e criado de forma exclusiva; erros e logs nunca imprimem a chave nem o JWT (§4.1, §17).
- `keys[*].publicKey` é validada no Receiver (PEM RSA, ≥ 2048 bits, sem chave privada embutida) e novamente no Manager; o Executor registra no Zitadel exatamente o `desired` (convergência por geração, decisão `0072`).
- Menor privilégio: `ipm-serviceaccount-executor` e `ipm-serviceaccount-observer` na `core`, sem papel de instância (a confirmar na sonda); chaves em volume Docker, como as demais (decisão `0011`).
- Token de service account é JWT validado pelo gateway como o de usuário (decisão `0052`). **Limite herdado:** token de identidade desativada vale até o `exp` (validação local).

## Compatibilidade e operação

- Contratos novos e aditivos: nenhuma mudança incompatível. `ipm/user`, `ipm/group`, `ipm/role` e `ipm/organization` ganham apenas uma consulta extra ao novo Receiver quando o `sub` não é de usuário.
- `ipm.permission`: sete permissões novas por migração e semente; `grantable` das seis delegáveis. SUM: catálogo do serviço `ipm` e o enum `GrantablePermission` ganham `ipm.serviceaccount.*` (sem o `admin`), com o teste de paridade da `0092`.
- Em `stg`/`prd` repetir: contas `ipm-serviceaccount-executor/observer`, papéis, Grants e autorizações do tipo, migrações, `update grantable=true` e o `adc.yaml` do gateway (rota e audience).
- Compose, gateway (rota `/v1/ipm/serviceaccounts`), telemetria e e2e: pelo skill `feature-registers`.

## Fora de escopo

- Segredo de cliente (*client credentials*) e *personal access token* do Zitadel: não são emitidos. Um segredo gerado no servidor atravessaria o loop; a chave com par gerado no cliente não.
- Federação de identidade externa (OIDC de CI como GitHub Actions) para trocar token sem chave de longa duração: caminho natural depois, aditivo, e fora desta decisão.
- Service accounts da plataforma (`<módulo>-<tipo>-<papel>`) continuam como estão, na `core`.

## Itens em aberto

1. ~~Quatro confirmações da sonda~~ **(fechada em 2026-10-26)**: `AddKey` com `publicKey` do cliente funciona, o token é JWT com `accessTokenType` explícito, os papéis mínimos bastam e o login por `jwt-bearer` e a revogação por `DeleteKey` se comportam como o esperado. Restam os itens "não verificados" da sonda, a conferir na implementação.
2. ~~Teto de chaves na etapa 1~~ **(fechada em 2026-10-26)**: 3 chaves com `key add|remove`.
3. Cota inicial (5) e prazo padrão (90 dias): provisórios, para testar o mecanismo.
