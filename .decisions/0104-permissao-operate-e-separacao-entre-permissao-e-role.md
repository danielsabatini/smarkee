# 0104 — Permissão de operador `.operate` e separação semântica entre Permissão e Role

- **Data:** 2026-10-29
- **Status:** Aceita. Evolui e revisa as decisões `0028` (formato de chaves de permissão), `0031` (roles do operador), `0083` (`ipm.permission` e `ipm.role`), `0084` (projeto `roles-operator`) e `0103` (integração Zitadel ↔ OpenBao).
- **Origem:** Reavaliação arquitetural (§25.1 do `AGENTS.md`) para eliminar a ambiguidade semântica entre permissões atômicas terminadas em `.admin` e papéis/roles compostas (`<módulo>.<tipo>Admin`), alinhando o plano de controle do cofre (`vault.platform`) aos princípios de menor privilégio e nomenclatura explícita (§15).

## Contexto

Historicamente, antes da criação do catálogo de roles compostas (`ipm/role`, decisão `0083`), a plataforma utilizava o sufixo `<módulo>.<tipo>.admin` em `ipm/permission` (e no projeto `roles-operator`, decisão `0084`) para conceder alcance global/multi-tenant ao operador da plataforma nas APIs (propriedade `principal.is_operator`).

Posteriormente, a decisão `0083` adotou o padrão Google Cloud IAM para as roles compostas pré-definidas da plataforma (`<módulo>.<tipo>Viewer` e `<módulo>.<tipo>Admin`, ex.: `ipm.userAdmin`, `svm.secretAdmin`). Isso gerou uma colisão conceitual:
- **`svm.secretAdmin`** (sem ponto, camelCase) é uma **Role** que agrupa as permissões atômicas de CRUD de um cliente na sua própria organização.
- **`svm.secret.admin`** (com ponto) era uma **Permissão Atômica** que dava alcance irrestrito ao operador, mas que no modelo `<módulo>.<tipo>.<ação>` usava um substantivo de papel (`admin`) em vez de um verbo de ação.
- No cofre (`vault`), a introdução de uma policy genérica `operator-admin` com `path "*"` violava o princípio de menor privilégio e quebrava a correspondência 1:1 entre ações do IdP e do cofre.

## Decisão

1. **Separação Estrita de Nomenclatura (Permissão vs. Role):**
   - **Permissão Atômica (`ipm/permission` e chaves no Zitadel):** é sempre estruturada como `<módulo>.<tipo>.<verbo>` com verbos no infinitivo/imperativo em inglês (`create`, `delete`, `get`, `list`, `update`, `bind`, `enable`, `disable`, `operate`). O termo `admin` fica terminantemente banido como terceiro segmento de permissão.
   - **Role Composta (`ipm/role` e OpenBao OIDC Roles):** é sempre estruturada como `<módulo>.<tipo><Viewer|Editor|Admin>`, representando um **conjunto agrupado de permissões atômicas**.

2. **Adoção do Verbo `.operate` para Permissões de Operador:**
   - A permissão que concede alcance multi-tenant/plataforma ao operador da Smarkee em `roles-operator` passa a ser `<módulo>.<tipo>.operate` (ex.: `ipm.user.operate`, `bsm.account.operate`, `svm.secret.operate`).
   - Conecta-se diretamente à organização **`operator`**, ao projeto **`roles-operator`** e à propriedade **`principal.is_operator`** nas APIs da Smarkee.
   - O controlador `ipm-permission-controller` roteia automaticamente qualquer permissão com terceiro segmento `operate` (`parts[2] == "operate"`) para o projeto `roles-operator` na organização `operator`.

3. **Plano de Controle do Cofre (`vault.platform`) e Políticas Atômicas:**
   - Criação do tipo `vault.platform` para o plano de controle do OpenBao (`sys/*`, `auth/*`, `identity/*`), exclusivo de operadores (`grantable = false`, roteado para `roles-operator`).
   - Permissões atômicas: `vault.platform.get`, `vault.platform.list`, `vault.platform.create`, `vault.platform.update`, `vault.platform.delete` e `vault.platform.operate`.
   - Eliminação de policies monolíticas `operator-admin`, `svm.secret.admin`, `ekm.key.admin` e `clm.certificate.admin` no OpenBao. Todas as policies HCL tornam-se atômicas por ação (24 policies atômicas no total).
   - Definição das Roles de Login OIDC no OpenBao:
     - **`vault.platformViewer`:** agrupa permissões de leitura/listagem (`vault.platform.{get,list}`, `svm.secret.{get,list}`, `ekm.key.{get,list}`, `clm.certificate.{get,list}`).
     - **`vault.platformAdmin`** (default): agrupa todas as ações atômicas de todos os quatro módulos do cofre.

## Consequências

- **Clareza Semântica:** Elimina qualquer confusão entre permissões e roles. Todo sufixo `Admin` denota um pacote (role); todo sufixo `operate` denota a permissão atômica de operador da plataforma.
- **Menor Privilégio Real:** O OpenBao passa a operar exclusivamente com policies HCL atômicas homônimas às permissões do Zitadel.
- **Auditoria Facilitada:** A listagem de permissões do operador em `roles-operator` expressa exatamente as ações que ele tem autorização para operar.
