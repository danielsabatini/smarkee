# 0011 — Serviço `core` colapsado: stack, layout e identidades

- **Data:** 2026-10-09
- **Status:** Aceita para o início do desenvolvimento; revisar antes de stg e prd.

## Contexto

O primeiro recurso do Resource Control Loop é a Organization (módulo `core`, decisão 0009). `docs/RESOURCE-CONTROL-LOOP.md` §48 define o formato colapsado como ponto de partida: um serviço com as responsabilidades de API, Manager, Observer, Reconciler e Executor. A separação em processos exige justificativa registrada (§49).

O `python.md` (§5 e §23) exige registrar o layout do pacote e a escolha das bibliotecas de mensageria e de banco.

## Decisão

- **Stack:** Python 3.14, FastAPI (API HTTP), `nats-py` (NATS JetStream), `psycopg` 3 (PostgreSQL) e PyJWT com `cryptography` (validação dos access tokens pelo JWKS do Zitadel). A configuração usa Pydantic e pydantic-settings, como o CLI (decisão 0008).
- **Formato colapsado:** um processo (`features/core`, pacote `core`, `main.py`) com a API e os workers (Manager, relay do outbox, Reconciler, Executor e Observer) em tarefas `asyncio`.
- **Fronteiras internas preservadas:** cada responsabilidade é um módulo próprio, que se comunica com os demais só pela mensageria.
  - Só o Manager escreve no SSOT.
  - A API só lê as views versionadas.
  - Observer, Reconciler e Executor não leem o SSOT.
  - A separação futura em processos não muda contratos.
- **Identidades:** no formato colapsado, o processo usa uma conexão por papel do PostgreSQL (`core_organization_manager`, `core_organization_api`, `core_relay`), e não uma identidade única com a soma dos privilégios. No NATS de dev há um único usuário (`infrastructure/dev`).

## Justificativa

- O formato colapsado é o ponto de partida do padrão e reduz a operação enquanto o modelo é validado.
- Conexões por papel mantêm no banco as fronteiras de privilégio mesmo num processo único.
- As bibliotecas escolhidas são os clientes mantidos e assíncronos de cada sistema. O Pydantic já é usado no CLI.

## Consequências

- **Desvio registrado de `RESOURCE-CONTROL-SECURITY.md` §9 e §14:** a credencial de escrita do Executor no Zitadel e a de leitura do Observer ficam no mesmo processo, e o NATS de dev não aplica identidades por serviço. É aceitável em dev; a separação do Executor (credencial de escrita) é o primeiro candidato pelos critérios da §49 antes de stg e prd.
- **Credencial do Executor no Zitadel:** usuário de máquina com chave JWT, criado na primeira instância por variáveis `ZITADEL_FIRSTINSTANCE_ORG_MACHINE_*` e gravado em volume, fora do git (mesmo padrão do PAT do login).
