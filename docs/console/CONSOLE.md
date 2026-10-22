# Especificação do Smarkee Console — Svelte 5

## 1. Objetivo

O **Smarkee Console** (`clients/console/`) é o console administrativo web unificado da plataforma Smarkee IT Solutions, construído com Svelte 5 e SvelteKit.

O objetivo é oferecer uma interface funcional, responsiva, modular e extensível, inspirada na experiência operacional e de navegação do Google Cloud Console (referência de mercado, `AGENTS.md` §2.7), mas com identidade visual própria da Smarkee e aderência estrita ao modelo de recursos e segurança da plataforma (`docs/RESOURCE-CONTROL-LOOP.md` e `docs/RESOURCE-CONTROL-SECURITY.md`).

Referências visuais:
- Layout de referência aprovado: `images/console-main-layout.png`.
- Logotipos oficiais da marca: `images/`.

O console é um cliente fino da API pública da plataforma (`clients/`, decisão `0034`), seguindo a ordem arquitetural `API (Receiver) → CLI (sk) → Console Web` (decisão `0013`). Ele consome exatamente os mesmos contratos HTTP e JSON Schema já estabelecidos para as features existentes, utilizando adaptadores simulados claramente identificados apenas onde o backend ainda não existe.

---

## 2. Princípios Arquiteturais

O Console obedece aos pilares do `AGENTS.md` (§2.1), nesta ordem:

1. **Segurança:** respeitar autenticação OIDC no provedor de identidade (Zitadel), autorização baseada nas roles da plataforma e isolamento por `Organization` (decisões `0006`, `0010`, `0013`, `0034` e `0077`).
2. **Simplicidade:** preferir soluções nativas do Svelte 5 e SvelteKit, evitando abstrações, bibliotecas de estado ou camadas desnecessárias.
3. **Robustez:** validar respostas da API de forma estrita e tratar explicitamente estados de erro, carregamento, ausência de dados, rejeição (`rejected`) e falha de convergência (`Failed`).
4. **Resiliência:** projetar a interface para tolerar falhas temporárias, reconexões e operações assíncronas do loop de reconciliação (`202 Accepted` seguido de acompanhamento de `Operation` e `phase`).
5. **Explícito sobre Implícito:** manter contratos, estados, escopo de dados (conta vs. organização) e limitações visíveis e inequívocos.

Regras de escopo e evolução aditiva (`AGENTS.md` §2.2 e §2.6):
- Não implemente funcionalidades inexistentes no backend como se fossem reais.
- Para features cujo backend já existe (`core.account`, `sum.service`, `ipm.organization`, `ipm.user`), os contratos TypeScript e adaptadores devem refletir fielmente os schemas JSON oficiais em `schemas/`.
- Para módulos futuros previstos na visão do produto (`AEM`, `ODM` e recursos ainda não implementados), utilize dados demonstrativos explicitamente identificados na interface (`Preview` / `Demonstrativo`).

---

## 3. Stack Tecnológica

- **Svelte 5** para componentes e reatividade baseada em *runes* (`$state`, `$derived`, `$effect`, `$props`).
- **SvelteKit** para roteamento, layouts compartilhados e estrutura da aplicação.
- **TypeScript** em modo estrito (`strict: true`).
- **Tailwind CSS** para estilos, tokens visuais e responsividade.
- **Lucide Svelte** (`lucide-svelte`) para iconografia consistente.
- **Vitest** para testes unitários e de componentes.
- **Playwright** para testes end-to-end das jornadas principais.
- **ESLint + Prettier** (com `eslint-plugin-svelte` e `prettier-plugin-svelte`) para lint e formatação do código TypeScript/Svelte.
- **pnpm** como gerenciador de pacotes do projeto em `clients/console/`.

Restrições:
- Utilize versões estáveis e compatíveis entre si.
- Não utilize APIs legadas do Svelte 3/4 (`export let`, `$:`, stores `writable` para estado local de componentes, `createEventDispatcher`, `<slot>`) quando houver a construção equivalente em Svelte 5 (`$props`, `$state`, `$derived`, snippets `{#snippet}` / `{@render}`).
- Evite adicionar dependências sem justificativa clara (`AGENTS.md` §21).

---

## 4. Identidade Visual e Idioma

### 4.1 Marca

