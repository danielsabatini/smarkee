# ipm.serviceaccount

A **service account** é a identidade de máquina da Organization: um usuário de máquina do Zitadel, na organização do cliente, que se autentica com uma **chave privada que nasce e fica no cliente** (a plataforma guarda só a pública) e recebe permissões da plataforma como qualquer usuário. Decisão [`0094`](../../../.decisions/0094-ipm-serviceaccount-identidade-de-maquina-da-organization.md). É gerenciada pelo Resource Control Loop (`docs/loop/RESOURCE-CONTROL-LOOP.md`); o `resourceId` é o ID do Zitadel (`userId`).

Decisões que definem esta feature: `0094` (o tipo, as chaves, o login e o escopo), `0096` (o Controller unifica observar, decidir e agir), `0077` (usuário da Organization: escopo, permissões e `bind`), `0071` (`bind`), `0040` (consulta entre Receivers com o token de quem pede), `0043` e `0074` (proteção contra exclusão como metadado; aqui ela **nasce ligada**), `0072` (toda alteração percorre o loop), `0073` (drivers espelhados) e `0075` (motores gerados do template). `features/ipm/user` é o **modelo** desta estrutura.

# 1. Estado da implementação

Etapa 1 da `0094` completa: os quatro papéis (Receiver, Manager, Publisher e Controller), o registro na infraestrutura (gateway, telemetria, contas do Zitadel, banco), o reconhecimento cruzado nos outros tipos do `ipm` e a CLI (`sk ipm serviceaccount`, `sk auth login --key-file`) implementados e verificados por testes unitários, de integração, de contrato, e2e e ao vivo no dev. Pendências antes de `stg`/`prd`: ver `docs/platform/IMPLEMENTATION-STATUS.md`.

| Papel | Projeto | Responsabilidade |
|---|---|---|
| Receiver | `receiver/` (`ipm-serviceaccount-receiver`) | API `/v1/ipm/serviceaccounts`: autentica, decide o escopo, valida as chaves públicas, confere catálogo, `bind` e cota, publica `requested`. Contrato em `openapi.json` |
| Manager | `manager/` | Consome `requested` (e os catálogos `DESIRED` de permission e role); nome único na Organization, permissões do módulo e cota na unidade atômica |
| Publisher | `publisher/` | Publica o outbox no NATS (decisão 0065) |
| Controller | `controller/` | Decisão 0096: consome `desired`, e numa só transação observa a máquina, as chaves, as autorizações e os metadados no Zitadel, decide `create`, `update` ou `delete`, age, reobserva e grava o estado e o `updated` no outbox. Leia o [README](src/ipm_serviceaccount/controller/README.md) |
| Testes e2e | `tests/e2e/` | Black-box: loop completo, incluindo a rotação de chaves |

# 2. Papéis e componentes

Os quatro papéis são **um projeto e uma imagem** (decisão 0063), cada um com processo e contêiner próprios, o próprio papel de banco (`ipm_serviceaccount_<papel>`, em `infrastructure/dev/database/bootstrap/ipm.sql`), a própria identidade no NATS e, quando usa o Zitadel, a própria conta de serviço. Além deles, `ipm-serviceaccount-migrate` (migrações) e `ipm-serviceaccount-consumer` (consumer do Manager) rodam e saem.

| Componente | Serviço no Compose | Papel de banco | Conta no Zitadel | Escreve |
|---|---|---|---|---|
| Receiver | `ipm-serviceaccount-receiver` | `ipm_serviceaccount_receiver` (só leitura das views) | — | `requested` no NATS |
| Manager | `ipm-serviceaccount-manager` | `ipm_serviceaccount_manager` | — | SSOT (`ipm.serviceaccount*`) e outbox |
| Publisher | `ipm-serviceaccount-publisher` | `ipm_serviceaccount_publisher` | — | `published_at` do outbox; NATS |
| Controller | `ipm-serviceaccount-controller` | `ipm_serviceaccount_controller` (lê e atualiza `serviceaccount`; `INSERT` só no outbox) | `ipm-serviceaccount-controller` (`ORG_USER_CREATOR` e `ORG_OWNER_VIEWER` em cada organização de cliente e `PROJECT_GRANT_OWNER` no Grant dela) | estado observado, fase, Operations e `updated` no SSOT (e o `desired` suspenso, ao suspender); a máquina no Zitadel |

## 2.1 Receiver

