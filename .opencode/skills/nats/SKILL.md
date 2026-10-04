---
name: NATS
description: Implementar, configurar, revisar e validar a arquitetura de mensageria definida em MESSAGING.md usando NATS e NATS JetStream.
---

# NATS

## 1. Introdução

Esta skill define o procedimento para implementar e validar em NATS e NATS JetStream o modelo semântico estabelecido em `docs/MESSAGING.md`.

A especificação de implementação está em `docs/NATS.md`.

A skill é um procedimento operacional. Ela não redefine a semântica de `desired`, `observed`, identidade de mensagem, ordering, idempotência ou Recovery Window.

Regras gerais permanecem em `AGENTS.md`.

## 2. Objetivo

Executar mudanças e validações NATS de forma previsível, segura, idempotente e compatível com a arquitetura semântica.

A skill deve ser utilizada para:

- projetar Subjects;
- projetar Streams;
- projetar Consumers;
- configurar entrega de trabalho e fanout;
- configurar ACK e redelivery;
- configurar `Nats-Msg-Id` e deduplicação;
- configurar ordering quando necessário;
- configurar retenção e replay;
- configurar TLS/mTLS e autorização;
- diagnosticar problemas de consumo;
- verificar a implementação contra `MESSAGING.md` e `NATS.md`.

## 3. Fontes de verdade

Antes de executar qualquer mudança, consultar:

```text
AGENTS.md
    ↓
docs/MESSAGING.md
    ↓
docs/NATS.md
```

A semântica definida em `MESSAGING.md` tem precedência sobre qualquer escolha de implementação.

A configuração concreta deve obedecer `NATS.md`.

Não criar uma implementação NATS baseada apenas em memória, convenção ou conhecimento implícito quando a documentação do projeto já definir o comportamento.

## 4. Pré-requisitos

Antes de alterar NATS:

1. identificar o ambiente alvo;
2. identificar o servidor NATS e versão configurada;
3. localizar configuração do broker;
4. localizar definição de Streams;
5. localizar definição de Consumers;
6. identificar credenciais e certificados sem expô-los;
7. identificar os Subjects afetados;
8. identificar dependências dos consumidores;
9. verificar a janela de recuperação necessária;
10. verificar o impacto de retenção e volume.

Não inventar nomes de arquivos, endpoints, project IDs ou credenciais.

## 5. Mapear semântica para NATS

A referência lógica:

```text
<emitter>.<semanticType>.<scope>.<resourceType>[.<resourceId>]
```

é materializada como NATS Subject.

Exemplos:

```text
manager.desired.underlay.node.node-01
manager.desired.overlay.vm.vm-01
worker.platform.observed.underlay.node.node-01
worker.storage.observed.underlay.volume.volume-01
worker.agent.observed.overlay.agent.agent-01
```

O primeiro token identifica o emissor.

Para workers especializados, utilizar:

```text
worker.platform
worker.storage
worker.identity
worker.vault
worker.agent
worker.runner
worker.tools
```

Não colocar destinatário como uma dimensão obrigatória do Subject.

## 6. Validar Subjects

### 6.1 Estrutura

Verificar:

```text
<emitter>.<semanticType>.<scope>.<resourceType>[.<resourceId>]
```

### 6.2 Tokens

Cada token deve possuir significado estável.

Evitar adicionar `action`, `command`, `status` ou outra dimensão apenas para descrever detalhes do processamento.

Se a informação for parte do estado desejado, ela pertence ao payload `desired`.

Se for uma observação, pertence ao payload `observed`.

### 6.3 Identificadores

Quando `resourceId` participar do Subject, não utilizar `.` no valor.

Preferir identificadores estáveis e opacos.

Não utilizar nomes humanos como única chave quando eles puderem mudar ou colidir.

## 7. Wildcards

Utilizar wildcards com o menor escopo necessário.

Exemplos:

