---
name: NATS
description: Guia de procedimentos para projetar, inspecionar, alterar, validar e diagnosticar a mensageria em NATS e JetStream definida em docs/MESSAGING.md e docs/NATS.md. Use ao criar ou revisar Streams, Consumers, Subjects, autorização ou ao diagnosticar backlog, redelivery e duplicidade.
---

# NATS

## 1. Papel desta skill

Esta skill é um **guia de procedimentos** que chama ferramentas (CLI `nats`, leitura de arquivos de configuração, pipeline de infraestrutura). Ela não define regras.

```text
AGENTS.md
    ↓
docs/MESSAGING.md   → semântica
    ↓
docs/NATS.md        → implementação em NATS
    ↓
esta skill          → procedimento
```

Não redefina aqui Streams, retenção, Consumers, autorização ou nomenclatura: leia `docs/NATS.md`. Em conflito, os documentos prevalecem.

Não use esta skill para decidir semântica de mensagem (use o agent `messaging`).

## 2. Regras de operação

1. **Leitura por padrão.** Os procedimentos de projeto, inspeção, validação e diagnóstico só leem.
2. **Mutação é declarativa e aprovada.** Streams e Consumers duráveis são criados pela infraestrutura a partir de configuração versionada (`docs/NATS.md`, administração). O agente prepara e revisa a configuração; a aplicação ocorre pelo pipeline da infraestrutura ou com aprovação explícita do operador.
3. **Sem comandos interativos.** Use sempre flags e arquivos de configuração (`--config`, `-j`), nunca assistentes interativos.
4. **Sem efeito colateral em produção.** `nats consumer next` consome e confirma mensagem; publicar mensagem de teste altera estado. Só em ambiente de teste e com subject de teste.
5. **Credenciais.** Use `nats context` ou variáveis de ambiente do ambiente. Nunca coloque credenciais na linha de comando, em log ou na resposta.
6. **Operações destrutivas** (apagar Stream ou Consumer, `purge`, reduzir retenção) exigem confirmação explícita do operador. Serviços de runtime nunca recebem essas permissões (`docs/NATS.md`).
7. **Não invente** nomes de arquivos, contextos, servidores ou versões. Se não existirem, informe e pare.
8. Confirme as flags da CLI na versão pinada do ambiente; este guia não fixa versão.

## 3. Procedimento A: projetar um fluxo ou mensagem

Entradas: o recurso (`<módulo>.<tipo>`) e o `messageType`.

1. Ler `docs/MESSAGING.md` e `docs/NATS.md` (Subjects, Streams, Consumers).
2. Classificar a mensagem: **trabalho**, **estado** ou **fato** (`docs/MESSAGING.md`).
3. Derivar, a partir de `docs/NATS.md`, e registrar em uma tabela:
   - Subject (gramática oficial);
   - Stream do `messageType` e sua retenção;
   - Consumers por serviço, com classe, filtro único `<módulo>.<tipo>` e nome;
   - política de ACK, retry, `max_deliver`, backoff e quarentena;
   - `Nats-Msg-Id` (quando aplicável) e a deduplicação obrigatória do consumidor;
   - autorização por serviço (publish e consumo).
4. Conferir a janela de recuperação (`docs/NATS.md`): retenção maior ou igual.
5. Entregar a tabela para revisão. Não aplique nada.

## 4. Procedimento B: inspecionar o estado atual (somente leitura)

Ferramentas e o que cada uma responde:

| Pergunta | Ferramenta |
|---|---|
| Quais Streams existem? | `nats stream ls` |
| Como está um Stream (retenção, limites, mensagens, `allow_direct`)? | `nats stream info <STREAM> -j` |
| Quais Consumers existem e como estão? | `nats consumer ls <STREAM>` e `nats consumer info <STREAM> <CONSUMER> -j` |
| Qual o último estado de um recurso? | `nats stream get <STREAM> --last-for <SUBJECT>` |
| Como está o servidor e o JetStream? | `nats server report jetstream` |

Registre a evidência (saída resumida, sem credenciais) e compare com `docs/NATS.md`. Divergência é um achado, e não uma correção automática.

## 5. Procedimento C: alterar Streams ou Consumers

