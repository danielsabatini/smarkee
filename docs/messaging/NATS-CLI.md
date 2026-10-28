# Operação e validação do NATS pela CLI

> **Escopo:** guia prático para **ver o que está acontecendo** no NATS de desenvolvimento (Streams, Consumers, Subjects e mensagens) usando a CLI `nats`, sem interface gráfica. A semântica das mensagens é de [`MESSAGING.md`](MESSAGING.md) e o desenho de Streams e Consumers é de [`NATS.md`](NATS.md): este documento não os redefine, só diz **como inspecioná-los**.
>
> **Base da verificação:** comandos executados em 2026-10-28 contra o `smarkee-dev` (servidor NATS 2.15.1; CLI `nats` 0.4.0 no host e 0.5.0 na imagem `smarkee-nats-client`). O que não foi possível verificar está na seção 10.

# 1. Quando usar

| Pergunta | Seção |
|---|---|
| O broker está de pé e o JetStream saudável? | [4](#4-verificação-rápida-de-saúde) |
| Que Streams existem, com quantas mensagens? | [5](#5-streams) |
| Que Consumers existem e algum está atrasado? | [6](#6-consumers) |
| Minha mensagem chegou? O que ela contém? | [7](#7-ler-mensagens) |
| Sintoma → o que olhar | [8](#8-receitas-de-diagnóstico) |

# 2. Preparação

## 2.1 Conexão pelo host

O NATS de dev publica `127.0.0.1:4222` (`nats.conf` e `infrastructure/dev/messaging/compose.yaml`). A CLI lê a conexão de variáveis de ambiente, então a senha **não** vai na linha de comando nem no histórico do shell:

```bash
export NATS_URL=nats://127.0.0.1:4222
export NATS_USER=smarkee   # SMARKEE_MESSAGING_USER (padrão do compose)
export NATS_PASSWORD=$(grep '^SMARKEE_MESSAGING_PASSWORD=' infrastructure/dev/messaging/.env | cut -d= -f2-)
```

Teste:

```bash
nats server check connection
# OK Connection OK:connected to nats://127.0.0.1:4222 ...
```

Senha errada ou ausente responde `Authorization Violation` (ver seção 8.7).

## 2.2 Sem a CLI instalada: pela imagem do projeto

A imagem `smarkee-nats-client` (a mesma dos contêineres `messaging-bootstrap-*`) tem a CLI. Rode-a na rede `internal`, passando as variáveis sem o valor da senha:

```bash
docker run --rm --network internal \
  -e NATS_URL=nats://messaging.smarkee.internal:4222 -e NATS_USER -e NATS_PASSWORD \
  smarkee-nats-client:dev nats stream ls -n
```

## 2.3 `jq`

As receitas de leitura de mensagens usam `jq`.

# 3. Regras de segurança

Em dev há **um único usuário** compartilhado por todos os serviços, com poder total (`nats.conf`). Nada impede um comando destrutivo.

| Tipo | Comandos | Regra |
|---|---|---|
| **Leitura (seguros)** | `stream ls\|info\|report\|subjects\|get`, `consumer ls\|info\|report`, `server check`, `account info`, `rtt`, `sub` com `--stream`, `curl` no `:8222` | Use à vontade |
| **Efeito colateral** | `pub`, `consumer next`, `sub --ack`, `consumer add`, `stream add\|edit` | Só com Subject de teste e fora dos Streams (ver 8.9). `consumer next` e `--ack` **confirmam** mensagens e alteram o progresso de quem lê |
| **Destrutivos** | `stream purge\|rm`, `consumer rm`, `stream rmm` | **Peça confirmação.** Em `DESIRED` e `OBSERVED` (um estado por recurso) um purge apaga o estado vigente de todos os tipos |

Outras regras:

- Nunca publique em Subject de um Stream (`desired.>`, `updated.>` etc.) para "testar": a mensagem é gravada e consumida pelos serviços reais.
- Não cole a senha em comando, log, issue nem na saída que você compartilhar.
- Alterar Streams e Consumers é declarativo (`infrastructure/dev/messaging/bootstrap/*.json`, [`NATS.md`](NATS.md) seção 25), e não por comando manual.

# 4. Verificação rápida de saúde

```bash
nats server check connection          # conecta e mede o RTT
nats server check jetstream           # armazenamento, Streams, Consumers, réplicas
nats stream report                    # visão geral de todos os Streams
curl -s http://127.0.0.1:8222/healthz # {"status":"ok"}
nats account info                     # uso do JetStream da conta
```

Saída saudável de `check jetstream` (dev, 1 réplica):

```text
OK JetStream | ... streams=3 consumers=... replicas_ok=3 replicas_no_leader=0 replicas_missing_replicas=0 ...
```

Esperado: `streams=3` (`DESIRED`, `UPDATED`, `AUDIT`) e `replicas_no_leader=0`. O número de Consumers varia com as instâncias em execução (ver 6.2).

As verificações `server check` seguem o formato de plugin de monitoramento: a primeira palavra da saída é `OK`, `WARNING` ou `CRITICAL`.

# 5. Streams

## 5.1 Listar e resumir

```bash
nats stream ls -n        # só os nomes
nats stream report       # mensagens, bytes e Consumers por Stream
nats stream info DESIRED # configuração e estado completos
```

`stream info` mostra o que decide o comportamento: `Subjects`, `Retention`, `Discard Policy`, `Maximum Per Subject`, `Maximum Age`, `Direct Get` e, em `State`, `Messages`, `First/Last Sequence` e `Active Consumers`.

Em JSON, para extrair campos:

```bash
nats stream info DESIRED -j | jq '{subjects:.config.subjects, max_per_subject:.config.max_msgs_per_subject,
  msgs:.state.messages, first:.state.first_seq, last:.state.last_seq, consumers:.state.consumer_count}'
```

## 5.2 O que esperar de cada Stream

O desenho está em [`NATS.md`](NATS.md) seção 6. Em dev, confira contra o broker em execução (valores lidos em 2026-10-28):

| Stream | Retenção observada | Uso em dev hoje |
|---|---|---|
| `DESIRED` | `limits`, 1 mensagem por Subject, sem `MaxAge`, `allow_direct` | **Em uso:** último `desired` de cada recurso |
| `UPDATED` | `limits`, `MaxAge` 24 h | **Em uso:** fatos `updated` |
| `OBSERVED` | `limits`, 1 por Subject, `MaxAge` 24 h | Vazio: nenhuma feature o usa mais (decisões 0096, 0098 e 0100) |
| `REQUESTED`, `ACTION` | `workqueue`, `DiscardNew` | Vazios, pelo mesmo motivo |
| `RESULT` | `limits`, `MaxAge` 72 h, `allow_direct` | Vazio, pelo mesmo motivo |

`ACTION` tem `subject_transform` com partição: o Subject **armazenado** difere do publicado (`NATS.md` seção 7.5). Hoje ele está vazio.

Um Stream vazio **não é defeito** nas condições acima.

## 5.3 Subjects retidos

```bash
nats stream subjects DESIRED                        # todos, com a contagem
nats stream subjects DESIRED 'desired.ipm.role.>'  # filtrando
```

Em `DESIRED` a contagem é sempre 1 por Subject (`MaxMsgsPerSubject=1`): cada linha é um recurso. Um `resourceId` que não aparece aqui nunca teve `desired` publicado, ou foi limpo.

# 6. Consumers

## 6.1 Listar e ver o estado

```bash
nats consumer ls DESIRED -n      # nomes
nats consumer report DESIRED     # tabela: Ack Pending, Redelivered, Unprocessed, Ack Floor
nats consumer info DESIRED <nome-do-consumer>
```

Campos que respondem "está atrasado?" em `consumer info`:

| Campo (`-j`) | Significa | Problema quando |
|---|---|---|
| `num_pending` ("Unprocessed Messages") | Mensagens do Stream ainda não entregues a este Consumer | Cresce sem parar (consumidor parado ou lento) |
| `num_ack_pending` ("Outstanding Acks") | Entregues e ainda sem ACK | Fica alto/estável (processando devagar ou travado) |
| `num_redelivered` | Mensagens reentregues | Sobe (falha de processamento, `ack_wait` curto, instância que caiu) |
| `num_waiting` ("Waiting Pulls") | Pulls abertos do Consumer pull | `0` em um Consumer que deveria ter leitor: ninguém está lendo |
| `delivered.stream_seq` / `ack_floor.stream_seq` | Posição entregue e confirmada | `ack_floor` muito atrás de `delivered` |

`delivered.stream_seq: 0` em um Consumer de `DeliverLastPerSubject` sem mensagens novas é normal.

## 6.2 Nomes e instâncias

Os Consumers de dev seguem `<módulo>-<tipo>-<papel>-<...>-<sufixo>`, em que o sufixo hexadecimal de 8 caracteres identifica a **execução do processo** (por exemplo, `ipm-organization-controller-desired-3deaf8e9`). Isso é o descrito em [`NATS.md`](NATS.md) seção 7.4. Consequências:

- Após reiniciar um serviço aparece um Consumer novo com sufixo novo. O antigo é removido pelo servidor após o `inactive_threshold` (`5m0s` no Controller observado). Vê-los em dobro por alguns minutos é normal.
- Os papéis em uso hoje são `api` (projeções), `controller` e `publisher` (decisões 0096, 0098 e 0100). Os papéis `manager`, `observer`, `reconciler` e `executor` da tabela de [`NATS.md`](NATS.md) seção 7.6 são o desenho de referência; nenhuma feature em dev os usa.

## 6.3 Quem está atrasado (varredura)

Mostra apenas Consumers com pendência, sem ACK ou reentrega, em todos os Streams. Saída vazia significa que ninguém está atrasado:

```bash
for s in $(nats stream ls -n); do
  for c in $(nats consumer ls "$s" -n); do
    nats consumer info "$s" "$c" -j | jq -r --arg s "$s" --arg c "$c" \
      '[$s,$c,.num_pending,.num_ack_pending,.num_redelivered]|@tsv'
  done
done | awk -F'\t' '$3>0||$4>0||$5>0'
```

São uma chamada por Consumer (cerca de 50 em dev).

## 6.4 Verificação com limiar

Útil em scripts. Falha (`CRITICAL`) ao passar do limite:

```bash
nats server check consumer --stream DESIRED --consumer <nome> \
  --unprocessed-critical 100 --redelivery-critical 5 --outstanding-ack-critical 100
# OK DESIRED_<nome> OK:Ack Pending: 0 OK:Unprocessed Messages: 0 OK:Redelivered: 0 | ...
```

Flags disponíveis (confirmadas em `--help`): `--unprocessed-critical`, `--redelivery-critical`, `--outstanding-ack-critical`, `--waiting-critical`, `--last-delivery-critical`, `--last-ack-critical` e `--pinned`. **Não existem** `--*-warn` neste comando.

Em `nats server check stream`, atenção: `--msgs-warn` e `--msgs-critical` são **mínimos** ("falha se houver *menos* que") e `--subjects-*` limitam os Subjects. Usar `--msgs-critical 5000` em um Stream com 3 mensagens retorna `CRITICAL`.

# 7. Ler mensagens

## 7.1 A mensagem mais recente de um recurso

O Subject de um recurso é `desired.<módulo>.<tipo>.<resourceId>` ([`NATS.md`](NATS.md) seção 3.6). Como `DESIRED` guarda o último estado, é aqui que se vê "o que a plataforma quer agora" para o recurso:

```bash
nats stream get DESIRED --last-for 'desired.ipm.serviceaccount.<resourceId>'
```

A saída traz o Subject, a sequência, o horário, os cabeçalhos (`Nats-Msg-Id`) e o corpo JSON. Por sequência:

```bash
nats stream get DESIRED 3
```

## 7.2 Decodificar com `jq`

Com `-j`, cabeçalhos e corpo vêm em base64. Decodifique e selecione os campos do envelope:

```bash
nats stream get DESIRED --last-for '<subject>' -j | jq '{
  subject, seq, time,
  headers: (.hdrs | @base64d),
  payload: (.data | @base64d | fromjson
    | {messageId, resourceType, resourceId, desiredGeneration, correlationId, publishedBy, lifecycle: .data.lifecycle})
}'
```

Campos do envelope que mais ajudam a depurar (definidos em [`MESSAGING.md`](MESSAGING.md)): `desiredGeneration` (qual versão do desejado), `correlationId` (liga a mensagem ao pedido que a originou), `publishedBy` (qual publisher emitiu), `occurredAt`/`publishedAt` (atraso entre o fato e a publicação) e `data.lifecycle`.

## 7.3 Percorrer várias mensagens (`sub` com `--stream`)

`nats sub` com `--stream` abre um Consumer **efêmero, sem ACK**, que lê o Stream sem alterar o progresso dos serviços:

```bash
# último estado de cada recurso de um módulo, só cabeçalhos
nats sub --stream DESIRED --last-per-subject --headers-only 'desired.ipm.>'

# tudo que o Stream retém (útil em UPDATED)
nats sub --stream UPDATED --all 'updated.>'

# só o corpo, pronto para o jq
nats sub --stream DESIRED --last-per-subject --raw 'desired.ipm.serviceaccount.>' 2>/dev/null \
  | jq -c '{resourceId, desiredGeneration, publishedBy}'
```

Observações verificadas:

- O comando **fica aguardando** novas mensagens depois de entregar as retidas. Use `--count N` ou interrompa com `Ctrl+C`.
- `--count N` pode entregar **mais** de N mensagens quando combinado com `--last-per-subject` (observado: pedi 2 e recebi 3). Não conte com o número exato.
- O Consumer efêmero aparece em `consumer ls` durante a leitura (observado 50 → 51 → 50) e some depois.
- Use `-n`/`--headers-only` para listar sem renderizar corpos grandes.

## 7.4 `nats stream view`

`nats stream view <STREAM>` é o navegador interativo de mensagens, mas **exige um terminal real**: em pipe, script ou ferramenta sem TTY falha com `interactive stream paging requires a valid terminal`. Nesses casos use `stream get` e `sub --stream`.

# 8. Receitas de diagnóstico

## 8.1 "Criei um recurso e ele não aparece no `DESIRED`"

1. Procure o Subject: `nats stream subjects DESIRED '<prefixo do módulo e tipo>.>'`.
2. Se a mensagem não está lá, o problema está **antes** do NATS: a API grava o `desired` no outbox e o `publisher` o publica ([`NATS.md`](NATS.md) seção 26.1). Confira se o publisher está `ready` (`/health/ready` na porta `8000`, só na rede `internal`) e o log dele. Um publisher bloqueado por recusa permanente sai de `ready` e registra `ERROR` ([`NATS.md`](NATS.md) seção 11.2).
3. Se a mensagem está lá, confirme `desiredGeneration` e `lifecycle` (7.2).

## 8.2 "Publicou, mas ninguém reagiu"

1. A mensagem está no Stream (8.1)?
2. O Consumer do serviço existe? `nats consumer ls DESIRED -n | grep <módulo>-<tipo>`.
3. Ele tem leitor? `nats consumer info ...`: `Waiting Pulls` deve ser maior que 0.
4. Há atraso? Varredura da seção 6.3.
5. Se houver `num_pending` > 0 com `num_waiting` = 0, o serviço está parado ou desconectado (seção 8.6).

## 8.3 "Está sendo reprocessado"

`nats consumer info` e veja `num_redelivered` e `num_ack_pending`. Redelivery não é falha do broker: pode ser processamento além do `Ack Wait` (30 s no padrão observado), instância que caiu ou erro retentável. A deduplicação e a idempotência são do consumidor ([`NATS.md`](NATS.md) seção 11).

## 8.4 "O que mudou entre duas versões do recurso?"

`DESIRED` guarda só a mais recente por recurso, então **não há histórico ali**. O que existe:

- `UPDATED` (fatos, retidos por 24 h): `nats sub --stream UPDATED --all --raw 'updated.<módulo>.<tipo>.>'`.
- O banco (SSOT) e o outbox: ver [`POSTGRESQL.md`](../data/POSTGRESQL.md).

## 8.5 Rastrear uma operação pelo `correlationId`

Procura, em cada Subject retido de um Stream, as mensagens com o `correlationId`:

```bash
C='<correlationId>'
for s in DESIRED UPDATED; do
  for q in $(nats stream subjects "$s" -j | jq -r 'keys[]'); do
    nats stream get "$s" --last-for "$q" -j \
      | jq -r --arg c "$C" --arg s "$s" 'select((.data|@base64d|fromjson|.correlationId)==$c)|[$s,.seq,.subject]|@tsv'
  done
done
```

Só enxerga a **última** mensagem por Subject. Para o traço completo da requisição use a telemetria ([`OBSERVABILITY.md`](../telemetry/OBSERVABILITY.md)).

## 8.6 Quem está conectado

```bash
curl -s 'http://127.0.0.1:8222/connz?limit=100' | jq -r '.connections[].name' | sort
```

Cada serviço se conecta com um nome (por exemplo, `ipm-user-publisher`, `sum-service-controller`). Um serviço ausente da lista não está conectado ao broker.

## 8.7 Falha de autenticação

- Pelo cliente: `nats server check connection` → `Authorization Violation`.
- Pelo broker: `docker logs messaging.smarkee.internal 2>&1 | grep 'authentication error'`.
  - Linha **sem** `User "..."`: o cliente conectou **sem enviar credencial** (cliente gráfico ou biblioteca sem usuário e senha configurados, ou com o modo de autenticação errado).
  - Linha **com** `User "smarkee"`: credencial enviada, mas senha incorreta.
- Compare a senha do `.env` com a do broker sem imprimi-la: os dois hashes devem ser iguais.

  ```bash
  p1=$(grep '^SMARKEE_MESSAGING_PASSWORD=' infrastructure/dev/messaging/.env | cut -d= -f2- | tr -d '\n' | shasum | cut -c1-12)
  p2=$(docker exec messaging.smarkee.internal sh -c 'printf %s "$NATS_PASSWORD"' | shasum | cut -c1-12)
  [ "$p1" = "$p2" ] && echo igual || echo diferente
  ```

  Se forem diferentes, o `.env` mudou depois que o broker subiu: recrie o `messaging`.

## 8.8 Publicar e assinar no Core (sem JetStream)

Para testar a conexão fora dos Streams, use um Subject que **nenhum Stream cobre**:

```bash
nats sub 'debug.meu-teste.>' --count 1 &
nats pub debug.meu-teste.ping '{"ok":true}'
```

Verificado: a mensagem chega ao assinante e nada é gravado.

## 8.9 O que **não** fazer para "testar" um Stream

Publicar em `desired.>`, `updated.>`, `audit.>` ou nos antigos subjects legados. A mensagem é persistida e consumida pelos serviços reais. Para validar publicação e deduplicação com `Nats-Msg-Id`, siga o procedimento D da skill `nats`, em Subject de teste dentro do escopo autorizado.

# 9. Monitoramento HTTP (`:8222`)

Sem autenticação, publicado só em `127.0.0.1` (`infrastructure/dev/README.md`). É a mesma fonte do `messaging-exporter`.

| Endpoint | Para quê |
|---|---|
| `/healthz` | `{"status":"ok"}` |
| `/healthz?js-enabled-only=true` | Saúde com o JetStream habilitado |
| `/varz` | Versão, conexões, `slow_consumers`, mensagens de entrada e saída, memória, `uptime` |
| `/jsz?streams=true&consumers=true` | Streams e Consumers (use `limit` e `jq`) |
| `/connz?limit=100` | Conexões e seus nomes |

```bash
curl -s http://127.0.0.1:8222/varz | jq '{version, connections, slow_consumers, in_msgs, out_msgs, uptime}'
```

`slow_consumers` acima de zero indica um cliente que não acompanha o servidor.

# 10. Limitações e o que não foi verificado

**Limitações do ambiente dev**

- `nats server info`, `server ls`, `server report jetstream` e demais comandos de **sistema** falham com `ensure the account used has system privileges`: o usuário `smarkee` está na conta `$G` (`System Account: false`). Use `server check`, `account info`, `stream report` e o `:8222`.
- `nats context ls` retorna "No known contexts": nenhum contexto foi configurado; a conexão é por variáveis de ambiente.
- O `uptime` do broker em `/varz` mostra desde quando ele está de pé; um valor pequeno indica reinício recente (e Streams possivelmente recriados).

**Não verificado**

- `nats stream view` em terminal interativo (a verificação foi sem TTY).
- Acompanhar mensagens **novas** ao vivo (`nats sub --stream ... --new`) com tráfego real: para não publicar nos Streams, não gerei tráfego.
- `nats event --js-advisory`: conecta e escuta, mas não observei nenhum evento durante o teste. Os avisos de reentrega máxima e de ACK terminado chegam por esse canal segundo a documentação do NATS, sem confirmação aqui.
- O código de saída de `server check` (a saída textual `OK`/`CRITICAL` foi confirmada).
- Comportamento em stg e prd: identidade por serviço e TLS ([`NATS.md`](NATS.md) seções 18 e 26) tornam esta conexão com usuário único inválida. Os comandos de leitura continuam valendo, com outro modo de autenticação.

# 11. Fonte de verdade

- Semântica das mensagens: [`MESSAGING.md`](MESSAGING.md).
- Streams, Consumers, Subjects, retenção e segurança: [`NATS.md`](NATS.md).
- Configuração real do broker: `infrastructure/dev/messaging/` (`nats.conf`, `compose.yaml`, `bootstrap/*.json`).
- Procedimentos do agente: skill `nats`. Este guia a complementa para a operação manual.
- CLI `nats`: https://docs.nats.io/using-nats/nats-tools/nats_cli