- Rotas sob `/v1/ipm/serviceaccounts`: `POST` cria, `GET ?organizationId=` lista, `GET /{resourceId}` lê, `PATCH /{resourceId}` altera, `DELETE /{resourceId}?resourceVersion=` remove e `GET /{resourceId}/operations/{operationId}` acompanha a Operation.
- Valida o token (assinatura por JWKS, `iss`, `aud` = projeto `roles-ipm`, `exp`). Cada ação exige `ipm.serviceaccount.<create|get|list|update|delete>`; o operador tem `ipm.serviceaccount.admin`.
- **Escopo por Organization (nesta ordem):** operador; registro próprio no SSOT (a máquina age na Organization dela); Receiver de User (`get_user_organization`, o usuário humano da Organization); Receiver da Organization (o dono). Fora do escopo, a resposta é `404`.
- **Chaves públicas:** o pedido traz de 1 a 3 chaves (`publicKey` em PEM e `expiresAt`). O Receiver exige RSA de 2048 bits ou mais, vencimento futuro de até 365 dias e rejeita duplicadas; calcula o `fingerprint` (SHA-256 do DER SPKI) e devolve o PEM canônico. Material de chave privada é recusado (`400`) e nunca é repetido na resposta. Ao alterar `keys`, quem não tem `ipm.serviceaccount.bind` não pode (MEMBER); reenviar uma chave já no `desired` a mantém, mesmo vencida.
- **Permissões:** só as do catálogo `grantablePermission`; sem `bind`, quem pede só atribui ou retira o que ele mesmo tem (decisão 0071).
- **Cota:** 5 por Organization (`IPM_SERVICEACCOUNT_RECEIVER_API_SERVICEACCOUNT_QUOTA`, provisória); o operador não tem cota.
- A service account **nasce protegida** (`deletionProtection` ausente vale `true`): o `DELETE` responde `409 DeletionProtected` até `sk ipm serviceaccount unprotect`.
- Só lê o SSOT, pelas views `ipm.serviceaccount_v1` e `ipm.serviceaccount_operation_v1`. Erros no formato `api-error`; a entrada inválida é `400` e nunca repete o valor enviado.

## 2.2 Manager

- Único escritor do SSOT (`ipm.serviceaccount` e `ipm.serviceaccount_operation`) e do `desired` no outbox. Só admite pedidos: não aplica observação nem resultado de ação, que são do Controller.
- Recusa com `validation` o nome já usado na Organization, a permissão fora do módulo `ipm` e a cota esgotada (na unidade atômica, sob trava consultiva); `protected` o `delete` de uma máquina protegida; `conflict` e `not_found` como em toda feature.
- Ao remover, o `desired` perde `name` e `keys` (`lifecycle absent`, só com a Organization).

## 2.3 Controller

Detalhes no [README do Controller](src/ipm_serviceaccount/controller/README.md) e na decisão `0096`.

- **Decisão:** campos gerenciados `lifecycle`, `permissions`, `deletionProtection`, `description` e os fingerprints das chaves; `organizationId` e `name` são imutáveis. Chave vencida segue no `desired` e no observado como `expired`, sem divergência.
- **Observação:** lê o usuário de máquina (`userState`, `accessTokenType`), a lista de chaves (`ListKeys`: só IDs e vencimentos, nunca material), as permissões em `roles-ipm` e os metadados `deletionProtection`, `description` e `keys` (mapa `fingerprint → keyId`). `absent` só com o `404` do usuário exato; qualquer falha é `unknown`.
- **Ação:** cria o usuário de máquina com `ACCESS_TOKEN_TYPE_JWT` (sempre), adiciona as chaves novas (`AddKey` com a pública) e grava o mapa no metadado `keys`; remove a chave do provedor sem registro no mapa e as fora do `desired`; deixa a autorização com **exatamente** as permissões do `desired`; remove a máquina no `delete`. O Project Grant é o teto.
- **Ciclo:** por `resourceId`, com a linha bloqueada, observa, decide, age, reobserva e grava estado, fase, Operations e `updated` (e apaga o registro quando a remoção converge). A reavaliação periódica detecta divergência externa.

## 2.4 Estrutura

```text
src/ipm_serviceaccount/
  common/      igual em todos os papéis (template, decisão 0064), exceto resource.py, catalog.py e contracts/generated.py
  receiver/  manager/  publisher/  controller/    (cada um com o seu README)
tests/
  common/  receiver/  manager/  publisher/  controller/    (unit, contract e integration)
  e2e/                                                (projeto à parte, black-box)
migrations/    SQL do tipo (esquema e privilégios do Manager e do Controller), aplicado pelo serviço ipm-serviceaccount-migrate
consumers/     manifesto do consumer do Manager (`requested`)
```