1. Executar o Procedimento B e guardar o estado atual (rollback).
2. Escrever a configuração desejada em arquivo, derivada do Procedimento A, no local de configuração que a infraestrutura do projeto definir. Se não houver, informar e parar.
3. Revisar a diferença entre o estado atual e o desejado, e classificar o risco: reduzir retenção, alterar filtro e remover Consumer são destrutivos.
4. **Pedir aprovação** para a aplicação.
5. Aplicar pelo pipeline da infraestrutura. Na ausência dele e com aprovação, usar o equivalente não interativo: `nats stream add <STREAM> --config <arquivo>` e `nats consumer add <STREAM> <CONSUMER> --config <arquivo>`.
6. Repetir o Procedimento B e confirmar que o estado final corresponde ao desejado.
7. Registrar o resultado e como reverter.

## 6. Procedimento D: validar um fluxo (somente em ambiente de teste)

1. Confirmar que o ambiente é de teste e usar um Subject de teste dentro do escopo autorizado.
2. Publicar duas vezes a mesma mensagem com o mesmo `Nats-Msg-Id`: `nats pub <SUBJECT> <CORPO> -H "Nats-Msg-Id:<ID>"`. Confirmar com `nats stream info` que apenas uma foi armazenada.
3. Verificar o consumo com `nats sub <SUBJECT> --count=1` ou, para Consumer pull de teste, `nats consumer next`, sabendo que isso confirma a mensagem.
4. Verificar redelivery (não confirmar dentro de `ack_wait`), retry com backoff e quarentena após `max_deliver`.
5. Para Consumer de estado: reiniciar a instância de teste e confirmar que o último estado por Subject é reconstruído (`DeliverLastPerSubject`).
6. Remover as mensagens e Consumers de teste.

## 7. Procedimento E: diagnosticar

| Sintoma | Verificar com | Observação |
|---|---|---|
| Mensagem duplicada no Stream | `nats stream info` (duplicates), cabeçalho `Nats-Msg-Id` | Retries devem reutilizar o mesmo `messageId`. A janela de deduplicação é limitada |
| Processada duas vezes | `nats consumer info` (redelivered, ack pending) | Redelivery não é falha do broker. Verificar tempo de ACK, queda de instância e idempotência |
| Backlog crescente | `nats consumer info` (num_pending, ack pending) | Não aumentar retenção para compensar consumidor lento |
| Fora de ordem | Consumers, `orderingKey`, concorrência | Stream não garante ordem de negócio |
| Estado não reconstruído após restart | Política de entrega do Consumer da instância | `DeliverLastPerSubject` só vale na criação do Consumer; o nome deve ser único por execução |
| Consumer recusado na criação | Filtros do Stream `WorkQueue` | Filtros sobrepostos são rejeitados |
| Permissão negada | Autorização por Stream, consumer e filtro | Nunca ampliar permissão para contornar |

## 8. Critérios de conclusão

Registre cada item como `PASS`, `FAIL` ou `NOT VERIFIED` (com o motivo). Não transforme item não executado em sucesso.

```text
NATS

Semântica (Subject, classe, Stream):   PASS/FAIL/NOT VERIFIED
Consumers (classe, filtro, nome):      PASS/FAIL/NOT VERIFIED
Retenção x janela de recuperação:      PASS/FAIL/NOT VERIFIED
Deduplicação e idempotência:           PASS/FAIL/NOT VERIFIED
ACK, retry, quarentena:                PASS/FAIL/NOT VERIFIED
Autorização (menor privilégio):        PASS/FAIL/NOT VERIFIED
TLS e segredos:                        PASS/FAIL/NOT VERIFIED
Observabilidade:                       PASS/FAIL/NOT VERIFIED

Overall: PASS/FAIL
```

## 9. Skills complementares

Quando estiverem disponíveis no harness, as skills do ecossistema NATS (publicação e assinatura, JetStream, consumers, clusters, replicação, configuração de servidor) podem apoiar a execução. Esta skill não depende delas, e a sua disponibilidade não foi verificada.

## 10. Regra final

```text
contrato semântico (MESSAGING.md)
        ↓
mapeamento NATS (NATS.md)
        ↓
configuração declarativa revisada
        ↓
aplicação aprovada
        ↓
validação operacional
```

Nunca inverter a ordem criando a semântica a partir da conveniência de uma configuração NATS.
