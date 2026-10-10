# 0011 — Serviço `core` colapsado: stack, layout e identidades

- **Data:** 2026-10-09
- **Status:** Aceita para o início do desenvolvimento; revisar antes de stg e prd.

## Contexto

O primeiro recurso do Resource Control Loop é a Organization (módulo `core`, decisão 0009). `docs/RESOURCE-CONTROL-LOOP.md` §48 define o formato colapsado como ponto de partida: um serviço com as responsabilidades de API, Manager, Observer, Reconciler e Executor. A separação em processos exige justificativa registrada (§49).

O `python.md` (§5 e §23) exige registrar o layout do pacote e a escolha das bibliotecas de mensageria e de banco.

## Decisão

- **Stack:** Python 3.14, FastAPI (API HTTP), `nats-py` (NATS JetStream), `psycopg` 3 (PostgreSQL) e PyJWT com `cryptography` (validação dos access tokens pelo JWKS do Zitadel). A configuração usa Pydantic e pydantic-settings, como o CLI (decisão 0008).
- **Configuração do serviço:** variável de ambiente → default (pydantic-settings, sem arquivo de configuração). Segredos por variável ou arquivo montado, nunca no código. O prefixo das variáveis é o do módulo, na mesma regra do CLI: `CORE_<SEÇÃO>_<CAMPO>` (por exemplo, `CORE_NATS_URL`). A decisão 0008 cobre só o CLI, que tem parâmetros de linha de comando e arquivo de configuração do usuário.
- **Formato colapsado:** um processo (`features/core`, pacote `core`, `main.py`) com a API e os workers (Manager, relay do outbox, Reconciler, Executor e Observer) em tarefas `asyncio`.
- **Fronteiras internas preservadas:** cada responsabilidade é um módulo próprio, que se comunica com os demais só pela mensageria.
  - Só o Manager escreve no SSOT.
  - A API só lê as views versionadas.
  - Observer, Reconciler e Executor não leem o SSOT.
  - A separação futura em processos não muda contratos.
- **Identidades:** no formato colapsado, o processo usa uma conexão por papel do PostgreSQL (`core_organization_manager`, `core_organization_api`, `core_user_manager`, `core_user_api` e `core_relay`), e não uma identidade única com a soma dos privilégios. No NATS de dev há um único usuário (`infrastructure/dev`).

## Justificativa

- O formato colapsado é o ponto de partida do padrão e reduz a operação enquanto o modelo é validado.
- Conexões por papel mantêm no banco as fronteiras de privilégio mesmo num processo único.
- As bibliotecas escolhidas são os clientes mantidos e assíncronos de cada sistema. O Pydantic já é usado no CLI.

## Consequências

- **Desvio registrado de `RESOURCE-CONTROL-SECURITY.md` §9 e §14:** a credencial de escrita do Executor no Zitadel e a de leitura do Observer ficam no mesmo processo, e o NATS de dev não aplica identidades por serviço. É aceitável em dev; a separação do Executor (credencial de escrita) é o primeiro candidato pelos critérios da §49 antes de stg e prd.
- **Contas no Zitadel:**
  - `platform-bootstrap@smarkee.internal` é o usuário de máquina da primeira instância (variáveis `ZITADEL_FIRSTINSTANCE_ORG_MACHINE_*`, chave JSON em volume, fora do git). O Zitadel lhe atribui `IAM_OWNER`. Ele é usado **só pela infraestrutura** para configurar a plataforma no Zitadel, e **nenhum serviço de runtime o usa**;
  - cada Executor que escreve no Zitadel tem o seu usuário de máquina, na organização `core` (decisão 0014), com o menor papel possível, criado pela infraestrutura com a conta de bootstrap (`<módulo>-<tipo>-<papel>`, `RESOURCE-CONTROL-SECURITY.md` §5). **Verificados em dev (2026-10-10):** `core-user-executor` com `ORG_USER_MANAGER` cria usuários sem senha, autoriza no projeto, lê e remove, e **não** cria organização nem acessa outras organizações (404, sem membership); `core-organization-executor` com `IAM_ORG_MANAGER` (instância, porque criar organização é operação de instância) cria organização com ID informado e Project Grant, mas também lê usuários de outras organizações: estreitar com papel customizado antes de prd. As chaves ficam no volume `identity-bootstrap` (`service-account-core-user-executor.json` e `service-account-core-organization-executor.json`), gravadas direto no volume, sem passar por arquivo no host;
  - a **API não tem credencial de escrita no Zitadel**: ela só publica `requested` e valida tokens pelo JWKS;
  - o mecanismo definitivo que aplica essa configuração no Zitadel em stg e prd ainda será decidido. Em dev, foi aplicada pela API com a conta de bootstrap, por um script temporário e não versionado.
