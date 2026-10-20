# 0017 — Estrutura interna dos componentes, relay no Manager e testes e2e

- **Data:** 2026-10-11
- **Status:** Aceita, **exceto a parte que faz do relay um modo do Manager, substituída pela decisão 0019** (o Publisher é o sexto papel). Mantêm-se a estrutura interna por camadas e a suíte e2e como teste. Ajusta a decisão 0015: a suíte de conformidade deixa de ser um componente.

## Contexto

A 0015 definiu um projeto por papel e por tipo de recurso, com seis papéis (`api`, `manager`, `relay`, `observer`, `reconciler` e `executor`) e uma suíte de conformidade ao lado deles. A implementação do User (`features/core/user`), a primeira feature e o modelo das demais, mostrou três problemas:

- **O relay não é um papel do padrão.** O `docs/RESOURCE-CONTROL-LOOP.md` define cinco papéis (Receiver, Manager, Observer, Reconciler e Executor). O relay é a publicação do outbox, e a publicação dos eventos consolidados é uma responsabilidade do Manager (§3.5). Separá-lo em projeto próprio acrescentou um sexto papel que o padrão não pede e uma imagem a mais por feature, sem um perfil de código diferente: ele muda junto com o Manager.
- **A suíte de conformidade não é um componente.** Ela não participa do loop, não é implantada e só existe para provar o contrato. Ao lado dos componentes, parecia um sétimo papel.
- **Não havia regra para a estrutura interna.** O código do Manager misturava a regra de negócio com o SQL (`policies.py`), o que dificulta testar a regra sem banco e trocar de linguagem.

## Decisão

### 1. ~~Cinco papéis; o relay é uma função do Manager~~ (substituída pela decisão 0019)

> **Substituída.** Esta seção fazia do relay um modo do Manager (`serve` e `relay`, na mesma imagem). A decisão 0019 a substituiu: o relay passou a ser o **Publisher**, o sexto papel, em projeto próprio (`features/<módulo>/<tipo>/publisher/`), com papel de banco `<módulo>_<tipo>_publisher` e identidade `<módulo>-<tipo>-publisher`. O Manager tem um único comportamento e não tem subcomandos. O que se mantém: o outbox como contrato entre os dois, uma instância ativa por trava consultiva de sessão, e a ausência de regra de negócio na publicação.

### 2. Estrutura interna dos componentes

Todo componente separa regra, orquestração, adaptadores e entrada. A dependência vai em um sentido só: `main → orquestração → domain`; os adaptadores implementam as portas definidas pela orquestração, e o `domain` **nunca importa um adaptador**.

| Camada | Conteúdo | Regra | Teste |
|---|---|---|---|
| `domain/` | Regras do tipo (por exemplo, e-mail único, convergência, decisão, mapeamento, revalidação) | Puro, sem I/O | Unitário, sem infraestrutura |
| orquestração (`handlers/` ou `engine/`) | Fluxo de cada mensagem, usando o `domain` e as portas | Sem SQL, HTTP ou NATS direto | Unitário com dublês |
| adaptadores (`store/`, `provider/`, `transport/`, `http/`, `auth/`, `outbox/`) | SSOT (`store/`), sistema externo (`provider/`), NATS (`transport/`), HTTP (`http/`, `auth/`), leitura do outbox (`outbox/`) | Falam com o mundo; sem regra de negócio | Integração |
| `main.py` | Configuração e ligação dos componentes | Pequeno | |

Camadas por papel (não se cria pasta vazia ou sem sentido, `python.md` §3):

| Papel | Camadas |
|---|---|
| `receiver` | `domain/` (autorização, limite de taxa, identidades e digest do pedido, views), `http/`, `auth/`, `store/` (leitura pelas views), `transport/` (publicação) |
| `manager` | `domain/`, `handlers/`, `store/`, `transport/`, `http/`, `main.py` |
| `publisher` (decisão 0019) | `domain/` (tipos puros da publicação), `outbox/`, `transport/`, `http/`, `main.py` |
| `reconciler` | `domain/` (a decisão), `engine/`, `transport/` |
| `observer` | `domain/` (mapeamento do `observed`), `drivers/` (leitura, um por sub-recurso), `provider/` (conexão só de leitura), `engine/`, `transport/` (decisão 0073) |
| `executor` | `domain/` (revalidação), `actions/` (compõem drivers), `drivers/` (escrita, um por sub-recurso), `provider/` (conexão de escrita), `engine/`, `transport/` (decisão 0073) |

A regra é **verificável**: cada projeto tem um teste que falha se `domain/` importar um adaptador. Uma ferramenta de análise de imports só entra com decisão própria (`AGENTS.md` §21).

### 3. A conformidade é teste, e não componente

A suíte black-box deixa de ser um projeto irmão dos componentes e passa a viver em `features/<módulo>/<tipo>/tests/e2e`. Continua sem importar o código dos componentes e valendo para qualquer implementação em qualquer linguagem, mas é documentada como **teste**, e não como papel. Os testes de contrato por componente (schemas e modelos gerados) continuam nos próprios projetos.

## Justificativa

- (Justificativa original do relay como modo do Manager, **substituída pela decisão 0019**: o publicador do outbox é uma tarefa do serviço dono dos dados, com credencial própria.)
- Separar `domain/` do SQL é o que torna a regra testável sem banco e a troca de linguagem uma troca de adaptadores.
- Alternativas descartadas: publicar direto após o `COMMIT` (perde mensagens entre gravar e publicar); captura de mudanças (CDC), infraestrutura a mais sem necessidade medida; manter o relay como projeto próprio (papel a mais que o padrão não pede; **revista na decisão 0019**).

## Consequências

- `docs/RESOURCE-CONTROL-LOOP.md` (§3.7, §6.6, §46, §48 a §50 e o checklist), `docs/SSOT.md` (§13 e §16), `docs/POSTGRESQL.md`, `docs/RESOURCE-CONTROL-SECURITY.md`, `docs/NATS.md`, os agents `python` e `platform`, as skills e o README do User passam a descrever a estrutura interna e `tests/e2e` (e, a partir da decisão 0019, seis papéis).
- A decisão 0015 continua valendo, exceto onde cita o relay como papel próprio e a suíte de conformidade como componente (ajustado nela).
- O **User** (`features/core/user`) segue esta decisão nos seis papéis, com teste de isolamento do `domain/` em cada projeto (2026-10-11). A Organization (`features/ipm/organization`) foi refeita a partir do User e segue esta decisão (decisão 0038, 2026-10-16). Saúde e erro permanente do Publisher: decisão 0018.
- Fusão dos nomes (**substituída pela decisão 0019**): o projeto `<módulo>-<tipo>-relay` deixou de existir como modo do Manager e voltou como projeto próprio, o Publisher.
