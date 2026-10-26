# 0018 — Partição no servidor, saúde dos componentes e erro permanente do Publisher

- **Data:** 2026-10-11
- **Status:** Aceita. (O "relay" citado nesta decisão passou a se chamar Publisher na decisão 0019.) Complementa as decisões 0015 e 0017. Implementada em dev para `core.user`: partição do `ACTION` (Executor), saúde em todos os componentes e erro permanente do relay.

## Contexto

Uma avaliação de um projeto de referência com NATS JetStream (o `k8s-meter-explorer`, de uso interno) e de práticas de implementações semelhantes apontou três lacunas reais no padrão dos componentes do smarkee:

1. **Ordem e paralelismo.** O Observer particiona por `hash(resourceId) mod count` na aplicação, e o Executor consome uma ação por vez (`max_ack_pending = 1`), o que serializa tudo, inclusive recursos independentes.
2. **Erro permanente na publicação do outbox.** O relay repetia para sempre uma recusa que nunca seria aceita (por exemplo, mensagem maior que o limite do servidor). Como a ordem é preservada, a mensagem recusada bloqueia as seguintes, e nada avisava.
3. **Saúde.** Reconciler, Observer, Executor e relay não têm HTTP; só o Receiver tinha healthcheck. Sem sinal de vida e de prontidão, o orquestrador não distingue um processo preso de um processo saudável.

## Decisão

### 1. Partição no servidor (aplicada ao `ACTION`)

A ordem por recurso e o paralelismo passam a vir do **Stream**, e não do código do componente:

- o Stream declara `subject_transform` com `partition(N, <token do resourceId>)`, que acrescenta ao subject o token da partição; quem publica continua publicando o subject definido em `docs/messaging/NATS.md`;
- cada partição tem **um consumer durável** com `filter_subject` da partição e `max_ack_pending = 1`: uma ação por vez em cada recurso, e até `N` recursos em paralelo;
- o número de partições `N` é definido no bootstrap do Stream (decisão 0005), nunca pela aplicação. Mudar `N` exige recriar o Stream e é uma operação planejada.

Verificado no NATS 2.15 de desenvolvimento (2026-10-11): 24 recursos distribuídos em 4 partições (7/5/5/7), de forma determinística, e depois no `ACTION` real, com o loop completo do User e os testes e2e passando.

- **Aplicado ao Executor.** O Subject armazenado ganha o token da partição logo depois do tipo (`reconciler.action.core.user.<partição>.<resourceId>.<operação>`), com `N = 4` em `bootstrap/action.json`; o Executor roda um laço por partição.
- **Não aplicado ao Observer nem ao `DESIRED`.** Particionar o `DESIRED` mudaria o Subject armazenado, que o Executor usa na leitura por Direct Get do `desired`. O Observer mantém `hash(resourceId) mod count` na aplicação até haver carga medida que justifique a mudança.

### 2. Servidor de saúde em todo componente

Todo componente expõe um servidor HTTP mínimo, na porta `8000`, com **três rotas somente de leitura**:

| Rota | Significado | Consulta dependências externas? |
|---|---|---|
| `/health/live` | O laço principal deu sinal de vida recentemente | **Não** |
| `/health/ready` | A inicialização terminou e as verificações críticas (NATS, banco) estão em dia | Sim |
| `/health/startup` | A inicialização terminou | Não |

- A **liveness não consulta dependências** externas: uma queda do NATS ou do banco não deve reiniciar todos os pods, só tirá-los de `ready`.
- Não existem `/config`, `/info` nem `/version`: seriam superfície de ataque sem necessidade (`AGENTS.md` §4), e a versão está na imagem.
- Sem biblioteca: o protocolo necessário é uma linha de pedido e uma resposta JSON. Cada componente tem a sua cópia (decisão 0015: sem código compartilhado).
- Em dev, o healthcheck do Compose usa `/health/ready`. No Kubernetes, `startupProbe`, `livenessProbe` e `readinessProbe` apontam para as três rotas.

### 3. Erro permanente do relay

A publicação classifica a recusa do transporte:

- **transitória** (indisponível, tempo esgotado): repete com *backoff* exponencial até 30 s, mantendo a ordem;
- **permanente** (mensagem grande demais ou inválida, ou seja, uma recusa que repetir não resolve): **continua preservando a ordem**, registra `ERROR` com `sequence` e `message_id`, e o relay sai de `ready` (verificação `publication`), para o problema aparecer no orquestrador e em alertas.

Não se descarta nem se pula a mensagem: pular quebraria a ordem por recurso, e descartar perderia evento. A saída (corrigir a causa, ou retirar a mensagem por procedimento humano) é uma atuação explícita.

## Justificativa

- Delegar a ordem ao Stream elimina código de partição em cada componente e funciona igual em qualquer linguagem (decisão 0015).
- Tornar o bloqueio **visível** resolve o problema real (ninguém percebia) sem acrescentar uma coluna de tentativas, uma fila de mensagens mortas ou um papel de banco novo (`AGENTS.md` §6).
- Liveness sem dependências evita a reinicialização em cascata, que piora uma indisponibilidade em vez de resolvê-la.
- Alternativas descartadas: pular a mensagem permanente (quebra a ordem); fila de mensagens mortas no outbox (exige coluna e privilégio novos, sem necessidade medida); biblioteca interna de saúde (prende todos à mesma linguagem).

## Consequências

- Implementado nos cinco papéis de `core.user`: `http/health.py` em cada componente (no Receiver, rotas no próprio app), `outbox/relay.py` e `transport/publisher.py` no Manager, com testes. A Organization adota ao ser derivada do User.
- `docs/messaging/NATS.md` passa a descrever a partição, a saúde e a política do relay.
- A `Nats-Expected-Last-Subject-Sequence` como endurecimento adicional do relay foi testada e funciona, mas **não** é adotada agora: depende da partição aplicada e não tem necessidade medida.

## Verificação de resiliência

Os testes e2e do User (`features/core/user/tests/e2e/tests/test_chaos.py`, com `E2E_CHAOS=1`) derrubam o Manager, o Executor e o relay durante um cadastro e verificam que o trabalho não se perde e o loop converge quando o componente volta.

## Pendente

- Substituir o `max_ack_pending=1` sem `pinned_client` por `pinned_client` antes de stg e prd (`docs/messaging/NATS.md` §7.5).
- Avaliar a partição do Observer quando houver carga medida.
- A topologia de implantação (`maintain` como terceiro modo do Manager, *sidecar* do relay, KEDA em stg e prd) **não** está decidida aqui: segue como proposta aguardando confirmação.