- Utilize os arquivos oficiais de logotipo disponíveis em `images/`.
- Não redesenhe, distorça, recolora ou substitua os logotipos oficiais por aproximações geradas por código.
- Utilize a versão adequada do logotipo conforme o fundo e o contexto: símbolo isolado, logotipo horizontal ou versão para fundo claro.

### 4.2 Paleta e Tokens Visuais

A identidade visual deriva da marca Smarkee:
- **Verde vivo** como cor primária e de destaque.
- **Verde escuro** para elementos de maior contraste e interação (*hover* / *active*).
- **Branco e tons de cinza muito claros** para superfícies e fundo da aplicação.
- **Azul-marinho escuro / quase preto** para tipografia principal.
- **Tons neutros** para bordas, divisores e textos secundários.
- **Cores semânticas de estado:**
  - Verde para estados convergidos e positivos (`Ready`, `completed`, `enabled`, `active`).
  - Azul/Verde para estados em progresso (`Pending`, `Reconciling`, `accepted`, `in_progress`).
  - Âmbar para alertas, avisos ou estados parciais (`Degraded`, `initial`, `disabled`).
  - Vermelho para falhas e rejeições (`Failed`, `failed`, `rejected`).

Regras visuais:
- Não reproduza a paleta azul predominante do Google Cloud.
- Defina tokens semânticos reutilizáveis para cores, tipografia, espaçamento, bordas, sombras, raios e estados. Evite valores arbitrários espalhados pelos componentes.
- Aparência profissional, limpa e discreta, com cartões de bordas suaves, sombras leves, ícones consistentes e densidade de informação adequada a um console de administração de plataforma.

### 4.3 Composição Visual (`images/console-main-layout.png`)

Preserve a composição e a hierarquia da imagem de referência:
- Cabeçalho horizontal fixo no topo.
- Menu lateral esquerdo com navegação hierárquica por módulos.
- Seletor de organização (`Organization`) no cabeçalho.
- Busca global no cabeçalho (`⌘K` / `Ctrl+K`).
- Ações globais no cabeçalho: notificações, operações, ajuda e perfil da conta.
- Área central com resumo da organização selecionada e grade do dashboard.
- Painel lateral direito retrátil com abas para **Notificações** e **Operações**.
- Cards de acesso rápido, cards de serviços da plataforma e tabelas de recursos recentes e estado dos serviços.

*(Nota: Na imagem de referência o card de Observabilidade aparece com a sigla `POM`; no Console deve ser adotada a sigla oficial da arquitetura, **`ODM` — Observability Data Manager**).*

### 4.4 Idioma da Interface

Conforme a referência visual aprovada e o `AGENTS.md` (§16.1 e §39.1), os textos de interface do Smarkee Console são apresentados em **Português do Brasil (`pt-BR`)**, mantendo-se em inglês apenas os termos técnicos consagrados e valores literais de contrato (`Ready`, `Reconciling`, `Failed`, `IAM`, nomes de módulos e siglas `IPM`, `SUM`, `AEM`, `ODM`). Comentários e docstrings no código-fonte seguem em `pt-BR`, e identificadores técnicos de código em `en-US`.

### 4.5 Abstração de Notações Internas e Foco no Usuário Final

O Smarkee Console é uma interface projetada para o **usuário final** e administradores de organizações, não um depurador de JSON Schema ou ferramenta interna de engenharia:
- **Proibição de Nomes Técnicos de Recursos e Módulos na UI:** É estritamente proibido exibir notações internas como `ipm.organization`, `ipm.user`, `sum.service`, `core.account` em títulos, subtítulos, tabelas, formulários ou cartões. Em seu lugar, use sempre nomes limpos em português: **Organização**, **Usuário**, **Serviço** e **Conta**.
- **Proibição de Notações de Schemas e Ações Internas:** Não exponha notações como `resourceId`, `desired.name`, `deletionProtection`, `operationType`, `update`, `create` ou `delete` diretamente ao usuário. Utilize rótulos amigáveis: **ID**, **Nome / Slug DNS**, **Proteção contra exclusão**, **Ação (Criação, Atualização, Exclusão)**.
- **Isolamento de Processos Internos do Loop:** Tarefas de bastidores executadas pelo loop de reconciliação (como concessões de Project Grant, atribuições de roles técnicas no Zitadel ou sincronizações internas) não são operações do usuário e não devem poluir o painel de operações ou a central de notificações.

---

## 5. Layout Principal (Shell)

