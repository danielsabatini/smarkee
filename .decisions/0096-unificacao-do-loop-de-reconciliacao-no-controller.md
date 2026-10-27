# 0096 — Unificação do loop de reconciliação externa no processo Controller

- **Data:** 2026-10-26
- **Status:** Aceita. Reavalia e substitui a separação física dos papéis Observer, Reconciler e Executor (decisões 0063, 0065, 0072 e 0073) para recursos com provedor externo, conforme AGENTS.md §2.1 (#2 Simplicidade), §2.7 (Referência de Mercado — Kubernetes Controllers) e §25.1.

## Contexto

As decisões 0063, 0065, 0072 e 0073 definiram que o Resource Control Loop operaria distribuído em 6 processos físicos por tipo de recurso (`receiver`, `manager`, `publisher`, `observer`, `reconciler`, `executor`), comunicando-se através de 5 Streams NATS (`REQUESTED`, `DESIRED`, `OBSERVED`, `ACTION`, `RESULT`) e gravando a persistência de idempotência em `<tipo>_action_result`.

Essa separação gerou complexidade operacional massiva:
1. **Sobrecarga de processos e tráfego:** 18 processos e 15 Streams NATS rodando apenas para o módulo `ipm/*`, com múltiplas mensagens assíncronas trafegando para um único ciclo de vida.
2. **Corridas e atrasos de convergência:** o estado intermediário em cache (`reconciler`) desacoplado da observação física (`observer`) e da execução (`executor`) introduzia janelas de inconsistência e corridas assíncronas.
3. **Fragilidade operacional:** reiniciar qualquer um dos papéis deixava mensagens órfãs ou causava timeouts.

## Decisão

1. **Unificação no papel `controller`:**
   - Para recursos que gerenciam estado em provedor externo (Zitadel: `ipm/organization`, `ipm/user`, `ipm/serviceaccount`), os papéis `observer`, `reconciler` e `executor` são unificados em um único processo: o **`controller`**.
   - A função pura de decisão `decide(desired, observed)` é preservada integralmente e sem efeitos colaterais.
   - O `controller` adota o padrão de referência da indústria (Kubernetes Controller / Informer + Workqueue):
     - **Informer:** consome o stream `DESIRED` do NATS com particionamento determinístico e barreira `wait_synced` (`WaitForCacheSync`).
     - **Workqueue com deduplicação e backoff:** fila assíncrona por `resourceId` que colapsa múltiplos eventos concorrentes e aplica backoff exponencial com jitter em erros transitórios do provedor.
     - **Ciclo atômico `reconcile(resourceId)`:** lê o recurso no SSOT sob lock consultivo/linha (`FOR UPDATE`), observa o estado externo no provedor, decide via `decide()`, executa a ação idempotente no provedor se houver divergência, reobserva imediatamente e grava o estado convergido (`status`, `observed`, `conditions`, `phase`) no SSOT.
2. **Eliminação dos Streams intermediários e tabelas transitórias:**
   - Os Streams NATS `OBSERVED`, `ACTION` e `RESULT` são extintos para esses tipos.
   - A tabela `<tipo>_action_result` no SSOT é removida, pois a idempotência da ação é garantida no ciclo atômico local do controller e pelas operações idempotentes nos drivers do provedor.
   - O Manager deixa de assinar `OBSERVED` e `RESULT` no NATS, focando exclusivamente no processamento de `REQUESTED` e admissão no SSOT.

## Justificativa

- **Simplicidade (§2.1 #2, §6):** reduz 4 processos para 1 por feature externa e elimina 3 Streams NATS por tipo, simplificando drasticamente a topologia, a observabilidade e o consumo de recursos.
- **Robustez e Resiliência (§2.1 #3 e #4, §11, §12):** o ciclo atômico local de reconciliação elimina corridas de rede entre observação, decisão e execução, garantindo que o estado gravado no SSOT reflita a realidade externa confirmada.
- **Referência de Mercado (§2.7):** segue fielmente o padrão universal de controladores Kubernetes (`controller-runtime` / `sample-controller`), que executam observação, decisão e reconciliação no mesmo loop de reconciliação de worker.

## Consequências

- Em `infrastructure/dev/compose.yaml`, os contêineres `<tipo>-observer`, `<tipo>-reconciler` e `<tipo>-executor` são substituídos por `<tipo>-controller`.
- Permissões NATS e scripts de dev são simplificados.
- As decisões anteriores sobre separação de observer/reconciler/executor ficam revogadas para os tipos migrados.
