# 0015 — Componentes por papel, autocontidos e independentes de linguagem

- **Data:** 2026-10-10
- **Status:** Aceita. Substitui a decisão 0011 (serviço `core` colapsado). Ajustada pelas decisões 0017, 0019 e 0046 (o código idêntico entre componentes passa a ter fonte única e verificação, sem biblioteca compartilhada): os papéis são **seis** (`receiver`, `manager`, `publisher`, `observer`, `reconciler` e `executor`) e a suíte de conformidade é teste (`tests/e2e`), e não componente.
- **Rotas:** os caminhos citados aqui (`/v1/users`, `/v1/organizations`, `/v1/<tipos>`) foram substituídos pelo padrão da decisão 0030 (`/v1/<módulo>/<tipos>`).

## Contexto

A decisão 0011 adotou o formato colapsado (`docs/RESOURCE-CONTROL-LOOP.md` §48): um único processo `features/core` com Receiver, Manager, relay e, depois, Observer, Reconciler e Executor. O primeiro recurso funciona assim, mas o formato conflita com requisitos já declarados:

- **Trocar de tecnologia por componente.** Hoje Python; amanhã um Receiver ou um Executor pode ser Go, sem refatorar o resto.
- **Escalar sem reestruturar.** Os papéis têm perfis de escala diferentes (`docs/RESOURCE-CONTROL-LOOP.md` §33): Manager por vazão, Observer por partição, Executor *single-flight*.
- **Ambientes.** Dev em Docker Compose; stg e prd em Kubernetes, com CI/CD e GitOps. Cada componente precisa ter versão, imagem e ciclo de implantação próprios.
- **Menor privilégio de verdade.** Um processo único reúne a credencial de escrita do Executor, a leitura do Observer e as conexões de banco do Manager e do Receiver (desvio já registrado na 0011).

Os critérios do §49 (fronteira de segurança, perfil de escala, domínio de falha, ciclo de implantação, dependências externas, credenciais) já se aplicam a todos os papéis do loop.

## Decisão

- **Componente = papel × tipo de recurso.** Papéis: `receiver`, `manager`, `publisher`, `observer`, `reconciler` e `executor` (o Publisher publica o outbox do Manager, decisão 0019). Cada componente é um **projeto autocontido**, com seu código, dependências (lockfile), testes, `Dockerfile`, imagem, versão e configuração.
- **Layout:** `features/<módulo>/<tipo>/<papel>/`, por exemplo `features/ipm/organization/receiver`. Nome do projeto e da imagem: `<módulo>-<tipo>-<papel>` (`ipm-organization-receiver`). Em Python, o pacote é plano: `ipm_organization_receiver`. Os nomes de identidade no NATS seguem `docs/NATS.md` (`<módulo>-<tipo>-receiver` e `<módulo>-<tipo>-<papel>`).
- **Sem código de runtime compartilhado entre componentes.** Nenhum componente importa outro nem uma biblioteca interna comum. O que é comum é **artefato neutro de linguagem**:
  - contratos em JSON Schema (`schemas/`); cada componente gera os seus modelos a partir deles;
  - o OpenAPI de cada Receiver, versionado no repositório e conferido pela CI contra o código;
  - SQL: tabelas, outbox e views versionadas (`docs/POSTGRESQL.md`, decisão 0004);
  - a especificação das mensagens e dos subjects (`docs/MESSAGING.md`, `docs/NATS.md`);
  - convenções de log, métrica e trace (`docs/NATS.md`, observabilidade);
  - uma **suíte e2e black-box** por tipo (`features/<módulo>/<tipo>/tests/e2e`, decisão 0017), que exercita o contrato pela rede (HTTP, NATS e views do SSOT) e deve passar para qualquer implementação, em qualquer linguagem.
