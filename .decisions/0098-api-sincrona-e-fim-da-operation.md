# 0098 — API v1 síncrona (`api`) e fim da Operation e do Stream `REQUESTED`

- **Data:** 2026-10-27
- **Status:** Aceita para `ipm/serviceaccount` (piloto); `ipm/user` e `ipm/organization` seguem o mesmo molde. Reavalia a submissão assíncrona universal (decisões 0024 e 0091, no que dizem respeito à Operation e ao `requested`). Conforme AGENTS.md §2.1 (#2 Simplicidade, #3 Robustez, #4 Resiliência), §2.2, §2.7 (Kubernetes: o API server admite e persiste de forma síncrona; controllers reconciliam depois) e §25.1.

## Contexto

Todo pedido de escrita era aceito com `202 Accepted` pelo Receiver, publicado como `requested` no Stream `REQUESTED` e só então admitido pelo Manager, que validava (unicidade de nome, cota, vínculos, `deletionProtection`, chave duplicada) e gravava o recurso, a Operation e o outbox. Consequências observadas:

- um pedido inválido só era descoberto depois, por polling de `/operations/{id}`;
- o cliente recebia "aceito" sem saber se o recurso existiria;
- a tabela `*_operation`, a view, a rota `/operations`, o Stream, o consumer e um processo inteiro (Manager) existiam para recuperar, de forma assíncrona, uma resposta que o cliente poderia ter na própria requisição;
- a admissão já era uma unidade atômica no SSOT (linha bloqueada, Operation e outbox na mesma transação); o assíncrono não acrescentava garantia alguma sobre ela.

No Kubernetes, o API server valida, admite e persiste de forma síncrona e responde com o objeto; a convergência é assíncrona e feita pelos controllers (decisão 0096).

## Decisão

1. **O processo `api` substitui Receiver e Manager.** Autentica (JWT), autoriza, valida e grava a admissão **na requisição**, em uma transação do SSOT: linha do recurso bloqueada, regras de negócio, escrita do recurso e inserção do `desired` no outbox. Quem publica continua sendo o Publisher. Nome do processo, do papel de log (`smarkee.component.role = api`), do serviço de rede (`ipm-serviceaccount-api.smarkee.internal`) e das variáveis `IPM_SERVICEACCOUNT_API_*`.
2. **Semântica HTTP.** `POST` → `201` com o `Resource`; `PATCH` → `200` com o `Resource`; `DELETE` → `202` com o `Resource` em `phase=Deleting` (o Controller conclui). Violação de regra de negócio → `400`/`403`/`409`/`422` no corpo `ApiError` (schema `api-error.v1`, inalterado).
3. **Concorrência.** O `resourceVersion` continua no corpo (`PATCH`) ou na consulta (`DELETE`), como hoje; divergência → `409 Conflict`, como o Kubernetes. Sem `If-Match` nem `problem+json`: seriam contrato novo sem consumidor que os peça.
4. **Idempotência.** `Idempotency-Key` identifica `(requested_by, idempotency_key)` na tabela `ipm.serviceaccount_idempotency`, gravada na transação da admissão com o `request_digest`. A chave é registrada só quando a escrita é aplicada (recusas não a consomem). Repetição com o mesmo digest devolve o recurso atual (sem gravar de novo); com digest diferente → `422 IdempotencyKeyReused`. Registros expiram por retenção (job de manutenção existente).
5. **Fim da Operation.** `ipm.serviceaccount_operation`, a view `ipm.serviceaccount_operation_v1`, a rota `/v1/ipm/serviceaccounts/operations/{id}`, o Stream `REQUESTED` do tipo, o consumer `ipm-serviceaccount-manager-requested` e o Manager deixam de existir. O estado de uma alteração é o próprio recurso (`generation`, `observedGeneration`, `phase`, `conditions`), lido por `GET`.
6. **`resourceVersion` e geração no `Resource`.** O `Resource` ganha `observedGeneration` (aditivo): o cliente espera a convergência lendo `observedGeneration >= desiredGeneration` com `phase` `Ready`/`Failed` (ou `404` após o `DELETE`).
7. **Causa da geração.** `requested_by` e `correlation_id` da última alteração do `desired` passam a ser colunas do recurso (`requested_by`, `correlation_id`), gravadas na admissão e lidas pelo Controller para preencher o `updated`. O Controller não depende mais de Operation.
8. **Envelope.** O `emitter` do `desired` passa a `api` (valor novo, aditivo, no enum de `message-envelope.v1`). `receiver` e `manager` permanecem no enum até as demais features migrarem. Os subjects (`manager.desired|updated.ipm.serviceaccount.*`), o Stream `DESIRED` e a ACL do Publisher não mudam.
9. **Banco.** O papel `ipm_serviceaccount_api` substitui `..._manager` e `..._receiver` (leitura/escrita do recurso, outbox e idempotência; sem `DELETE` no recurso, decisão 0096).

## Compatibilidade (§10, §31)

- **API:** quebra por tipo, sem convivência (decisão do responsável): `202`+`operationId` deixa de existir em `ipm/serviceaccount`; o corpo de resposta passa a ser o `Resource`. Consumidores no repositório: CLI `sk` (`--wait` passa a consultar o recurso) e Console, ambos alterados no mesmo commit.
- **`Resource`:** campo `observedGeneration` novo (aditivo); a view `ipm.serviceaccount_v1` ganha a coluna no fim.
- **Mensageria:** `desired` e `updated` mantêm subject, Stream e payload; só o `emitter` do `desired` muda (`receiver` → `api`), e nenhum consumidor confere o `emitter` do `desired` de `serviceaccount`. O `updated` (Stream `UPDATED`) é inalterado.
- **Dados:** a migração `0005` acrescenta as colunas de causa, cria a idempotência e remove a Operation e a view. Operations antigas não têm uso depois da migração.
- **DNS/rota:** `ipm-serviceaccount-receiver` → `ipm-serviceaccount-api`; gateway, telemetria e `config.toml` dos peers são atualizados.

## Consequências

- Um processo a menos por tipo, uma tabela, um Stream e um consumer a menos; erro de negócio responde na requisição.
- A latência da requisição passa a incluir a transação de admissão; sem cliente do provedor externo no caminho (o provedor só é tocado pelo Controller).
- Se o banco estiver indisponível, a escrita falha na hora (`503`), em vez de ficar aceita no Stream. A durabilidade do pedido passa a ser a do SSOT, não a do Stream.
- Lacuna declarada em `docs/platform/IMPLEMENTATION-STATUS.md`: as contas Zitadel `ipm-serviceaccount-{receiver,manager}` deixam de ser usadas; a conta `ipm-serviceaccount-api` substitui a do Receiver.

## Referência

Kubernetes: o API server valida, aplica admissão e persiste o objeto na requisição, com `resourceVersion` para concorrência otimista e `status.conditions` para o estado; a convergência é assíncrona. Diverge ao manter o outbox transacional + Publisher para o NATS (o Kubernetes usa o `watch` do etcd) e ao devolver `202` no `DELETE`, porque a remoção no provedor é concluída pelo Controller (equivale ao *finalizer* do Kubernetes).