```text
manager.desired.>
manager.desired.underlay.>
manager.desired.overlay.>
worker.*.observed.>
worker.platform.observed.underlay.>
worker.storage.observed.underlay.volume.>
```

Evitar subscriptions de produção como:

```text
>
*
```

porque ampliam desnecessariamente o conjunto de mensagens recebidas.

## 8. Escolher Core NATS ou JetStream

### 8.1 Core NATS

Utilizar somente quando a semântica suportar comunicação efêmera e a perda durante indisponibilidade for aceitável.

Não utilizar Core NATS para mensagens que precisam sobreviver a reinício do consumidor, replay ou recuperação de backlog.

### 8.2 JetStream

Utilizar JetStream quando houver requisitos de:

- persistência;
- recuperação;
- replay;
- retry/redelivery;
- consumidores duráveis;
- retenção;
- processamento após indisponibilidade.

Mensagens `desired` e `observed` de controle de plataforma normalmente exigem JetStream quando a arquitetura depende de durabilidade.

## 9. Escolher a política de entrega

### 9.1 Work Distribution

Usar quando somente uma instância de um grupo deve processar o trabalho.

Padrão de referência:

```text
DESIRED Stream
      ↓
Pull Consumer
      ↓
worker-1 / worker-2 / worker-N
```

Várias réplicas compartilham a carga.

### 9.2 Fanout

Usar quando múltiplos consumidores independentes precisam receber a mesma mensagem.

Padrão de referência:

```text
OBSERVED Stream
      ↓
+-----+-----+-----+
|     |     |     |
manager billing audit
```

Cada consumidor possui seu próprio progresso.

## 10. Streams

A divisão de Streams deve seguir:

- política de retenção;
- semântica de entrega;
- volume;
- recuperação;
- segurança;
- ciclo de vida operacional.

Evitar criar Stream por recurso sem necessidade.

### 10.1 `DESIRED`

Referência:

```text
Stream: DESIRED
Subjects: manager.desired.>
```

Usar WorkQueue quando o fluxo representa trabalho consumido por um grupo lógico de reconciliação.

### 10.2 `OBSERVED`

Referência:

```text
Stream: OBSERVED
Subjects: worker.*.observed.>
```

Usar retenção compatível com múltiplos consumidores independentes e com a janela de replay/recuperação definida pelo projeto.

### 10.3 `AUDIT`

Criar somente quando houver requisito de retenção histórica, replay controlado ou auditoria.

Não transformar auditoria em requisito obrigatório de toda mensagem.

## 11. Consumers

Para processamento de trabalho, preferir Pull Consumers duráveis.

Validar:

```text
consumer name
filter subject
ack policy
ack wait
max deliver
backoff
max ack pending
deliver policy
inactive threshold
```

O consumer deve representar uma função de processamento, não uma instância efêmera.

## 12. Pull Consumer e backpressure

O worker deve controlar quanto trabalho busca.

Fluxo recomendado:

```text
fetch
  ↓
process
  ↓
side effect
  ↓
verify result
  ↓
ACK
```

Não ACKar antes de o processamento atingir o ponto de segurança definido pelo contrato.

A capacidade de fetch deve ser compatível com memória, concorrência e tempo de processamento.

## 13. ACK, redelivery e falhas

Assumir entrega pelo menos uma vez.

Um timeout ou crash antes do ACK pode provocar redelivery.

Nunca tratar redelivery como erro excepcional de arquitetura.

O consumidor deve suportar:

```text
message
  ↓
process
  ↓
crash
  ↓
redelivery
```

### 13.1 ACK

ACK significa confirmação de processamento segundo a política do consumidor.

ACK não significa:

- convergência do recurso;
- ausência de duplicação futura;
- sucesso histórico permanente;
- confirmação do sistema externo em todos os casos.

### 13.2 NAK / retry

Utilizar retry/backoff quando o erro for transitório.

Não realizar loop agressivo de retry sem backoff.