Implementado como layout persistente compartilhado (`src/routes/+layout.svelte`).

### 5.1 Cabeçalho (`AppHeader.svelte`)

Contém:
- Botão *hamburger* para expandir ou recolher o menu lateral.
- Logotipo Smarkee com link para o início (`/`).
- Seletor da `Organization` ativa (`OrganizationSelector.svelte`).
- Busca global (`GlobalSearch.svelte`) para pesquisa rápida de recursos, serviços e rotas.
- Indicador e botão de abertura do painel de **Operações** e **Notificações** (com *badge* de contagem ativa).
- Acesso à documentação/ajuda.
- Menu de perfil da conta autenticada (`core.account` ou `ipm.user`).

### 5.2 Seletor de Organização (`OrganizationSelector.svelte`)

Inspirado no seletor de projeto/organização do Google Cloud Console, reflete o recurso `ipm.organization` (decisões `0006`, `0016` e `0038`).

Requisitos:
- Exibir o nome (`desired.name`) e identificar a organização atualmente selecionada.
- Abrir um *popover* ou modal acessível com busca por nome (`name`) ou identificador (`resourceId`).
- Exibir somente organizações visíveis ao usuário autenticado (`GET /v1/ipm/organizations`).
- Indicar visualmente a organização ativa, sua fase (`phase`: `Ready`, `Reconciling`, etc.) e seu estado (`platformAccess`).
- Permitir alternar o contexto administrativo ativo.
- Tratar estados de carregamento, erro e ausência de organizações (ex.: quando o usuário recém-cadastrado ainda não habilitou o `ipm` no SUM ou ainda não criou nenhuma organização).
- Ao trocar de organização, atualizar imediatamente os dados dependentes de organização na página e **impedir que dados da organização anterior permaneçam visíveis** durante ou após a troca.

Regras de segurança de contexto:
- O seletor define apenas o contexto de trabalho na interface (equivalente ao `[ipm] organizationId` da CLI `sk`).
- Nunca trate a seleção no navegador como mecanismo de autorização: todas as operações são autorizadas pelos Receivers no backend mediante validação do token JWT e do vínculo do solicitante (root dono ou `ipm.user` daquela organização, decisão `0077`).
- Nunca assuma que a organização interna `core` ou `register` do Zitadel são organizações de cliente (decisões `0009` e `0027`).

### 5.3 Navegação Lateral (`Sidebar.svelte`)

Menu estruturado por configuração tipada única, agrupado pelos módulos reais e planejados da plataforma:

**Início**
- Dashboard (`/`)

**Identity Provider Manager (IPM)**
- Contas (`/identity/accounts`) — *escopo da conta titular (`core.account`, `/v1/core/accounts`)*
- Organizações (`/identity/organizations`) — *organizações do titular (`ipm.organization`, `/v1/ipm/organizations`)*
- Usuários (`/identity/users`) — *usuários dentro da organização selecionada (`ipm.user`, `/v1/ipm/users`)*
- Configurações de identidade (`/identity/settings`) — *placeholder demonstrativo*

**Service Usage Manager (SUM)**
- Catálogo de serviços (`/services/catalog`)
- Serviços habilitados (`/services/enabled`) — *ligações da conta (`sum.service`, `/v1/sum/services`)*

**Audit Event Manager (AEM)** *(Preview / Demonstrativo)*
- Eventos de auditoria (`/audit/events`)

**Observability Data Manager (ODM)** *(Preview / Demonstrativo)*
- Métricas (`/observability/metrics`)
- Logs (`/observability/logs`)
- Traces (`/observability/traces`)
- Alertas (`/observability/alerts`)

**Administração**
- Configurações (`/settings`)

Requisitos do menu:
- Destacar a rota ativa.
- Permitir expandir e recolher seções.
- Suportar modo compacto (exibindo apenas ícones com *tooltip* acessível) em desktop e comportamento de *drawer* sobreposto em telas menores.
- Refletir permissões do contexto do usuário (ex.: sinalizar quando um módulo requer habilitação prévia no SUM), sem jamais tratar ocultação visual como barreira de segurança.
- Utilizar páginas de *placeholder* consistentes e informativas para rotas fora do escopo do MVP inicial.

### 5.4 Área Principal do Dashboard