A convergência e os handlers do Manager e o domínio comum do Receiver vêm do template (decisão 0075): altere o modelo em `templates/feature/`, não a cópia.

# 3. Mensageria

| Stream | Subject | Consumer | Quem lê |
|---|---|---|---|
| `REQUESTED` | `receiver.requested.ipm.serviceaccount.>` | `ipm-serviceaccount-manager-requested` (durável) | Manager |
| `DESIRED` | `manager.desired.ipm.serviceaccount.>` | `ipm-serviceaccount-controller-desired-<instância>` | Controller |
| `DESIRED` (catálogos) | `manager.desired.ipm.permission.>` e `manager.desired.ipm.role.>` | `ipm-serviceaccount-manager-{permissions,roles}-<instância>` | Manager |

`OBSERVED`, `ACTION` e `RESULT` **não existem** para este tipo (decisão 0096): o Controller observa, age e grava o resultado na mesma transação. O `updated` sai pelo outbox, publicado pelo Publisher em `UPDATED`. Os Streams e as regras de consumo estão em [`docs/messaging/NATS.md`](../../../docs/messaging/NATS.md).

# 4. Contratos

Em `schemas/ipm/serviceaccount/` (e `schemas/common/`), com o índice `schemas/ipm.serviceaccount.index.json`. Os modelos Pydantic são gerados (`uv run datamodel-codegen`, decisão 0012) e conferidos por teste de contrato. A API HTTP é descrita em [`openapi.json`](openapi.json), gerado por `uv run python -m ipm_serviceaccount.receiver.http.openapi > openapi.json` e conferido por teste.

# 5. Segurança e privacidade

- **Chave privada só no cliente:** nunca passa por CLI-para-API, Receiver, SSOT, NATS, logs ou telemetria. O contrato não tem campo para ela e o Receiver recusa o envio.
- **Só permissões da plataforma:** a máquina nunca recebe papel nativo do Zitadel.
- **O Grant é o teto, três vezes:** o Receiver recusa a permissão fora do catálogo, o Manager a permissão fora do módulo `ipm` e o Zitadel a permissão fora do Project Grant.
- **Token sempre JWT:** o gateway não valida token opaco; o Controller força `ACCESS_TOKEN_TYPE_JWT` na criação e confere na observação.
- **`bind`:** sem ele, ninguém concede mais do que tem, nem altera as chaves de outra máquina (MEMBER).
- **Menor privilégio:** a conta `ipm-serviceaccount-controller` no Zitadel só tem `ORG_USER_CREATOR`, `ORG_OWNER_VIEWER` e `PROJECT_GRANT_OWNER` nas organizações de cliente. No banco, o papel `ipm_serviceaccount_controller` lê e atualiza `serviceaccount` e `serviceaccount_operation`, apaga só a linha da remoção convergida e só insere no outbox; o Manager não apaga nem atualiza Operations (migrações `0002` e `0003`).

# 6. Configuração, execução e testes

Variáveis `IPM_SERVICEACCOUNT_<PAPEL>_<SEÇÃO>_<CAMPO>`, com `config.toml` por papel e senhas em `/run/secrets`. Todos os parâmetros estão em [`docs/CONFIGURATION.md`](docs/CONFIGURATION.md) (decisões 0067 e 0070). O `.env.example` lista as obrigatórias.

```bash
# 1. Plataforma (banco, messaging, identidade, gateway): infrastructure/dev, no ar e saudável
# 2. Os componentes
cd features/ipm/serviceaccount && cp -n .env.example .env   # preencha os valores vazios
docker compose up -d --build
# 3. Testes do projeto
uv sync && uv run ruff check . && uv run pyright && uv run pytest
# 4. Testes e2e (stack no ar e uma Organization preparada): ver tests/e2e/README.md
```

# 7. Limitações e pendências

- Etapa 1 (decisão 0094): sem grupos, sem política e alerta de expiração (etapas 2 e 3).
- A cota (5) é provisória.
- Token de uma máquina removida vale até o `exp` (15 min), como nos demais tipos.
- Diagramas (`docs/architecture`, `docs/flow`, `docs/state`, `docs/database`) e o `DATA-FLOW` ainda não foram produzidos.
