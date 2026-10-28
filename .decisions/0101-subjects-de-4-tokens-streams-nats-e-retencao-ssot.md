# 0101. Subjects de 4 Tokens, Streams NATS Simplificados e Retenção no SSOT

**Data:** 2026-10-28  
**Status:** Aprovada  
**Decisões relacionadas:** 0015 (loop de 7 papéis, descontinuada por 0096/0098), 0019 (publisher), 0072 (geração observada), 0087 (banco ssot), 0096 (unificação do loop no controller), 0098 (api síncrona e fim da operation), 0100 (desacoplamento http e projeções desejado)

## Contexto

Com a evolução da arquitetura de controle de recursos pelas decisões 0096, 0098 e 0100:
1. O loop legado de 7 papéis (`receiver`, `manager`, `reconciler`, `executor`, `observer`) foi substituído por dois padrões consolidados: `internal-state` (`api` + `publisher`) e `external-reconciled` (`api` + `publisher` + `controller`).
2. A entidade `operation` foi eliminada, e as APIs realizam admissão síncrona diretamente no SSOT com outbox atômico.
3. Não existem mais mensagens do tipo `requested`, `action`, `observed` nem `result`. Portanto, os Streams `REQUESTED`, `OBSERVED`, `ACTION` e `RESULT` tornaram-se obsoletos no JetStream.
4. O formato anterior de Subjects NATS herdava 6 tokens (`<emitter>.<messageType>.<module>.<resourceType>.<resourceId>.<operation>`), contendo informações redundantes como o prefixo legado `manager.` e o sufixo fixo `.changed`.
5. As tabelas de `<tipo>_outbox` e `<tipo>_idempotency` no SSOT acumulavam registros indefinidamente, demandando uma política explícita de retenção com princípio de menor privilégio.

## Decisão

### 1. Formato Canônico dos Subjects NATS (4 Tokens)

Os Subjects do JetStream passam a ser padronizados estritamente no formato de 4 tokens:

```text
<messageType>.<module>.<resourceType>.<resourceId>
```

- **`messageType`:** restrito a `desired` ou `updated`.
- **`module`:** módulo da plataforma (ex: `core`, `bsm`, `sum`, `ipm`).
- **`resourceType`:** tipo do recurso (ex: `account`, `organization`, `permission`).
- **`resourceId`:** identificador opaco do recurso (UUIDv7).

O emissor (`emitter`) permanece declarado com validação estrita no envelope (`schemas/common/message-envelope.v1.schema.json`), restrito aos emissores vigentes: `api` ou `controller`. O campo `operation` no envelope é mantido como `"changed"`.

### 2. Topologia de Streams JetStream

O NATS JetStream consolida sua topologia em 3 streams:

1. **`DESIRED`:**
   - **Subjects:** `desired.>`
   - **Retenção:** `LimitsPolicy`, `max_msgs_per_subject: 1`, `allow_direct: true`, `max_age: 0` (indefinido), `max_bytes: 1G`, `max_msg_size: 512K`.
   - **Finalidade:** retém o último estado desejado de cada recurso para consumo do Informer do Controller e projeções locais da API.
2. **`UPDATED`:**
   - **Subjects:** `updated.>`
   - **Retenção:** `LimitsPolicy`, `max_msgs_per_subject: 1`, `allow_direct: true`, `max_age: 24h` (em dev), `max_bytes: 1G`, `max_msg_size: 512K`.
   - **Finalidade:** fatos consolidados de convergência emitidos pelo Controller para Console e observabilidade.
3. **`AUDIT`:**
   - **Fontes (Stream Sources):** `[{"name": "DESIRED"}, {"name": "UPDATED"}]`.
   - **Subjects:** `audit.>` (sem sobreposição direta de subjects com streams de origem).
   - **Retenção:** `LimitsPolicy`, `max_msgs_per_subject: -1` (todas as versões preservadas), `deny_delete: true` (proteção de integridade), `max_age: 24h` (em dev), `max_bytes: 1G`.

Os streams legados `REQUESTED`, `OBSERVED`, `ACTION` e `RESULT` foram formalmente removidos.

### 3. Retenção e Expurgo no SSOT

1. **Janela de Retenção Padrão:** 24 horas para:
   - `<schema>.<tipo>_outbox`: mensagens com `published_at IS NOT NULL` e `published_at < cutoff`.
   - `<schema>.<tipo>_idempotency`: registros com `created_at < cutoff`.
2. **Menor Privilégio:** a operação de expurgo utiliza estritamente as credenciais de manutenção de cada módulo (`core_maintenance_login`, `bsm_maintenance_login`, `sum_service_maintenance_login`, `ipm_maintenance_login`), possuindo unicamente `SELECT` e `DELETE` nas tabelas de outbox e idempotência. Nenhum papel de runtime possui permissão de `DELETE` nessas tabelas.
3. **Utilitário de Manutenção:** criado o utilitário `scripts/dev/retention` (`smarkee-dev-retention`), suportando:
   - Simulação segura em modo dry-run (padrão).
   - Execução com flag `--apply`.
   - Configuração da janela com `--older-than` (ex: `24h`, `7d`, ou `0s` para expurgo imediato em dev).
   - Filtragem seletiva por `--module`, `--type` e `--kind`.

## Consequências

- **Positivas:**
  - Simplificação radical dos Subjects NATS e eliminação de acoplamentos nominais com papéis extintos.
  - Otimização do JetStream com `allow_direct` e eliminação de 4 streams desnecessários.
  - Trilha de auditoria desacoplada e imutável via stream sources (`AUDIT`).
  - Banco de dados `ssot` protegido contra crescimento descontrolado do outbox e tabelas de idempotência.
  - Conformidade estrita aos pilares de Simplicidade, Robustez e Menor Privilégio.
- **Negativas/Atenção:**
  - Consumidores e testes precisam adotar obrigatoriamente os novos subjects de 4 tokens (`desired.<mod>.<type>.<id>` e `updated.<mod>.<type>.<id>`).