A página inicial (`src/routes/+page.svelte`) apresenta:
1. Cabeçalho de boas-vindas e descrição curta do console.
2. Card de resumo da `Organization` selecionada (`OrganizationSummary.svelte`).
3. Grade de acessos rápidos (`QuickAccessGrid.svelte`).
4. Cards dos principais serviços da plataforma (`ServiceCards.svelte`).
5. Tabela de recursos recentes (`RecentResources.svelte`).
6. Tabela de estado dos serviços (`ServiceStatusTable.svelte`).

No card de resumo da organização (`OrganizationSummary.svelte`):
- No card de resumo da organização (`OrganizationSummary.svelte`): Exibir os campos reais do contrato `ipm.organization`. Em interface para o usuário final, omita os nomes técnicos e notações internas dos campos (como `resourceId`, `desired.name` ou `ipm.user`). O rótulo deve ser limpo e intuitivo (ex: "ID", "Slug DNS / Domínio", "Proteção contra exclusão", "Membros").
- Caso sejam exibidos metadados adicionais da referência visual que ainda não existem no schema (como *Plano* ou *Região primária*), identificá-los explicitamente com indicador de **Dado demonstrativo**.

### 5.5 Painel de Notificações e Operações (`OperationsPanel.svelte`)

Painel lateral direito retrátil com duas abas:
- **Notificações:** distingue eventos não lidos e lidos, permite marcar como lido e possui estado vazio claro.
- **Operações:** reflete o acompanhamento das solicitações assíncronas (`Operation` de `schemas/common/operation.v1.schema.json`) disparadas pelo usuário no Console.

**Regra de Foco no Usuário:** O Console é destinado ao usuário final. Tarefas de bastidores executadas internamente pelo loop de controle (`RESOURCE-CONTROL-LOOP.md`) — como atribuições internas de roles, sincronizações técnicas ou passos intermediários de provisionamento — **não devem** aparecer no painel de Operações. O Console deve ser dedicado exclusivamente às ações que o usuário inicia e compreende (como "Criar Organização", "Habilitar Serviço", "Adicionar Usuário").

Cada item da aba **Operações** exibe:
- Tipo de recurso amigável e ação formatada (ex.: "Organização • Atualização", "Usuário • Criação", "Serviço • Habilitação"). Notações internas como `ipm.organization • update` não devem ser exibidas ao usuário.
- Identificador do recurso e da operação (com rótulos amigáveis "ID" e "ID da Operação").
- Estado oficial da operação com badge semântico (`StatusBadge`).
- Motivo legível em português em caso de rejeição (ex.: "Protegido contra exclusão", "Conflito de unicidade").
- Tempo relativo (`há 5 minutos`, `agora`).
- Ação para abrir detalhes da operação ou inspecionar o diagnóstico de erro/rejeição.

Regra de progresso (`AGENTS.md` §3 e §9):
- **Não invente percentuais de progresso estimados localmente.** O contrato `Operation` da plataforma não fornece percentual numérico; enquanto a operação estiver em `accepted` ou `in_progress` (ou o recurso estiver em `Pending` / `Reconciling`), exiba indicador visual indeterminado acompanhado do estado real da operação e das `conditions` (`Ready`, `Progressing`).

---

## 6. Componentes do Dashboard

### 6.1 Acessos Rápidos (`QuickAccessGrid.svelte`)

Cards reutilizáveis com ícone, título, descrição curta e navegação para os módulos ativos e disponíveis da plataforma:
- **Usuários** (`/identity/users` — gestão de usuários na organização ativa).
- **Organizações** (`/identity/organizations` — gestão de organizações).
- **Catálogo de Serviços** (`/services/catalog`).
- **Serviços Habilitados** (`/services/enabled` — serviços habilitados na conta).
- **Eventos de Auditoria** (`/audit/events` — identificado como *Preview*).

### 6.2 Serviços da Plataforma (`ServiceCards.svelte`)

Cards para os módulos de gestão:
- **Identity Provider Manager (`IPM`)** — serviço disponível no catálogo real do SUM (`service: "ipm"`).
- **Service Usage Manager (`SUM`)** — serviço base de habilitação da plataforma.
- **Audit Event Manager (`AEM`)** — *Demonstrativo / Preview*.
- **Observability Data Manager (`ODM`)** — *Demonstrativo / Preview*.

Cada card apresenta nome, sigla, descrição, estado de habilitação e link para a área correspondente.

### 6.3 Recursos Recentes (`RecentResources.svelte`)