Erros permanentes devem avançar para a política de quarentena definida pelo projeto.

## 14. `Nats-Msg-Id` e deduplicação

`Nats-Msg-Id` é um mecanismo central de deduplicação de publicação do JetStream.

Quando a mesma mensagem lógica for publicada novamente dentro da janela de deduplicação do Stream, o produtor deve reutilizar o mesmo identificador de mensagem.

Mapeamento recomendado:

```text
MESSAGING.md
messageId
    ↓
NATS
Nats-Msg-Id
```

O valor deve representar a identidade lógica da mensagem.

Não gerar um novo `Nats-Msg-Id` em cada retry de uma mesma mensagem.

## 15.1 O que `Nats-Msg-Id` resolve

Ele protege o Stream contra duplicações de publicação reconhecíveis dentro da janela configurada.

Exemplo:

```text
publish messageId=A
        ↓
network timeout
        ↓
producer não sabe se foi aceito
        ↓
publish novamente com Nats-Msg-Id=A
```

O JetStream pode reconhecer a segunda publicação como duplicada dentro da janela configurada.

## 15.2 O que `Nats-Msg-Id` não resolve

Não tratar `Nats-Msg-Id` como substituto de idempotência do consumidor.

A mensagem ainda pode ser redelivered ao consumidor depois de uma falha posterior ao processamento.

Também não usar `Nats-Msg-Id` como garantia absoluta contra duplicação fora da janela de deduplicação.

## 15.3 `duplicate_window`

A janela deve ser dimensionada de acordo com:

```text
retry duration
+
maximum expected producer/network outage
+
operational recovery time
```

Uma janela pequena demais pode permitir uma publicação duplicada após recuperação de uma indisponibilidade prolongada.

Uma janela maior aumenta o custo de retenção da informação de deduplicação no servidor.

A escolha deve ser explícita e documentada.

## 16. Idempotência do consumidor

Implementar proteção adicional no processamento.

Modelo:

```text
             +------------------+
publish ---> | Nats-Msg-Id      |
             | broker dedup     |
             +------------------+
                       ↓
             +------------------+
             | consumer         |
             | idempotency      |
             +------------------+
                       ↓
             +------------------+
             | reconciliation   |
             | / external state |
             +------------------+
```

Quando houver efeitos externos, utilizar identificadores, generations ou verificações que permitam reconhecer processamento anterior.

## 17. Ordering e `orderingKey`

Não assumir ordering global.

Quando `orderingKey` for necessária, mapear a chave de forma determinística para a implementação NATS.

Exemplo conceitual:

```text
orderingKey = resourceId
```

A estratégia precisa impedir que duas mensagens da mesma sequência sejam processadas em paralelo quando isso violar a semântica do recurso.

Não configurar `max_ack_pending=1` como padrão universal.

Usar serialização completa somente quando o requisito realmente existir.

## 18. Replay e Deliver Policy

O fluxo normal de um consumer novo deve iniciar conforme a política configurada para operação normal do projeto, normalmente `new` quando o consumidor não precisa reprocessar o backlog histórico.

Replay/backfill deve ser explícito.

Antes de executar replay:

1. identificar o intervalo;
2. avaliar efeitos externos;
3. confirmar idempotência;
4. avaliar ordering;
5. verificar retenção;
6. avaliar concorrência;
7. validar impacto operacional;
8. registrar a ação quando necessária para auditoria.

Não utilizar `all` indiscriminadamente em produção.

## 19. Retenção e Recovery Window

Calcular retenção com base na recuperação necessária.

Regra de referência:

```text
Stream retention
    >=
maximum recoverable consumer outage
```

Se o downstream depende do replay do Stream:

```text
Downstream retention
    >=
required replay window
```

Quando essa relação for um requisito de correção, transformá-la em configuração validável ou teste de invariância.

## 20. Quarentena / Dead Letter

Definir uma estratégia explícita para mensagens que ultrapassem o limite de retry.

