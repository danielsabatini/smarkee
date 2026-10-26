# sk — CLI da plataforma smarkee

CLI do usuário da plataforma, em Typer e Pydantic. Requer Python 3.14 e [uv](https://docs.astral.sh/uv/).

```bash
uv sync
uv run sk --help      # ou -h; o rodapé aponta a documentação (https://docs.smarkee.com.br)
uv run sk --version
```

## Configuração

Cada valor é resolvido nesta ordem, do mais forte para o mais fraco: **variável de ambiente → arquivo de configuração → padrão de produção** (decisões 0008 e 0041). O que é do ambiente (provedor, client ID, endereço da API, projetos de roles e HTTP sem TLS) **não tem opção de linha de comando**: em produção a CLI usa o padrão embutido, e em dev e stg o ambiente se escolhe por variáveis (`.env` e `source`).

- Variáveis: `SK_<SEÇÃO>_<CAMPO>`, por exemplo `SK_AUTH_CLIENT_ID`. Os módulos usam a própria seção (`SK_IPM_*`).
- Arquivo: `$XDG_CONFIG_HOME/sk/config.toml` (padrão `~/.config/sk/config.toml`), com uma tabela por seção e **chaves em camelCase**. Uma chave desconhecida ou fora do camelCase (por exemplo `client_id`) é rejeitada.
- O mesmo nome muda só de grafia entre os meios: variável `SK_AUTH_CLIENT_ID`, chave `clientId`; as opções de linha de comando (`--resource-id`, `--wait`) são kebab-case (`docs/data/SCHEMA.md`, *Grafia dos nomes por meio*).

**Em produção não há nada a configurar.** Os valores da plataforma (provedor de identidade, URL da API, client ID e os IDs dos projetos de roles dos módulos) são o **padrão** da CLI: ela funciona sem arquivo e sem variável, e não há `sk init` (decisão 0036). O arquivo, as variáveis e as opções existem só para **sobrescrever**, o que o desenvolvimento e o stg fazem. O `allowInsecureHttp` é só de desenvolvimento e vem desligado.

`sk config` mostra o que vale e altera as sobrescritas, sem editar o arquivo à mão:

```bash
uv run sk config list                              # cada chave, o valor efetivo e a origem (default, file ou env)
uv run sk config get api.url                   # só o valor efetivo, para uso em scripts
uv run sk config set api.url http://api-dev.smarkee.com.br:8080   # cria o arquivo, se não existir
```

Chaves: `auth.issuer`, `auth.clientId`, `auth.allowInsecureHttp`, `api.url`, `api.allowInsecureHttp`, `core.projectId`, `sum.projectId`, `ipm.projectId`, `ipm.organizationId`, `bsm.projectId`, `bsm.accountId` e `operator.projectId`. `set` valida a chave e o valor (booleanos aceitam só `true` ou `false`; endereços precisam de `http://` ou `https://`) e regrava o arquivo inteiro **só com as sobrescritas**: um valor que ficou no padrão não vai para o arquivo, e comentários feitos à mão não são preservados. Não há `unset`: para voltar ao padrão, apague a chave do arquivo.

**O que ainda não tem padrão de produção:** o client ID e os IDs dos projetos de roles só nascem quando o Zitadel de produção for provisionado. Até lá o padrão é o marcador `000000000000000000` (18 zeros), e `sk auth login` recusa o login dizendo quais valores faltam (em vez de seguir e falhar adiante). Em desenvolvimento, sobrescreva cada um:

```bash
uv run sk config set auth.issuer http://ipm-dev.smarkee.com.br:8080
uv run sk config set auth.clientId <client-id-da-aplicação-cli>
uv run sk config set api.url http://api-dev.smarkee.com.br:8080
uv run sk config set core.projectId <ID-do-projeto-roles-core>
uv run sk config set sum.projectId <ID-do-projeto-roles-sum>
uv run sk config set ipm.projectId <ID-do-projeto-roles-ipm>
uv run sk config set auth.allowInsecureHttp true   # dev não tem TLS
uv run sk config set api.allowInsecureHttp true
```

**Alternativa por variáveis:** copie `.env.example` para `.env` (fora do git), preencha e rode `source .env` antes de usar a CLI. As variáveis `SK_*` valem mais que o arquivo (`sk config list` mostra a origem `env`), então com o `.env` carregado o arquivo de configuração nem é necessário. Os testes ignoram as variáveis `SK_*` do seu ambiente.

```toml
[auth]
issuer = "http://ipm-dev.smarkee.com.br:8080"
clientId = "<client-id-da-aplicação-sk>"
allowInsecureHttp = true  # somente em desenvolvimento

[api]
url = "http://api-dev.smarkee.com.br:8080"
allowInsecureHttp = true  # somente em desenvolvimento

[core]
projectId = "<ID de roles-core>"

[sum]
projectId = "<ID de roles-sum>"

[ipm]
projectId = "<ID de roles-ipm>"
```

O `sk config set` avisa quando grava um endereço `http` sem permissão, e o uso recusa esse endereço.

O arquivo guarda configuração, e não credenciais. Os tokens ficam em `credentials.json`, no mesmo diretório.

## Autenticação

```bash
uv run sk auth login
```

O login é da plataforma, e não de um módulo. O `sk` autentica o usuário direto no provedor de identidade (Zitadel), pelo gateway, sem API própria de autenticação:

1. obtém o discovery OIDC do issuer e confere que o `issuer` anunciado é o configurado;
2. abre o navegador na URL de autorização (Authorization Code com PKCE S256) e também a imprime, para o caso de o navegador não abrir;
3. recebe o retorno em `http://127.0.0.1:<porta efêmera>/callback`, escutando só no loopback, por no máximo 5 minutos, e confere o `state`;
4. troca o código pelos tokens (cliente público, sem segredo) e consulta o userinfo para exibir o usuário autenticado;
5. grava os tokens em `$XDG_CONFIG_HOME/sk/credentials.json` (padrão `~/.config/sk/credentials.json`), com permissão `0600` e gravação atômica. Um novo login substitui o anterior.

O login **não tem opções**: o provedor, o client ID e a permissão de HTTP vêm só do ambiente, do arquivo ou do padrão de produção (decisão 0041).

| Variável de ambiente | Chave em `[auth]` | Significado |
|---|---|---|
| `SK_AUTH_ISSUER` | `issuer` | URL do issuer OIDC, acessado pelo gateway |
| `SK_AUTH_CLIENT_ID` | `clientId` | Client ID da aplicação nativa do `sk` no provedor |
| `SK_AUTH_ALLOW_INSECURE_HTTP=true` | `allowInsecureHttp = true` | Aceita issuer `http`. Somente em desenvolvimento |

A aplicação do `sk` mora no projeto `clients` (sem permissões), e não num projeto de permissões: o token só vale no Receiver de um módulo se o login pedir a audience do projeto de permissões dele. Com `[core] projectId`, `[sum] projectId` e `[ipm] projectId` configurados (ou `SK_CORE_PROJECT_ID`, `SK_SUM_PROJECT_ID` e `SK_IPM_PROJECT_ID`), o login pede a audience de `roles-core`, `roles-sum` e `roles-ipm` no Zitadel, com as permissões no token: sem a chave de um módulo, o Receiver dele recusa o token. Sem a chave, o login é o de sempre.

Códigos de saída: `0` sucesso; `1` falha no login ou na gravação, ou cancelamento (Ctrl+C); `2` uso incorreto (issuer ou client ID ausente, configuração inválida).

### Login de máquina (`sk auth login --key-file`)

```bash
uv run sk auth login --key-file sa-ci.json     # ou SK_AUTH_KEY_FILE=sa-ci.json
```

Autentica uma service account (decisão 0094) sem navegador: a CLI assina uma assertion RS256 (`iss` e `sub` = `userId`, `aud` = issuer, `kid` = `keyId`) com a chave privada do arquivo e a troca por um access token (`jwt-bearer`). Não há refresh token nem `client_id`: a sessão se renova reassinando a assertion a partir do caminho do arquivo, gravado em `keyFile` nas credenciais; o arquivo precisa continuar acessível. O `--key-file` é só opção ou `SK_AUTH_KEY_FILE` (não é chave do `config.toml`). O formato do arquivo é o do Zitadel: `type` (`serviceaccount`), `keyId`, `key` (PEM privada) e `userId`. `sk auth whoami` mostra o `keyFile` da sessão de máquina.

### `sk auth refresh`

```bash
uv run sk auth refresh
```

Renova a sessão agora, pelo refresh token, mesmo com o acesso ainda válido. O token só traz as permissões que existiam quando foi emitido: depois de ligar ou desligar um serviço, renovar faz o token refletir as permissões novas. `sk sum service enable|disable --wait` já faz isso. Sem sessão ou sem refresh token, sai com `1` e aponta `sk auth login`.

### `sk auth whoami`

```bash
uv run sk auth whoami
```

Mostra o usuário da sessão gravada e confirma com o provedor que o acesso ainda vale:

1. lê `credentials.json`; sem o arquivo, diz que não há sessão e aponta `sk auth login`;
2. se o acesso já venceu pela data gravada, para ali, sem consultar o provedor;
3. consulta o userinfo com o access token. Se o provedor recusar ou não responder, a mensagem traz a causa e o comando não mostra o usuário.

A saída nunca mostra tokens. Código `0` com sessão válida; `1` sem sessão, sessão vencida ou sessão não confirmada pelo provedor.

Limitações atuais:

- o `sk` não valida localmente a assinatura do ID token e não usa as claims dele; a identidade exibida vem do userinfo, e a validação dos tokens é responsabilidade dos Receivers que os recebem;
- não há `logout`;
- o arquivo de credenciais guarda tokens em texto claro, protegido apenas pela permissão do sistema de arquivos.

Configuração do Zitadel no ambiente de desenvolvimento: `infrastructure/dev/README.md`, seção *Login do CLI*.

## Qualidade

```bash
uv run ruff check .
uv run ruff format --check .
uv run pyright
uv run pytest --cov --cov-report=term-missing
```

Os testes de integração (`tests/integration`) exercitam o fluxo completo contra um provedor OIDC falso em loopback; não dependem do Zitadel.

## Sessão

O access token vale **15 minutos** (decisão 0033), para que uma revogação de permissão chegue ao token em pouco tempo. Quando está vencido ou para vencer, o `sk` troca o refresh token por um novo, regrava as credenciais e segue, sem pedir login: vale para `sk sum service`, para `sk auth whoami` e para a espera de `--wait`, que renova a cada leitura. O refresh token vale 30 dias sem uso e 90 dias no total (configuração da instância). Sem refresh token, ou se o provedor o recusar, a saída manda rodar `sk auth login`.

## Serviços do SUM (`sk sum service`)

```bash
uv run sk sum service enable --service ipm [--wait] [--timeout SEGUNDOS]
uv run sk sum service get --resource-id ID [--operation-id OPERACAO]
uv run sk sum service disable --resource-id ID [--wait] [--timeout SEGUNDOS]
uv run sk sum service list
```

O endereço da API e a permissão de HTTP sem TLS **não têm opção de linha de comando** (decisão 0041): vêm de `SK_API_URL` e `SK_API_ALLOW_INSECURE_HTTP=true`, de `[api]` no arquivo ou do padrão de produção, como no `sk account create`. `resourceId` e `operationId` precisam seguir o padrão do contrato (letras minúsculas, números e hífen, até 128 caracteres): outro valor é recusado antes de qualquer chamada, porque entra no caminho da URL.

| Comando | Requisição | Resultado |
|---|---|---|
| `enable --service NOME` | `POST /v1/sum/services`, com `Idempotency-Key` gerada por pedido | `202`: o `resourceId` e o `operationId`; com `--wait`, espera `Ready` e renova a sessão |
| `disable --resource-id ID` | `GET` do serviço (para ler a `resourceVersion`), depois `DELETE`; se já está desabilitado, não faz nada | `202`: o `operationId` (ou "nada a fazer", saída `0`); com `--wait`, espera `Ready` e renova a sessão |
| `get --resource-id ID` | `GET` do serviço (e da Operation, se `--operation-id`) | `state` (`enabled` / `disabled`), `phase` e `observedPermissions` |
| `list` | `GET /v1/sum/services` | Uma linha por serviço do solicitante (habilitado ou desabilitado) |

Habilitar e desabilitar são assíncronos: o comando confirma o aceite, e `get` mostra quando a fase chega a `Ready`. **O token só traz as permissões que existiam quando foi emitido**: as do serviço (`ipm.*`) chegam depois do aceite e saem ao desligar. Por isso `--wait` espera a convergência (`Ready` e Operation `completed`, até `--timeout`, 60 s por padrão) e **renova a sessão** pelo refresh token, e o token já reflete o novo estado. Sem `--wait`, rode `sk auth refresh` quando a fase for `Ready`. Se a renovação falhar (por exemplo, sem refresh token), o comando avisa e sai com `0`, porque o pedido já valeu. Os nomes dos campos e os valores de estado saem em inglês (`resourceId`, `state`, `phase`); as mensagens e a ajuda também são em inglês (ver *Idioma*, abaixo). Usa a API de `[api] url` e o token da sessão. Precisa de um solicitante com as permissões `sum.ipm.enable`, `sum.ipm.disable` e `sum.ipm.get`.

Códigos de saída: `0` sucesso; `1` sessão ausente, API recusou ou indisponível, ou `--wait` sem convergir (Operation recusada ou tempo esgotado); `2` opção obrigatória ausente, identificador fora do contrato, endereço sem HTTPS ou configuração inválida.

## Organizations (`sk ipm organization`)

```bash
uv run sk ipm organization create --name NOME [--wait] [--timeout SEGUNDOS]
uv run sk ipm organization get [--resource-id ID] [--operation-id OPERACAO]
uv run sk ipm organization list
uv run sk ipm organization update [--resource-id ID] --name NOVO-NOME [--wait] [--timeout SEGUNDOS]
uv run sk ipm organization protect [--resource-id ID] [--wait] [--timeout SEGUNDOS]
uv run sk ipm organization unprotect [--resource-id ID] [--wait] [--timeout SEGUNDOS]
uv run sk ipm organization delete [--resource-id ID] [--wait] [--timeout SEGUNDOS]
```

O endereço da API vem do ambiente, do arquivo ou do padrão, sem opção de linha de comando (decisão 0041), e os identificadores seguem o padrão do contrato, como em `sk sum service`. O nome (`--name`) segue o contrato: letras minúsculas, números e hífen, de 1 a 63 caracteres, começando e terminando com letra ou número; outro valor é recusado antes de qualquer chamada, sem repetir o valor.

| Comando | Requisição | Resultado |
|---|---|---|
| `create --name NOME` | `POST /v1/ipm/organizations`, com `Idempotency-Key` gerada por pedido | `202`: o `resourceId` e o `operationId`; com `--wait`, espera `Ready` e mostra a Organization |
| `update --resource-id ID --name NOVO` | `GET` (para ler a `resourceVersion`), depois `PATCH`; se o nome já é esse, não faz nada | `202`: o `operationId` (ou "nada a fazer", saída `0`); com `--wait`, espera `Ready` com o nome novo |
| `protect` / `unprotect --resource-id ID` | `GET` (para ler a `resourceVersion`), depois `PATCH` com `deletionProtection`; se já está no estado pedido, não faz nada | `202`: o `operationId` (ou "nada a fazer", saída `0`); com `--wait`, espera a Operation `completed` (a observação da nova geração, decisão 0072) e mostra a Organization |
| `delete --resource-id ID` | `GET` (para ler a `resourceVersion`), depois `DELETE`; a Organization nasce protegida e o `409 DeletionProtected` pede o `unprotect` antes (decisão 0043) | `202`: o `operationId`; com `--wait`, espera a Operation `completed` e a Organization sumir (`state removed`) |
| `get --resource-id ID` | `GET` da Organization (e da Operation, se `--operation-id`) | `name`, `state` (`active`, `inactive` ou `unknown` enquanto não observada), `phase`, `platformAccess` e `protected` (`yes` ou `no`) |
| `list` | `GET /v1/ipm/organizations`, seguindo o cursor | Uma linha por Organization do solicitante |

**Organization ativa.** Como o projeto ativo do `gcloud`, a Organization ativa dispensa repetir o `--resource-id`: sem a opção, os comandos usam `[ipm] organizationId` (ou `SK_IPM_ORGANIZATION_ID`, que prevalece sobre o arquivo); `--resource-id` sempre prevalece sobre os dois. Quem grava e troca a Organization ativa é o `sk config set ipm.organizationId ID`: `organization` não tem comando próprio para isso. A única gravação automática é a do `create --wait`: quando a Organization converge e **ainda não há uma ativa** (do ambiente ou do arquivo), ela vira a ativa e a saída avisa; havendo uma, nada muda e a saída mostra o `sk config set` para trocar. Sem `--wait`, o `create` não grava e a saída indica o `sk config set`. Se a gravação falhar, o `create` continua com sucesso e avisa. `delete` da Organization ativa avisa que a chave passa a apontar para um recurso removido e mostra o `sk config set` para trocar. O `sk config set` só confere o formato do `resourceId`: um id que não é seu falha com `404` no primeiro comando que o usar.

As escritas são assíncronas, como as do SUM: o comando confirma o aceite e mostra como acompanhar. A dica de acompanhamento é só `sk ipm organization get` (com `--resource-id` quando a Organization não é a ativa); o `--operation-id` é opcional e serve para diagnosticar um pedido recusado, e a saída de uma recusa já traz o comando completo. Com `--wait`, ele espera a Operation `completed` (até `--timeout`, 60 s por padrão) e trata o `404` logo depois do `202` como espera, porque o Manager ainda pode não ter gravado o pedido. A sessão não precisa ser renovada: criar uma Organization não muda as permissões do token. O dono altera só o `name`; `platformAccess` é do operador e não tem comando nesta CLI.

**Pré-requisitos.** O token precisa trazer as permissões `ipm.organization.*`, que vêm de `sk sum service enable --service ipm --wait` (a sessão já sai renovada). Para criar, o e-mail da conta precisa estar verificado, e a cota é de uma Organization por conta. As recusas da API viram dicas: sem a permissão, a saída manda habilitar o `ipm`; sem e-mail verificado, abrir o link do e-mail de ativação; cota esgotada, remover uma Organization.

Códigos de saída: como em `sk sum service`.

## Usuários, grupos, roles e permissões (`sk ipm user|group|role|permission`)

```bash
uv run sk ipm user create --name NOME --surname SOBRENOME --email EMAIL [--role ROLE]... [--group GRUPO]... [--organization-id ID] [--wait]
uv run sk ipm user update --resource-id ID [--role ROLE]... [--no-roles] [--group GRUPO]... [--no-groups] [--wait]
uv run sk ipm group create --name SLUG --description TEXTO [--role ROLE]... [--organization-id ID] [--wait]
uv run sk ipm group update --resource-id ID --description TEXTO [--role ROLE]... [--no-roles] [--wait]
uv run sk ipm role create --name MODULO.NOME --description TEXTO --permission PERMISSAO... [--organization-id ID] [--wait]
uv run sk ipm role update --resource-id ID --description TEXTO --permission PERMISSAO... [--wait]
uv run sk ipm permission create --name MODULO.TIPO.ACAO --description TEXTO [--grantable | --not-grantable] [--wait]
uv run sk ipm permission update --resource-id ID --description TEXTO [--grantable | --not-grantable] [--wait]
uv run sk ipm user|group|role|permission get|list|protect|unprotect|delete ...
```

Os quatro tipos seguem o mesmo ciclo das Organizations: `create`, `update`, `protect`, `unprotect` e `delete` são assíncronos (`202`, com `Idempotency-Key` por pedido), e `--wait` espera a Operation `completed` até `--timeout` (60 s por padrão). `delete` lê a `resourceVersion` antes de pedir, e um recurso protegido responde `409 DeletionProtected`: a saída manda rodar `unprotect` antes. `get` aceita `--operation-id`, para ver por que um pedido foi recusado ou falhou. A API vem do ambiente, do arquivo ou do padrão, como nos demais comandos.

| Tipo | Escopo | Detalhes |
|---|---|---|
| `user` | Organization (`--organization-id` ou a ativa) | Nasce **sem senha**: a pessoa define a senha pelo e-mail de ativação e entra com `sk auth login`. `update` **substitui** as roles e os grupos pelos valores dados; `--no-roles` e `--no-groups` removem todos. Novos usuários não nascem protegidos |
| `group` | Organization | Agrupa roles compostas. `--role` substitui as roles do grupo; `--no-roles` limpa. O nome é um slug de 2 a 63 caracteres (minúsculas, números e hífen) |
| `role` | Organization (`custom`) ou da plataforma (predefinida) | Nome no formato `<módulo>.<nomeDaRole>`. `--permission` lista as permissões atômicas da role e, no `update`, substitui as atuais. `list` mostra as predefinidas e as `custom` da Organization |
| `permission` | Plataforma (operador) | Permissão atômica no formato `<módulo>.<tipo>.<ação>`. `--grantable` / `--not-grantable` diz se pode ser delegada a Organizations de clientes; no `update`, sem a opção, o valor não muda. Criar, alterar e remover exigem `ipm.permission.admin`; consultar exige `ipm.permission.get` / `list` |

As recusas da API viram dicas na saída (por exemplo, `ipm.user.bind` para mudar roles de um usuário e `ipm.group.bind` para as de um grupo). Códigos de saída: como em `sk sum service`.

## Billing Accounts (`sk bsm account`)

```bash
uv run sk bsm account create --display-name NOME --currency BRL|USD|EUR --contact EMAIL... [--wait]
uv run sk bsm account get [--resource-id ID] [--operation-id OPERACAO]
uv run sk bsm account list
uv run sk bsm account update [--resource-id ID] [--display-name NOME] [--contact EMAIL]... [--wait]
uv run sk bsm account protect|unprotect|delete [--resource-id ID] [--wait]
```

Usa o token da sessão e a API de `[api] url`; o token precisa trazer as permissões `bsm.account.*`. `--currency` não muda depois da criação. `--contact` aceita de 1 a 10 e-mails distintos e, no `update`, **substitui** a lista. Como na Organization, existe a **Billing Account ativa** (`[bsm] accountId` ou `SK_BSM_ACCOUNT_ID`): sem `--resource-id`, os comandos usam a ativa. O `create --wait` grava a nova como ativa **só se não houver uma**; havendo, a saída mostra o `sk config set bsm.accountId ID` para trocar. A Billing Account nasce protegida: `unprotect` precede o `delete`.

## Service accounts (`sk ipm serviceaccount`, alias `sa`)

```bash
uv run sk ipm sa create --name NOME [--organization-id ID] [--description TEXTO] [--role ROLE]... [--key-file F | --public-key-file F.pub] [--expires-in DIAS] [--wait]
uv run sk ipm sa get|list|update|protect|unprotect|delete ...
uv run sk ipm sa key list --resource-id ID
uv run sk ipm sa key add --resource-id ID [--key-file F | --public-key-file F.pub] [--expires-in DIAS] [--wait]
uv run sk ipm sa key remove --resource-id ID --key-id KEYID_OU_FINGERPRINT [--wait]
uv run sk ipm sa key-file --resource-id ID --key-file F
```

A identidade de máquina da Organization (decisão 0094). **A chave privada nasce e fica no cliente**: `create` e `key add` geram o par RSA 2048 localmente, gravam o arquivo de chave (`0600`, criação exclusiva: recusa sobrescrever; padrão `sa-<nome>.json`) e enviam só a pública. Com `--public-key-file` a CLI registra uma chave que você já tem e não grava nada. Cada chave vale até 365 dias (`--expires-in`, padrão 90) e há no máximo 3 por service account; a última não pode ser removida. A service account nasce protegida: `unprotect` precede o `delete`.

O `keyId` só existe depois que o Zitadel registra a chave. Com `--wait`, a CLI completa `keyId` e `userId` no arquivo; sem ele, rode `key-file` quando a fase for `Ready`. Depois, `sk auth login --key-file F`. O papel mínimo para gerenciar é ter as permissões `ipm.serviceaccount.*` (roles `ipm.serviceaccountAdmin` e `ipm.serviceaccountViewer`).

## Cadastro (`sk account create`)

```bash
uv run sk account create --name Ana --surname Souza --email ana@dominio.com
```

Pede o cadastro de um usuário pela API do módulo `core`. É **anônimo**: não exige login, não envia token (mesmo que existam credenciais salvas) e não pede senha. A pessoa define a senha depois, na página do provedor, a partir do e-mail de ativação. O cadastro é assíncrono: o comando confirma que o pedido foi aceito (`resourceId` e `operationId`), e não que a conta já existe.

| Opção | Significado |
|---|---|
| `--name` | Nome próprio (obrigatório, 1 a 256 caracteres) |
| `--surname` | Sobrenome (obrigatório, 1 a 256 caracteres) |
| `--email` | E-mail, também o nome de login (obrigatório) |

O endereço da API (`SK_API_URL`, `[api] url`) e a permissão de HTTP (`SK_API_ALLOW_INSECURE_HTTP=true`, `[api] allowInsecureHttp`) vêm só do ambiente ou do arquivo, sem opção de linha de comando (decisão 0041).

```toml
[api]
url = "http://api-dev.smarkee.com.br:8080"
allowInsecureHttp = true  # somente em desenvolvimento
```

Os dados são validados antes do envio, com os mesmos limites do contrato. Um e-mail mal formado não gera nenhuma chamada à API. Códigos de saída: `0` pedido aceito; `1` serviço indisponível, limite de taxa ou falha de conexão; `2` uso incorreto ou dado recusado pela API.

Depois do cadastro, a pessoa recebe um e-mail do provedor ("Verificar e-mail"), cujo link confirma o e-mail e define a senha. Enquanto a conta não é ativada, `sk auth login` não consegue autenticar. O passo a passo para ativar a conta, e para pedir outro link ou código quando o anterior expirou, está em `features/core/account/README.md`, seção 4.7.

## Conta (`sk account`)

```bash
uv run sk account get
uv run sk account protect [--wait] [--timeout SEGUNDOS]
uv run sk account unprotect [--wait] [--timeout SEGUNDOS]
uv run sk account delete --yes [--wait] [--timeout SEGUNDOS]
```

Agem sobre a conta da sessão (`sk auth login`); o `resourceId` é o `sub` do token. A conta **nasce protegida contra exclusão** (decisão 0043): `unprotect` precede o `delete` (sem ele, a API responde `409 DeletionProtected` e a saída aponta o comando), e `protect` religa a proteção; ambos são idempotentes e `--wait` espera a Operation `completed`. `delete` exige `--yes` (a exclusão não se desfaz) e lê a `resourceVersion` antes de pedir. **A exclusão é segura (decisão 0040):** a API recusa (`409`) enquanto a conta tiver Organizations ou serviços habilitados, e a saída diz o que remover antes (`sk ipm organization delete`, depois `sk sum service disable --service ipm`). Com `--wait`, o comando espera a Operation `completed` (ou o token deixar de valer, porque o usuário já saiu do provedor) e **esquece a sessão local**. `get` mostra `resourceId`, `name`, `email`, `phase`, `platformAccess` e `protected`. O cadastro anônimo agora é `sk account create`.

## Saída no terminal

Os comandos mostram sucesso em painel e erro com causa e dica de correção. Cores aparecem só em terminal interativo, e `NO_COLOR` é respeitado. A apresentação está em `src/sk/ui.py` (`.decisions/0021-apresentacao-da-cli-com-rich.md`). A saída de sucesso vai para a saída padrão, e a de erro para a saída de erro.

### Para scripts: `--output json` e `--raw`

Duas opções do grupo raiz, válidas para qualquer comando e **antes do subcomando** (depois dele o Typer recusa com código 2; decisão 0093):

```bash
uv run sk --output json ipm role list | jq '.[].name'    # um documento JSON na saída padrão
uv run sk --output json ipm organization get --resource-id <ID> | jq -r .phase
uv run sk --raw ipm role list                            # TSV com cabeçalho, sem caixas nem cor
```

- `--output table` é o padrão. `--output json` emite **um único documento** por execução: objeto no `get`, array no `list` (`[]` se vazio), o aceite (`resourceId`, `operationId`) num pedido sem `--wait` e o recurso convergido com `--wait` (`{"resourceId": ..., "state": "removed"}` na remoção). As chaves são as da API, em camelCase.
- `--raw` imprime tabelas em TSV e painéis como `rótulo<TAB>valor`; com `--output json` o JSON sai compacto, em uma linha.
- As orientações ("Follow it with ...", "Nothing to do") vão para a **saída de erro** em `--raw` e em `--output json`, para a saída padrão ter só dados. Em falha a saída padrão fica vazia e o código de saída não muda.
- `auth login`, `auth refresh` e `config get|set` não têm saída em JSON e recusam `--output json` com código 2, antes de qualquer chamada. `config get` segue imprimindo só o valor.
- Sequências de escape e caracteres de controle vindos da API são removidos da saída em todos os modos.

## Textos de ajuda

A ajuda (`--help`) segue um padrão único, montado por `src/sk/help.py` e verificado em `tests/unit/test_help.py` (`.decisions/0022-padrao-dos-textos-de-ajuda-da-cli.md`). Cada opção aparece como:

```text
--timeout  Seconds to wait with --wait. [Integer] [default 60] [optional]
```

- `[String]`, `[Integer]` ou `[Boolean]`: o tipo do valor.
- `[env … | file … | default …]`: de onde o valor pode vir, na ordem de resolução (variável de ambiente, arquivo de configuração, padrão de produção). Só aparecem as fontes que existem.
- `[required]` (vermelho) ou `[optional]`: sem padrão, a opção é obrigatória.

Os textos descrevem o que o comando faz, sem detalhes de implementação. Novos comandos usam `command()` e `option()`.

**Idioma:** tudo o que a CLI mostra ao usuário (ajuda, mensagens, títulos, avisos, erros, dicas e a página de retorno do login) é em **inglês** (decisão 0035); este README, os comentários e as docstrings continuam em português. A data de validade da sessão sai como `AAAA-MM-DD HH:MM` (24 h).