Tabela apresentando recursos recentes com colunas para:
- **Nome / Identificador** (`name`, `email`, `service` ou `resourceId`).
- **Tipo** (`ipm.organization`, `ipm.user`, `sum.service`, `core.account`, além de exemplos demonstrativos devidamente marcados se aplicável).
- **Fase (`phase`)** (`Pending`, `Reconciling`, `Ready`, `Degraded`, `Failed`).
- **Atualizado em** (`updatedAt`).

Requisitos:
- Diferenciar estados por cor, ícone e rótulo textual (nunca exclusivamente por cor).
- Nomeclatura fiel ao domínio: usar **`Organization`** (e nunca o termo antigo `Tenant`), **`Account`** (`core.account`) e **`User`** (`ipm.user`).

### 6.4 Estado dos Serviços (`ServiceStatusTable.svelte`)

Tabela que apresenta os serviços e seu estado de habilitação (`sum.service`, decisão `0033`):
- Na arquitetura da Smarkee, a ligação no SUM (`POST /v1/sum/services`) é por conta (`ownerAccountId` + `service`), concedendo as roles do módulo (ex.: `ipm.organization.*`, `ipm.user.*`).
- A tabela deve exibir o nome do serviço, a sigla, o estado da ligação (`lifecycle`: `present` / Habilitado vs. `absent` / Desabilitado, e `phase`: `Ready`, `Reconciling`, `Failed`) e a última atualização (`updatedAt`), deixando explícito quais serviços pertencem ao catálogo ativo e quais são demonstrativos.

---

## 7. Modelo de Dados, Contratos e Adaptadores

O acesso a dados é feito exclusivamente por meio de serviços e adaptadores tipados em `src/lib/services/`, desacoplando componentes Svelte de chamadas HTTP ou dados simulados.

### 7.1 Aderência aos Contratos Oficiais (`schemas/`)

Os tipos TypeScript em `src/lib/types/` devem espelhar rigorosamente os JSON Schemas vigentes no repositório (`schemas/common/` e `schemas/<módulo>/<tipo>/`):

- **Primitivas comuns (`schemas/common/definitions.v1.schema.json`):**
  - `ResourcePhase`: `'Pending' | 'Reconciling' | 'Ready' | 'Degraded' | 'Failed'`
  - `Lifecycle`: `'present' | 'absent'`
  - `Reconciliation`: `'active' | 'suspended'`
  - `Presence`: `'present' | 'absent' | 'unknown'`
  - `PlatformAccess`: `'enabled' | 'disabled'`
  - `Condition`: `{ type: string; status: 'True' | 'False' | 'Unknown'; reason: string; message?: string; observedGeneration?: number; lastTransitionTime: string }`
  - `RequestAccepted`: `{ resourceId: string; operationId: string }` (resposta HTTP `202`)
- **Operação (`schemas/common/operation.v1.schema.json`):**
  - `Operation`: `{ operationId: string; operationType: 'create' | 'update' | 'delete'; module: string; resourceType: string; resourceId: string; desiredGeneration?: number; operationStatus: 'accepted' | 'in_progress' | 'completed' | 'failed' | 'rejected'; operationStatusReason?: 'conflict' | 'validation' | 'not_found' | 'protected'; createdAt: string; updatedAt: string; completedAt?: string }`
- **Conta (`schemas/core/account/resource.v1.schema.json`):**
  - `AccountResource`: visão de `/v1/core/accounts/{resourceId}` com `desired` (`givenName`, `familyName`, `email`, `platformAccess`, `deletionProtection`) e `observed` (`presence`, `accountState`, `observedAt`).
- **Organização (`schemas/ipm/organization/resource.v1.schema.json`):**
  - `OrganizationResource`: visão de `/v1/ipm/organizations` com `resourceId`, `resourceVersion`, `desiredGeneration`, `phase`, `conditions`, `desired` (`name`, `lifecycle`, `reconciliation`, `platformAccess`, `deletionProtection`), `observed` (`presence`, `name`, `platformAccess`, `organizationState`, `deletionProtection`, `observedAt`), `createdAt` e `updatedAt`.
- **Usuário da Organização (`schemas/ipm/user/resource.v1.schema.json`):**
  - `OrganizationUserResource`: visão de `/v1/ipm/users` com `desired` (`organizationId`, `givenName`, `familyName`, `email`, `roles`, `deletionProtection`, `lifecycle`, `reconciliation`) e `observed` (`presence`, `userState`, `roles`, `deletionProtection`, `observedAt`).
