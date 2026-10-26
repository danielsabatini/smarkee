# 0084 — Organização `operator` e projeto `roles-operator` no Zitadel

- **Data:** 2026-10-25
- **Status:** Aceita. Evolui e revisa as decisões `0031` (roles do operador), `0032` (projetos de roles por módulo) e `0083` (`ipm.permission`).
- **Origem:** Reavaliação arquitetural (§25.1 do `AGENTS.md`) solicitada pelo responsável do projeto para isolar fisicamente os operadores da plataforma e as permissões de operação (`*.admin`) em uma organização e projeto dedicados (`operator` e `roles-operator`), deixando a organização `core` exclusivamente com os projetos de permissões de ação dos módulos e as service accounts de infraestrutura.

## Contexto

Nas decisões `0031` e `0032`, as permissões de operação (`<módulo>.<tipo>.admin`) conviviam dentro dos mesmos projetos `roles-<módulo>` da organização `core` que guardam as permissões de ação dos clientes, e o operador padrão (`admin@smarkee`) recebia autorizações diretas no contexto da organização `core`.

Essa convivência trazia três limitações:

1. **Superfície compartilhada entre permissões de cliente e de operador:** nos projetos `roles-<módulo>` na `core`, o que impedia uma permissão `*.admin` de chegar a uma organização de cliente era apenas o filtro do Project Grant; um erro humano ou de automação ao atualizar um Grant em `roles-<módulo>` encontraria a role `*.admin` disponível no mesmo projeto.
2. **Autorizações humanas na `core`:** a organização `core` misturava service accounts de infraestrutura dos loops com autorizações de operadores humanos e referenciava um usuário da organização `smarkee` (administrador da instância do Zitadel).
3. **Evolução para clientes/consoles de operação:** futuras aplicações administrativas (como um console exclusivo de operadores) pertencem naturalmente ao domínio da operação (`operator`), separado da organização técnica `core` e da organização de instância `smarkee`.

## Alternativas avaliadas (segurança → simplicidade → robustez → resiliência)

1. **Caminho 1 — Organização `operator` somente para usuários operadores, mantendo `*.admin` nos projetos `roles-<módulo>` da `core`** (rejeitada): exigiria delegar `*.admin` da `core` para `operator` via Project Grants, criando exatamente o artefato que nunca deve existir para permissões `*.admin` (um Project Grant que inclui `*.admin`).
2. **Caminho 2 — Organização `operator` dona do projeto `roles-operator` (com todas as `*.admin`) e dos usuários operadores** (adotada): isola fisicamente as roles `*.admin` em um projeto próprio que nunca possui Project Grants e mantém nos projetos `roles-<módulo>` da `core` exclusivamente permissões de ação.

## Decisão

1. **Quatro organizações de plataforma no Zitadel:**
   - `smarkee`: administração da instância do Zitadel (`platform-bootstrap`, `login-client`).
   - `core`: dona dos projetos de permissões de ação por módulo (`roles-core`, `roles-sum`, `roles-ipm`, `roles-bsm`), do projeto `clients` (aplicação `cli`) e das service accounts dos loops (`*-executor`, `*-observer`). **Não possui usuários humanos nem autorizações de usuários.**
   - `operator`: dona dos usuários operadores da plataforma (ex.: `admin@operator.smarkee.internal`), do projeto `roles-operator` e de futuras aplicações exclusivas de operação (em projeto próprio sem roles, conforme decisão `0034`).
   - `register`: usuários cadastrados na plataforma (`core.account`).
2. **Projeto `roles-operator` na organização `operator`:**
   - Configurado com `projectRoleAssertion = true` e `authorizationRequired = true`.
   - Guarda exclusivamente todas as permissões `<módulo>.<tipo>.admin`, mantendo `group = <módulo>`.
   - **Nunca possui Project Grants** para nenhuma outra organização.
   - Administrado pelas mesmas service accounts do loop de permissões: `ipm-permission-executor` (`PROJECT_OWNER`) e `ipm-permission-observer` (`PROJECT_OWNER_VIEWER`).
   - **Correção (2026-10-26):** `PROJECT_OWNER_VIEWER` não basta ao Observer. O Zitadel só devolve as roles de `ListProjectRoles` a quem lê a organização dona do projeto: no `roles-operator` a resposta trazia `totalResult` sem a lista, o Observer concluía `absent`, o Reconciler republicava o `create` sem efeito e toda `*.admin` terminava `Failed` por `ProgressDeadlineExceeded`. O Observer recebe também `ORG_OWNER_VIEWER` na organização `operator` (somente leitura, como já tem na `core`). O Executor não precisa: escreve com `PROJECT_OWNER`.
3. **Projetos `roles-<módulo>` na organização `core`:**
   - Contêm **exclusivamente permissões de ação** (nenhuma `*.admin`).
   - Delegam suas permissões de ação via Project Grant tanto para `register` (e organizações de clientes, no caso de `roles-ipm`) quanto para `operator` (para que os operadores recebam as permissões de ação que exercem além do escopo `*.admin`, conforme decisão `0031`).
4. **Roteamento no `ipm/permission`:**
   - O Executor e o Observer de `ipm/permission` roteiam qualquer permissão cujo terceiro segmento seja `admin` (`*.*.admin`) para o projeto `roles-operator` (chave `"operator"` em `IPM_PERMISSION_IDENTITY_PROJECT_IDS`), preservando `group = <módulo>`, e as demais permissões para `roles-<módulo>`.
5. **Verificação de token nos Receivers e login na CLI `sk`:**
   - Cada Receiver continua exigindo a `audience` do projeto `roles-<módulo>` do seu módulo e lendo as permissões de ação de `urn:zitadel:iam:org:project:<audience>:roles`, além de incorporar qualquer permissão terminada em `.admin` presente em claims `urn:zitadel:iam:org:project:<id>:roles` do token validado (emitida por `roles-operator`).
   - A CLI `sk` inclui `[operator] projectId` (`SK_OPERATOR_PROJECT_ID`) nas audiences solicitadas no `sk auth login` quando configurado.
6. **Reserva de nome:** `"operator"` passa a integrar `RESERVED_ORGANIZATION_NAMES` em `ipm/organization`.

## Consequências

- **Isolamento físico no provedor de identidade:** nenhum projeto `roles-<módulo>` da `core` possui roles `*.admin`, tornando impossível delegar `*.admin` a qualquer organização de cliente mesmo diante de falha humana ou de automação num Project Grant.
- **Separação limpa entre administração do IdP e operação da Smarkee:** o operador da Smarkee autentica-se na organização `operator`, sem usar o superusuário da instância `smarkee` nem habitar a `core`.
- **Verificação:** comprovado pela suíte `infrastructure/dev/identity/conformance` (20 passed) e pelas suítes unitárias das features e da CLI `sk`.
