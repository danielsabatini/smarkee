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

## 5. Fonte Única da Verdade (SSOT)

Em conformidade com o `AGENTS.md` (seção 24.1 - Relação com Agentes e Skills), esta skill fornece exclusivamente o checklist executivo de operação. 

**As políticas arquiteturais, limites de hardware, configurações do JetStream e especificações técnicas de Streams e Consumers do projeto NATS estão definidas em:**
👉 `docs/NATS.md`

Ao executar esta skill, **você deve consultar, ler e extrair a configuração adequada do `docs/NATS.md`** (e cruzar com a semântica em `docs/MESSAGING.md`). Não duplique conhecimento ou invente implementações que fujam da documentação oficial.

## 6. Procedimento para criar um novo fluxo

### 6.1 Definir semântica

Primeiro responder:

```text
Qual é o `messageType` (e sua classe: trabalho, estado ou fato)?
Qual é o recurso?
Qual é o module?
Quem é o emissor?
```

### 6.2 Definir identidade

Determinar:

```text
messageId
resourceId
orderingKey, se necessária
correlationId, se necessária
causationId, se necessária
```

### 6.3 Escolher entrega

Determinar:

```text
Work Distribution
ou
Fanout
```

### 6.4 Mapear para NATS

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

### 6.5 Validar recuperação

Confirmar:

```text
retention >= Recovery Window
```

### 6.6 Validar segurança

Confirmar:

```text
Publish permissions
Subscribe permissions
TLS/mTLS
secret handling
```

### 6.7 Validar operacionalmente

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

## 7. Checklist de implementação

### Semântica

- [ ] `desired`/`observed` correto.
- [ ] emissor explícito.
- [ ] destinatário não codificado indevidamente.
- [ ] module correto.
- [ ] Stream correto para o `messageType`.
- [ ] resource type correto.
- [ ] resourceId estável.
- [ ] messageId estável.

### Entrega

- [ ] Work Distribution ou Fanout definido.
- [ ] Pull Consumer usado para trabalho; consumer de estado em memória é por instância (não compartilhado).
- [ ] consumer com filtro único no nível `<módulo>.<tipo>`; sem purge ou administração de Stream para serviço de runtime.
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

## 8. Troubleshooting

### 8.1 Mensagem duplicada no Stream

Verificar:

```text
Nats-Msg-Id
Duplicate Window
identity generation
retry behavior
```

Confirmar que retries utilizam o mesmo identificador lógico.

### 8.2 Mensagem processada duas vezes

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

### 8.3 Backlog crescente

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

### 8.4 Mensagens fora de ordem

Verificar:

```text
orderingKey
parallel consumers
concurrency
routing strategy
```

Não assumir que a criação de um Stream por si só garante a ordem de negócio desejada.

### 8.5 Replay gera efeitos duplicados

Verificar idempotência do consumidor e proteção por geração/estado.

Replay deve ser tratado como uma nova execução do processamento, não como uma consulta passiva.

## 9. Critérios de conclusão

Uma alteração NATS está concluída quando:

- o Subject corresponde ao modelo semântico;
- Stream e Consumer possuem a política correta para a classe da mensagem (`docs/NATS.md`);
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

## 10. Regra final

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

## 11. Skills Complementares NATS

Sempre que apropriado, utilize e aproveite as informações operacionais especializadas disponíveis nas skills externas complementares do ecossistema NATS no harness:

- `nats-core-publish-subscribe`: Comunicação efêmera, pub/sub e subjects sem persistência.
- `nats-core-request-reply`: Comunicação síncrona RPC de alta performance.
- `nats-jetstream-cluster`: Topologia e HA do JetStream.
- `nats-jetstream-consumers`: Configuração avançada de Push e Pull consumers.
- `nats-jetstream-kv`: Configuração e operação de Key-Value Store nativo.
- `nats-jetstream-replicate`: Topologia Hub-Spoke, Mirroring, Source e Leaf Nodes.
- `nats-jetstream-streams`: Configuração profunda, limits, retenção e storage em disco/memória de streams persistentes.
- `nats-operations-configure-server`: Definição e tuning do `nats.conf` e hardware (limits/OOM/auth).

## 12. Comandos e Procedimentos Operacionais (NATS CLI)

Como uma skill focada em operação, utilize os seguintes comandos para materializar e verificar a configuração do NATS.

### 12.1 Gerenciamento de Streams

```bash
# Adicionar um novo stream interativamente
nats stream add <nome-do-stream>

# Visualizar a configuração de um stream existente
nats stream info <nome-do-stream>

# Atualizar retenção ou limites de um stream
nats stream edit <nome-do-stream>

# Listar todos os streams
nats stream ls
```

### 12.2 Gerenciamento de Consumers

```bash
# Criar um consumer (push ou pull) interativamente
nats consumer add <nome-do-stream> <nome-do-consumer>

# Inspecionar detalhes e fila de um consumer
nats consumer info <nome-do-stream> <nome-do-consumer>

# Testar consumo via Pull
nats consumer next <nome-do-stream> <nome-do-consumer>

# Listar consumers atrelados a um stream
nats consumer ls <nome-do-stream>
```

### 12.3 Testes e Validação de Mensagens

```bash
# Publicar uma mensagem com Nats-Msg-Id (Deduplicação)
nats pub <subject> "payload" -H "Nats-Msg-Id:<id-unico>"

# Assinar um subject para depuração em tempo real
nats sub <subject>
```