- **Ligação de Serviço (`schemas/sum/service/resource.v1.schema.json`):**
  - `ServiceLinkResource`: visão de `/v1/sum/services` com `desired` (`service`, `lifecycle`, `reconciliation`) e `observed` (`presence`, `serviceRoles`, `observedAt`).
- **Modelos específicos de UI:**
  - `ServiceCatalogItem` (metadados visuais dos módulos `IPM`, `SUM`, `AEM`, `ODM` e indicação `isDemo`).
  - `ResourceSummary` (projeção unificada para a tabela de recursos recentes e busca global).
  - `Notification` e `UserContext` (dados do sujeito autenticado, roles presentes no token e organização selecionada).

### 7.2 Arquitetura de Adaptadores

- **Interface única (`ConsoleDataAdapter`):** os componentes e stores consomem apenas o contrato abstrato do serviço.
- **Adaptador Simulado (`MockDataAdapter`):** fornece dados em memória realistas, aderentes aos schemas JSON acima, permitindo simular cenários de carregamento, troca de organização, criação/atualização assíncrona (`202` → `in_progress` → `completed` / `Ready`), rejeição (`rejected` por `protected` ou `conflict`) e erro de rede.
- **Preparação para o Adaptador HTTP (`HttpDataAdapter`):** centraliza o mapeamento para as rotas reais do gateway APISIX:
  - `POST / GET / PATCH / DELETE /v1/core/accounts...`
  - `POST / GET / DELETE /v1/sum/services...`
  - `POST / GET / PATCH / DELETE /v1/ipm/organizations...`
  - `POST / GET / PATCH / DELETE /v1/ipm/users...`
  - Consulta de operações em `/v1/<módulo>/<tipos>/{resourceId}/operations/{operationId}`.
- Valide identificadores (`resourceId`, `operationId`) no cliente com o padrão oficial `^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$` antes de interpolar caminhos de URL, prevenindo *path traversal* (mesma defesa aplicada na CLI em `clients/cli/src/sk/features/api_contract.py`).

---

## 8. Operações Assíncronas e Reconciliação

A Smarkee opera por reconciliação assíncrona entre estado desejado (`desired`) e estado observado (`observed`). O frontend reflete esse ciclo de vida sem reimplementar regras de controle do backend:

- **Recebimento vs. Conclusão:** uma resposta HTTP `202 Accepted` com `{ resourceId, operationId }` significa apenas que o Receiver aceitou o pedido e publicou `requested.*`. Nunca trate `202` como confirmação de que o recurso já convergiu.
- **Dupla dimensão de acompanhamento:**
  1. Estado da solicitação (`Operation.operationStatus`: `accepted` → `in_progress` → `completed` | `failed` | `rejected`).
  2. Convergência do recurso (`Resource.phase`: `Pending` → `Reconciling` → `Ready` | `Degraded` | `Failed`, detalhado por `conditions` `Ready` e `Progressing`, decisão `0078`).
- **Adaptador de acompanhamento de operações (`OperationWatcher`):**
  - Deve expor uma interface reativa desacoplada da tecnologia de transporte.
  - No MVP inicial, opera sobre o adaptador simulado de transições temporizadas.
  - Na integração com o backend atual, a primeira implementação real utiliza **polling com backoff** nos endpoints REST `GET .../operations/{operationId}` e `GET .../{resourceId}` (como faz o `--wait` da CLI `sk`), permitindo evolução futura transparente para SSE ou WebSocket sem alterar componentes Svelte.
  - Deve deduplicar eventos por `operationId` e `resourceVersion`, preservando a consistência visual em reconexões ou recarregamentos.

---

## 9. Segurança e Autenticação

A autenticação da plataforma utiliza **Zitadel** via OpenID Connect (decisões `0007`, `0013`, `0034` e `0052`).