- **Duplicação aceita.** Validação de JWT, configuração, logging e conexão com NATS e PostgreSQL são reescritos em cada componente. O custo é conhecido e compensado por: contrato verificável (testes e2e), componentes pequenos e a regra de que a lógica que muda por tipo fica no componente do tipo. Se a duplicação virar problema medido, volta-se à decisão com evidência.
- **Estrutura interna e Publisher:** a estrutura interna dos componentes e a suíte e2e em `tests/e2e` estão na decisão 0017; o Publisher, sexto papel, na decisão 0019.
- **Fronteiras de dependência:**
  - componentes se comunicam **somente** por mensageria; a única exceção é o SSOT: o Manager escreve, o Receiver lê as views e o Publisher lê e marca o outbox;
  - o **Receiver contém a sua autenticação e autorização** (validação do token e das roles); não existe serviço de autenticação compartilhado;
  - o **Manager é dono do esquema do tipo**: o código das migrações fica no projeto dele e acompanha a sua versão. Elas **executam como etapa própria de implantação** (job ou contêiner de inicialização, como o `core-migrate` de dev), com o papel administrativo do banco, e **nunca com o papel de runtime do Manager**, que não tem privilégio de DDL (`docs/SSOT.md` §16, `docs/RESOURCE-CONTROL-SECURITY.md` §9). O controle de versão das migrações é obrigatório antes de stg e prd;
  - o **Publisher** (sexto papel, decisão 0019) é um projeto próprio, com papel de banco por tipo (`<módulo>_<tipo>_publisher`), trava consultiva por tipo (`<módulo>.<tipo>_outbox`) e identidade própria no NATS (`<módulo>-<tipo>-publisher`, que publica no emissor `manager`).
- **Papéis são criados incrementalmente.** Um componente nasce quando o seu papel é necessário. A fatia 1 foi `organization` com `receiver` e `manager` (com o relay, hoje Publisher); `observer`, `reconciler` e `executor` vêm depois. Depois, `user` é derivado do primeiro como modelo. O **modelo** é a Organization; a ferramenta de geração de esqueletos (por exemplo, `copier`) só será avaliada, com ADR própria (`AGENTS.md` §21), depois de dois ou três componentes mostrarem o que realmente se repete.
- **Operation aninhada ao recurso.** A rota é `GET /v1/<tipos>/{resourceId}/operations/{operationId}`. Cada Receiver só conhece o seu tipo, e a autorização da leitura fica no mesmo lugar do recurso. A rota global `/v1/operations/{id}` deixa de existir. A leitura continua restrita ao solicitante e aos operadores, e o solicitante `anonymous` não lê Operation (`docs/RESOURCE-CONTROL-LOOP.md` §6.1.2).
- **Ambientes:**
  - **dev:** Docker Compose, um serviço por componente, com imagem, variáveis e rede espelhando o que será implantado no Kubernetes. Cada feature tem o seu `compose.yaml` (`features/<módulo>/<tipo>/compose.yaml`, com migração, consumers do Manager, Receiver, Manager, Publisher, Reconciler, Observer e Executor) e o seu `.env`; `infrastructure/dev` fica só com as capacidades da plataforma (banco, broker, identidade e gateway), que sobem antes e criam a rede `internal`. O manifesto do consumer de `requested` é do Manager (`manager/consumers/`);
  - **stg e prd:** Kubernetes, com CI/CD e GitOps. Cada componente tem pipeline, imagem e versão próprios; um manifesto de versões por ambiente indica qual versão de cada componente roda. Os detalhes (escala de Manager, partição do Observer, `StatefulSet` onde houver índice estável de réplica, políticas de rede, pooling de conexões compatível com a trava de sessão do modo `relay`) são decididos e registrados quando o primeiro ambiente Kubernetes for criado.
