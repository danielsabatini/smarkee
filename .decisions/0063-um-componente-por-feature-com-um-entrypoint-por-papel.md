# 0063 — Um componente por feature, com um entrypoint por papel

- **Data:** 2026-10-19
- **Status:** Proposta; piloto implementado e verificado em `core/account` (seção *Piloto*); aguarda a decisão de migrar `ipm/organization` e `sum/service`. Se aceita, ajusta a 0015 (unidade do componente) e responde a pergunta que a 0046 deixou em aberto (juntar ou separar). Não altera a 0017, a 0019 nem a 0062.
- **Origem:** o responsável considerou os componentes totalmente autocontidos complexos demais e pediu um meio-termo que reduza a duplicação, sem perder a separação.

## Contexto

Hoje cada feature (`core/account`, `ipm/organization`, `sum/service`) tem seis papéis, e cada papel é um projeto autocontido (0015): 18 projetos, 18 `uv.lock`, 18 imagens. Medido em 2026-10-19: cerca de 42 mil linhas de Python em `src/`, das quais pelo menos 21% (8,8 mil linhas) são arquivos idênticos byte a byte entre projetos; a parte quase idêntica não foi medida. Mudar um contrato transversal (por exemplo, o de logs, 0045) tocou mais de 100 arquivos, e a 0046 passou a gerar as cópias a partir de uma fonte única.

A 0015 separou os papéis por **credencial e fronteira** (Receiver anônimo e exposto; Executor com credencial de escrita no provedor; Observer com leitura; Manager e Publisher com papéis de banco distintos). A troca de linguagem por papel, outro motivo da 0015, é hipotética e não tem evidência de uso (AGENTS §25).

## Decisão

- **Componente = feature.** Cada feature (`<módulo>/<tipo>`) é **um projeto** (código, `pyproject.toml`, `uv.lock`, testes, `Dockerfile`, versão) que produz **uma imagem** (`<módulo>-<tipo>`).
- **Um entrypoint por papel.** A imagem contém o código dos seis papéis; cada papel roda como **um processo e um contêiner próprios**, escolhidos pelo `command` (`receiver`, `manager`, `publisher`, `observer`, `reconciler`, `executor`). Os papéis nunca rodam juntos no mesmo processo.
- **Código comum uma vez por feature.** Configuração, logging, saúde, NATS, banco e validação de JWT ficam em `common/` do projeto, e não repetidos por papel. Cada papel mantém a estrutura interna da 0017, com o `domain/` puro.
- **Nada muda nas fronteiras de privilégio.** Permanecem por papel: contêiner, Deployment (stg e prd), variáveis e segredos (cada contêiner recebe só os do seu papel), papel de banco (`<módulo>_<tipo>_<papel>`), identidade no NATS (`<módulo>-<tipo>-<papel>`), conta do provedor e escala. Ter o código de um papel na imagem de outro não concede privilégio: o privilégio vem da credencial, que não está na imagem.
- **Isolamento verificado por teste.** Um papel não importa outro papel. Um teste em cada feature falha se isso ocorrer, no mesmo espírito do teste de isolamento do `domain/` (0017).
- **Etapas de implantação** (`migrate` e criação dos consumers do NATS) usam a mesma imagem, com outro `command`; a migração continua com o papel administrativo do banco, nunca com o de runtime do Manager (0015).
- **A duplicação entre features continua e continua com fonte única** (0046), agora em 3 cópias do `common/` em vez de 18. Uma biblioteca comum entre features, se um dia for necessária, é decisão posterior e aditiva.
- **Telemetria não muda** (0062 e `docs/OBSERVABILITY-ARCHITECTURE.md`): `telemetry-agent`, `telemetry-router`, um `platform-telemeter` e um `<módulo>-<tipo>-telemeter` por feature, que segue sendo um contêiner do OpenTelemetry Collector com imagem própria, fora da imagem da aplicação.
- **Auditor: em aberto.** Será decidido em decisão própria. A orientação inicial, ainda não decidida, é um auditor por feature, que consome os fatos duráveis (outbox e NATS) com identidade de leitura própria. A questão de ser um sétimo entrypoint da imagem da feature ou uma peça separada fica para essa decisão.

## Justificativa

| Opção | Segurança | Simplicidade | Robustez e resiliência |
|---|---|---|---|
| Manter 18 projetos (0015 + 0046) | Máxima | Pior: cada mudança transversal toca todos | Divergência detectada por teste |
| **Um projeto por feature, seis contêineres (adotada)** | Mesmas credenciais e fronteiras; a imagem do Receiver passa a conter código de outros papéis | Bem melhor: 18 projetos viram 3 | Igual; a versão é única por feature |
| Um processo por feature (0011) | Pior: Receiver anônimo e Executor juntos | Ótima | Domínio de falha grande |
| Um processo por papel para todos os features | Pior: Executor com as credenciais de todos os tipos | Ótima | Raio de falha de um tipo atinge todos |
| Biblioteca de runtime compartilhada, 18 projetos | Igual à atual | Boa em código, mas mantém 18 projetos e muda o build | Um bug na biblioteca afeta tudo |