Diretrizes obrigatórias:
- A aplicação `console` residirá no projeto `clients` da organização `core` no Zitadel (decisão `0034`), utilizando **Authorization Code Flow com PKCE** e solicitando as audiences dos projetos de roles dos módulos (`roles-core`, `roles-sum`, `roles-ipm`).
- **Nenhum segredo no cliente:** jamais armazene `client_secret`, chaves de contas de serviço ou credenciais privadas no código ou no bundle do frontend.
- **Proteção de tokens e dados sensíveis:** nunca registre tokens JWT, e-mails ou dados pessoais (`confidential`) no `console.log`, em mensagens de erro brutas ou em URLs.
- **Autorização no Backend:** as roles no token (`core.account.*`, `sum.ipm.*`, `ipm.organization.*`, `ipm.user.*`) e os itens visíveis no menu servem apenas para ergonomia da interface. Toda decisão de autorização pertence exclusivamente aos Receivers.
- **Renovação após mudanças no SUM:** assim como na CLI (decisão `0033`), habilitar ou desabilitar um serviço no SUM altera as roles do usuário no Zitadel, exigindo renovação do token (refresh) após a convergência da ligação para que as novas roles tenham efeito nos Receivers.
- Enquanto o fluxo OIDC interativo do Console não estiver conectado ao Zitadel de dev, o estado de sessão deve vir de um `AuthAdapter` simulado explícito, documentando todos os parâmetros de integração (`issuer`, `clientId`, `redirectUri`, `scopes` com audiences dos projetos de roles).

---

## 10. Organização do Código

Localização no repositório: `clients/console/` (conforme decisão `0034`).

Estrutura de referência:

```text
clients/console/
├── package.json
├── svelte.config.js
├── vite.config.ts
├── tsconfig.json
├── playwright.config.ts
└── src/
    ├── app.css
    ├── app.html
    ├── lib/
    │   ├── components/
    │   │   ├── shell/
    │   │   │   ├── AppHeader.svelte
    │   │   │   ├── Sidebar.svelte
    │   │   │   ├── OrganizationSelector.svelte
    │   │   │   ├── GlobalSearch.svelte
    │   │   │   └── OperationsPanel.svelte
    │   │   ├── dashboard/
    │   │   │   ├── OrganizationSummary.svelte
    │   │   │   ├── QuickAccessGrid.svelte
    │   │   │   ├── ServiceCards.svelte
    │   │   │   ├── RecentResources.svelte
    │   │   │   └── ServiceStatusTable.svelte
    │   │   └── ui/
    │   │       ├── StatusBadge.svelte
    │   │       ├── DemoBadge.svelte
    │   │       └── EmptyState.svelte
    │   ├── config/
    │   │   └── navigation.ts
    │   ├── services/
    │   │   ├── adapter.ts
    │   │   ├── mock-adapter.ts
    │   │   └── operation-watcher.ts
    │   ├── state/
    │   │   └── console-context.svelte.ts
    │   └── types/
    │       ├── common.ts
    │       ├── resources.ts
    │       └── console.ts
    └── routes/
        ├── +layout.svelte
        ├── +page.svelte
        ├── identity/
        │   ├── accounts/+page.svelte
        │   ├── organizations/+page.svelte
        │   ├── users/+page.svelte
        │   └── settings/+page.svelte
        ├── services/
        │   ├── catalog/+page.svelte
        │   └── enabled/+page.svelte
        ├── audit/
        │   └── events/+page.svelte
        ├── observability/
        │   ├── metrics/+page.svelte
        │   ├── logs/+page.svelte
        │   ├── traces/+page.svelte
        │   └── alerts/+page.svelte
        └── settings/
            └── +page.svelte
```

Regras de organização:
- Componentes pequenos, coesos e com nomes explícitos.
- Estado reativo compartilhado construído com módulos `.svelte.ts` (runes do Svelte 5) e Context API do Svelte (`setContext` / `getContext`), evitando estado global mutável inseguro em SSR.
- Não crie diretórios vazios ou camadas sem uso imediato.

---

## 11. Qualidade, Acessibilidade e Responsividade

A interface deve:
- Funcionar em desktop, tablet e dispositivos móveis.
- Utilizar HTML semântico (`<header>`, `<nav>`, `<main>`, `<aside>`, `<section>`, `<button>`, `<dialog>`).
- Suportar navegação completa por teclado (`Tab`, `Shift+Tab`, `Escape` para fechar popovers/drawers, atalho `⌘K` / `Ctrl+K` para a busca global).
- Ter indicador de foco visível (`focus-visible`) em todos os controles interativos.
- Possuir `aria-label`, `aria-expanded`, `aria-current="page"` e papéis ARIA adequados em botões de ícone, menus e abas.
- Manter contraste adequado e nunca comunicar estado exclusivamente por cor (combinar cor + ícone + texto).
- Respeitar `prefers-reduced-motion`.
- Exibir estados explícitos de carregamento (*skeleton* / *spinner*), erro (com ação de tentar novamente) e lista vazia (`EmptyState`).
- Tratar tabelas em telas menores com rolagem horizontal limpa, sem quebrar o layout principal.