- **Configuração do componente:** variável de ambiente → default (pydantic-settings em Python; sem arquivo de configuração). Segredos por variável ou arquivo montado, nunca no código. O prefixo é o do componente, `<MÓDULO>_<TIPO>_<PAPEL>_<SEÇÃO>_<CAMPO>` (por exemplo, `IPM_ORGANIZATION_RECEIVER_NATS_URL`); cada contêiner recebe apenas as variáveis do seu papel (ajuste feito na decisão 0016). A decisão 0008 cobre só o CLI.
- **Stack Python (dos componentes em Python):** Python 3.14, FastAPI (API HTTP), `nats-py`, `psycopg` 3, PyJWT com `cryptography` (JWKS do Zitadel), Pydantic e pydantic-settings. Outra linguagem escolhe as bibliotecas equivalentes e deve passar nos mesmos testes e2e.
- **Contas do Zitadel (inalteradas em relação à 0011):**
  - `platform-bootstrap@smarkee.internal` é o usuário de máquina da primeira instância (`ZITADEL_FIRSTINSTANCE_ORG_MACHINE_*`, chave JSON em volume, fora do git), com `IAM_OWNER`. Usado **só pela infraestrutura**; nenhum componente de runtime o usa;
  - cada Executor que escreve no Zitadel tem a sua conta, na organização `core` (decisão 0014), com o menor papel possível (`<módulo>-<tipo>-<papel>`, `docs/RESOURCE-CONTROL-SECURITY.md` §5). Verificado em dev (2026-10-10): `core-user-executor` com `ORG_USER_MANAGER` cria usuários sem senha, autoriza no projeto, lê e remove, e não cria organização nem acessa outras organizações; `ipm-organization-executor` com `IAM_ORG_MANAGER` (instância) cria organização com ID informado e Project Grant, mas também lê usuários de outras organizações, então o papel deve ser estreitado com papel customizado antes de prd. As chaves ficam no volume `identity-bootstrap`;
  - o Receiver não tem credencial de escrita no Zitadel;
  - o mecanismo definitivo que aplica essa configuração no Zitadel em stg e prd continua a decidir. Em dev foi aplicada por script temporário, não versionado.

## Justificativa

- Separar por papel e por tipo dá a cada componente um único motivo para mudar, escalar e falhar, e limita o dano de uma credencial comprometida (menor privilégio).
- Sem biblioteca de runtime compartilhada, nenhuma mudança de linguagem ou de versão de dependência de um componente força os demais. O acoplamento passa a ser só por contratos verificáveis.
- A suíte e2e black-box é o que torna a troca de linguagem segura: o contrato é o que os testes provam, e não o que o código Python faz.
- A criação incremental evita seis projetos por tipo antes de existir necessidade, e preserva a regra de simplicidade (`AGENTS.md` §6) sem abrir mão do layout final.
- Alternativa descartada: manter o formato colapsado e separar "quando necessário". Adiaria a refatoração para o momento de maior pressão e manteria a credencial de escrita junto do Receiver anônimo.
- Alternativa descartada: biblioteca interna comum de infraestrutura. Reduz duplicação, mas prende todos os componentes à mesma linguagem e ao mesmo ciclo de versão, contra o objetivo.

## Consequências

- `docs/RESOURCE-CONTROL-LOOP.md` (§3.7, §6.1.1, §46, §48 a §50), `docs/NATS.md`, `docs/POSTGRESQL.md`, `docs/RESOURCE-CONTROL-SECURITY.md`, os agents e o `ROADMAP.md` são alinhados a esta decisão.
- O projeto único `features/core` (`smarkee-core`) foi dividido em `features/ipm/organization/...` e `features/core/user/...` (a estrutura final do relay e da conformidade está na decisão 0017). A rota global da Operation e o papel de banco `core_relay` mudam (`ipm_organization_relay`, `core_user_relay`); a mudança de contrato da rota é feita antes de existir consumidor externo.
- O desvio da 0011 (credenciais de escrita e de leitura no mesmo processo) deixa de existir assim que Executor e Observer forem criados como componentes próprios.
- Mais projetos, mais pipelines e mais imagens para manter. É o custo assumido; a automação de CI por componente e o gerador de esqueleto são as respostas planejadas.
- Os esqueletos vazios `components/manager` e `features/ipm` não têm função no layout novo. `components/manager` foi removido em 2026-10-12; `features/ipm` deve ser reaproveitado quando o módulo correspondente for criado.