A opção adotada reduz a duplicação onde ela é maior (entre os papéis da mesma feature) sem tocar nas fronteiras que sustentam o pilar de segurança. É um degrau aditivo (AGENTS §2.6): contratos, nomes de identidade, papéis de banco, subjects e testes e2e permanecem; o que se acrescenta é o `common/`, e o que se substitui é a divisão do código em 6 projetos por feature.

## Consequências

- **Segurança, custo conhecido:** a imagem do Receiver, que é a exposta, passa a conter o código e as dependências dos outros papéis (por exemplo, o cliente do Zitadel), o que aumenta a superfície de supply chain e de CVEs. Mitigações: o teste de não importação entre papéis, imagem sem shell, `cap_drop: ALL` e `no-new-privileges`.
- **Versão única por feature:** mudar o Executor gera uma imagem nova para todos os papéis da feature. Em stg e prd, só reinicia o Deployment cujo manifesto mudou de versão; o rastreio de "qual versão roda onde" fica menos fino.
- **Troca de linguagem por papel deixa de ser simples.** Um papel em outra linguagem exigiria extraí-lo para um projeto próprio, e a suíte e2e black-box (0017) continua sendo o contrato que ele deve cumprir.
- **Contratos afetados e migração (AGENTS §10):** muda o nome da imagem (`core-account-receiver` → `core-account`) e o layout (`features/<módulo>/<tipo>/<papel>/` → um projeto por feature). Não mudam: nomes de contêiner, variáveis (`<MÓDULO>_<TIPO>_<PAPEL>_<SEÇÃO>_<CAMPO>`), papéis de banco, identidades no NATS, subjects, rotas e schemas. A migração é por feature, uma de cada vez, com a suíte e2e passando antes e depois.
- **Documentos a alinhar quando a decisão for aceita:** `docs/RESOURCE-CONTROL-LOOP.md` (§48 e checklist), `docs/IMPLEMENTATION-STATUS.md` (§2.6), os READMEs das features, `.opencode/agents/` e `.opencode/skills/` (AGENTS §24.1). O `sync.py` da 0046 passa a tratar o `common/` por feature.
- **Piloto:** migrar `core/account` primeiro e medir (linhas, arquivos, tempo de build, tamanho da imagem, suíte e2e e de resiliência) antes de aceitar a decisão e migrar as demais.

## Piloto em `core/account` (2026-10-19)

**O que foi feito.** Os seis projetos viraram um (`features/core/account/pyproject.toml`, um `uv.lock`, um `Dockerfile`, uma imagem `smarkee-core-account`). Pacote `core_account` com `common/` (`logging_config`, `ids`, `http/health`, `contracts/base` e `contracts/generated`) e um subpacote por papel; os scripts de entrada continuam `core-account-<papel>` e o `compose.yaml` escolhe o papel pelo `command`. Testes em `tests/<papel>/` e `tests/common/`; `migrations/`, `consumers/` e `openapi.json` na raiz da feature. A suíte `tests/e2e` segue como projeto à parte.

**Ajustes que a mudança exigiu** (além do previsto):
- O `Resource` do log (contrato 0045) derivava o papel do nome do pacote (`<módulo>_<tipo>_<papel>`). Agora o papel é informado pelo entrypoint (`configure_logging(role=...)`). A fonte canônica aceita os dois modos (papel no pacote, ou explícito) até `ipm/organization` e `sum/service` migrarem; `service.name`, `smarkee.module`, `smarkee.resource.type` e `smarkee.component.role` não mudam, e o roteamento da 0062 continuou funcionando.
- `schemas/observability/sync.py` entende os dois layouts (por papel e por feature).
- Os módulos de apoio dos testes de integração, antes todos chamados `support`, passaram a `support_<papel>`, porque agora convivem no mesmo projeto.
- Os testes `test_domain_isolation.py` usavam a posição do componente no nome do módulo para achar a camada; foram ajustados (sem isso passariam sem verificar nada). `tests/common/unit/test_role_isolation.py` é novo.

**Medido.**

| | Antes | Depois |
|---|---|---|
| Projetos / `uv.lock` / `Dockerfile` | 6 / 6 / 6 | 1 / 1 / 1 |
| Imagens | 6 (226 a 298 MB cada) | 1 (299 MB) |
| Python em `src/` | 13.785 linhas, 92 arquivos | 7.858 linhas, 70 arquivos |
| Python em testes (sem e2e) | 7.658 linhas, 60 arquivos | 5.817 linhas, 55 arquivos |
| Contêineres de aplicação | 6 | 6 (mesmos nomes, saúde e credenciais) |

**Verificado.** `ruff` e `pyright` (strict) sem erros; 400 testes unitários e de contrato e 31 de integração (banco e NATS reais) passaram; `docker compose` sobe os seis papéis da imagem única, todos saudáveis; `tests/e2e` de `core/account` com `E2E_CHAOS=1` (11 testes, 147 s) e `tests/telemetry` (13 testes) passaram; `schemas` (397 testes) e os testes de log dos 12 componentes de `ipm/organization` e `sum/service`, com a fonte canônica nova, passaram.

**Não verificado.** A jornada e2e completa (`tests/e2e` da raiz, com a CLI e o `sum`), o build em Kubernetes e o tempo de build a frio. A medição de superfície de CVEs da imagem maior não foi feita.