O fluxo de referência:

```text
original message
      ↓
retry / redelivery
      ↓
max delivery reached
      ↓
quarantine / DLQ
      ↓
ACK ou terminação controlada da original
```

A implementação não deve perder silenciosamente a mensagem.

Preservar a identidade e o contexto original para diagnóstico.

## 21. Segurança NATS

Aplicar segurança por ambiente.

Fora do desenvolvimento local, utilizar TLS conforme `NATS.md`.

Para comunicação serviço-a-serviço, utilizar mTLS quando definido pelo ambiente.

Nunca colocar tokens ou chaves privadas em Subjects, código-fonte, logs ou arquivos versionados.

Configuração de autenticação deve utilizar mecanismos seguros do ambiente.

### 21.1 Autorização

Aplicar menor privilégio para Publish e Subscribe.

Exemplo conceitual:

```text
worker.platform
    publish → worker.platform.observed.>
    subscribe → manager.desired.underlay.node.>
```

Não conceder `>` global quando um filtro mais restrito for suficiente.

## 22. Observabilidade

Monitorar pelo menos:

- disponibilidade do broker;
- tamanho dos Streams;
- idade das mensagens;
- backlog dos Consumers;
- pending messages;
- redeliveries;
- ACK latency;
- falhas de publicação;
- falhas de consumo;
- mensagens em quarentena;
- estado de replicação quando aplicável;
- capacidade de armazenamento.

Backlog alto deve ser investigado como possível problema de capacidade, downstream ou falha de consumidor.

## 23. Diagnóstico operacional

Antes de alterar configuração, verificar o estado atual.

Comandos de referência, quando disponíveis no ambiente:

```text
nats server info
nats stream ls
nats stream info <stream>
nats consumer ls <stream>
nats consumer info <stream> <consumer>
nats stream view <stream>
```

Não executar comandos destrutivos sem confirmar escopo e impacto.

Não expor credenciais nos comandos ou na saída registrada.

## 24. Procedimento para criar um novo fluxo

### 24.1 Definir semântica

Primeiro responder:

```text
É desired ou observed?
Qual é o recurso?
Qual é o scope?
Quem é o emissor?
```

### 24.2 Definir identidade

Determinar:

```text
messageId
resourceId
orderingKey, se necessária
correlationId, se necessária
causationId, se necessária
```

### 24.3 Escolher entrega

Determinar:

```text
Work Distribution
ou
Fanout
```

### 24.4 Mapear para NATS

Definir:

```text
Subject
Stream
Retention
Consumer
Filter
Ack policy
Retry
MaxDeliver
Backoff
Dedup window
```

### 24.5 Validar recuperação

Confirmar:

```text
retention >= Recovery Window
```

### 24.6 Validar segurança

Confirmar:

```text
Publish permissions
Subscribe permissions
TLS/mTLS
secret handling
```

### 24.7 Validar operacionalmente

Confirmar:

- criação do Stream;
- criação do Consumer;
- publicação;
- deduplicação;
- consumo;
- ACK;
- redelivery;
- retry;
- quarentena;
- replay quando aplicável;
- ordering quando aplicável.

## 25. Checklist de implementação

### Semântica

- [ ] `desired`/`observed` correto.
- [ ] emissor explícito.
- [ ] destinatário não codificado indevidamente.
- [ ] scope correto.
- [ ] resource type correto.
- [ ] resourceId estável.
- [ ] messageId estável.

### Entrega

- [ ] Work Distribution ou Fanout definido.
- [ ] Pull Consumer usado para trabalho quando apropriado.
- [ ] ACK no ponto correto.
- [ ] retry definido.
- [ ] quarentena definida.

### Deduplicação

- [ ] `Nats-Msg-Id` configurado/usado.
- [ ] mesmo `messageId` em retries da mesma mensagem.
- [ ] `duplicate_window` dimensionada.
- [ ] consumidor idempotente.

### Ordering