---

## 12. Testes e Verificação (`AGENTS.md` §19)

A verificação obrigatória da implementação inclui:

1. Renderização do layout principal (cabeçalho, menu lateral, área central e painel direito).
2. Expansão, recolhimento e modo compacto do menu lateral.
3. Navegação entre rotas e destaque da rota ativa (`aria-current="page"`).
4. Abertura, busca por nome/ID e seleção no `OrganizationSelector`.
5. Atualização imediata do contexto da organização selecionada, garantindo que dados da organização anterior não permaneçam visíveis e que operações/recursos reflitam o novo contexto.
6. Abertura, recolhimento e alternância entre as abas **Notificações** e **Operações** no painel direito.
7. Apresentação fiel dos estados de `Operation` (`accepted`, `in_progress`, `completed`, `failed`, `rejected` com `operationStatusReason`) e de `phase` (`Ready`, `Reconciling`, `Failed`), sem percentuais inventados.
8. Tratamento visual dos estados de carregamento, erro e ausência de dados.
9. Responsividade básica (desktop e mobile drawer).
10. Execução limpa de `pnpm check` (`svelte-check`), `pnpm lint`, `pnpm test:unit` (Vitest), `pnpm test:e2e` (Playwright) e `pnpm build`, sem erros no console do navegador.

---

## 13. Roteiro Incremental de Entrega (`AGENTS.md` §2.2)

### Etapa 1 — Fundação e Contratos (`clients/console/`)
- Inicializar o projeto SvelteKit + Svelte 5 + TypeScript estrito + Tailwind CSS + Lucide + Vitest + Playwright em `clients/console/`.
- Copiar/referenciar os ativos oficiais de marca de `images/` para `clients/console/static/brand/`.
- Definir os contratos TypeScript em `src/lib/types/` espelhando os JSON Schemas de `schemas/`.
- Implementar o `MockDataAdapter` e o estado reativo de contexto (`console-context.svelte.ts`).

### Etapa 2 — Shell e Navegação
- Configurar tokens visuais da Smarkee em `src/app.css`.
- Implementar `AppHeader.svelte`, `OrganizationSelector.svelte`, `GlobalSearch.svelte`, `Sidebar.svelte` e `OperationsPanel.svelte`.
- Implementar o layout persistente (`+layout.svelte`).

### Etapa 3 — Dashboard e Visões Operacionais
- Implementar os componentes do Dashboard (`OrganizationSummary`, `QuickAccessGrid`, `ServiceCards`, `RecentResources`, `ServiceStatusTable`).
- Implementar as rotas funcionais e placeholders claramente identificados para os módulos `IPM`, `SUM`, `AEM`, `ODM` e `Administração`.
- Conectar a simulação de disparo de operação assíncrona (`202` → reconciliação → `Ready`) refletindo em tempo real no painel lateral de **Operações**.

### Etapa 4 — Verificação e Documentação
- Executar bateria de testes unitários/componentes (Vitest) e testes E2E (Playwright).
- Validar `svelte-check`, ESLint e build de produção.
- Documentar no `clients/console/README.md` os comandos de execução, a arquitetura de adaptadores e o mapa exato de integração com o gateway APISIX e o Zitadel.

---

## 14. Critérios de Conclusão do MVP

O MVP do Smarkee Console estará concluído quando:
- O projeto iniciar e compilar localmente em `clients/console/` com comandos documentados.
- O layout reproduzir fielmente a composição e a hierarquia de `images/console-main-layout.png` com a paleta oficial da Smarkee.
- Toda a nomenclatura e todos os tipos de dados respeitarem os contratos da plataforma (`Organization`, `Account`, `User`, `Service`, `Operation`, `phase`, `conditions`), sem resíduos do termo `Tenant` nem percentuais de progresso fictícios.
- O seletor de organização filtrar e alternar o contexto sem vazar dados da organização anterior.
- Os dados demonstrativos e módulos futuros (`AEM`, `ODM`) estiverem explicitamente sinalizados na UI.
- A suíte de verificação (`check`, `lint`, `test`, `build`) passar integralmente.