- [ ] requisito de ordering explicitamente identificado.
- [ ] `orderingKey` definida quando necessária.
- [ ] concorrência compatível.
- [ ] não existe serialização desnecessária.

### Recuperação

- [ ] retention definida.
- [ ] Recovery Window definida.
- [ ] replay planejado quando necessário.
- [ ] deliver policy adequada.

### Segurança

- [ ] TLS/mTLS conforme ambiente.
- [ ] Publish ACL restrita.
- [ ] Subscribe ACL restrita.
- [ ] nenhum segredo em payload/Subject/log.

### Observabilidade

- [ ] backlog observável.
- [ ] redelivery observável.
- [ ] falhas observáveis.
- [ ] quarentena observável.
- [ ] armazenamento monitorado.

## 26. Troubleshooting

### 26.1 Mensagem duplicada no Stream

Verificar:

```text
Nats-Msg-Id
Duplicate Window
identity generation
retry behavior
```

Confirmar que retries utilizam o mesmo identificador lógico.

### 26.2 Mensagem processada duas vezes

Não concluir imediatamente que o broker falhou.

Verificar:

```text
ACK timing
consumer redelivery
worker crash
idempotency
external side effect
```

`Nats-Msg-Id` trata deduplicação de publicação; não elimina redelivery após falha de ACK/processamento.

### 26.3 Backlog crescente

Verificar:

```text
consumer status
num_pending
processing latency
external dependency latency
redelivery count
worker replicas
```

Não aumentar retenção como substituto para corrigir um consumidor incapaz de acompanhar a carga.

### 26.4 Mensagens fora de ordem

Verificar:

```text
orderingKey
parallel consumers
concurrency
routing strategy
```

Não assumir que a criação de um Stream por si só garante a ordem de negócio desejada.

### 26.5 Replay gera efeitos duplicados

Verificar idempotência do consumidor e proteção por geração/estado.

Replay deve ser tratado como uma nova execução do processamento, não como uma consulta passiva.

## 27. Critérios de conclusão

Uma alteração NATS está concluída quando:

- o Subject corresponde ao modelo semântico;
- Stream e Consumer possuem a política correta;
- `Nats-Msg-Id` é utilizado quando a deduplicação de publicação é necessária;
- retry/redelivery são seguros;
- idempotência do consumidor foi considerada;
- ordering atende apenas ao requisito necessário;
- retention atende à Recovery Window;
- replay possui comportamento conhecido;
- ACLs respeitam menor privilégio;
- TLS/mTLS atende ao ambiente;
- observabilidade permite detectar backlog e falhas;
- a implementação foi validada contra `docs/MESSAGING.md` e `docs/NATS.md`.

## 28. Regra final

A implementação deve seguir esta ordem:

```text
MESSAGING semantic contract
        ↓
NATS mapping
        ↓
JetStream configuration
        ↓
operational validation
```

Nunca inverter a ordem criando a semântica a partir da conveniência de uma configuração NATS.

## 29. Skills Complementares NATS

Sempre que apropriado, utilize e aproveite as informações operacionais especializadas disponíveis nas skills externas complementares do ecossistema NATS no harness:

- `nats-core-publish-subscribe`: Comunicação efêmera, pub/sub e subjects sem persistência.
- `nats-core-request-reply`: Comunicação síncrona RPC de alta performance.
- `nats-jetstream-cluster`: Topologia e HA do JetStream.
- `nats-jetstream-consumers`: Configuração avançada de Push e Pull consumers.
- `nats-jetstream-kv`: Configuração e operação de Key-Value Store nativo.
- `nats-jetstream-replicate`: Topologia Hub-Spoke, Mirroring, Source e Leaf Nodes.
- `nats-jetstream-streams`: Configuração profunda, limits, retenção e storage em disco/memória de streams persistentes.
- `nats-operations-configure-server`: Definição e tuning do `nats.conf` e hardware (limits/OOM/auth).
