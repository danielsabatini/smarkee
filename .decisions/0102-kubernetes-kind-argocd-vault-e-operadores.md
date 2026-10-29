# 0102. Ambiente Kubernetes (`kind`), GitOps (`ArgoCD` + `Kustomize`), Operadores Oficiais e `vault` (`/svm`, `/ekm`, `/clm`)

**Data:** 2026-10-29  
**Status:** Aprovada  
**Decisões relacionadas:** 0006 (Organization como unidade de isolamento), 0062 (coleta de telemetria em duas camadas), 0067 (configuração por papel com `config.toml` e segredos em `/run/secrets/`), 0087 (banco `ssot`), 0098 (API síncrona e padrões `internal-state` e `external-reconciled`), 0101 (subjects de 4 tokens e streams NATS)

## Contexto

1. O ambiente de desenvolvimento baseado em Docker Compose (`infrastructure/dev/compose.yaml`) acumulava divergências estruturais em relação a `stg` e `prd`:
   - Uso do domínio sintético `*.smarkee.internal` em vez do DNS nativo do Kubernetes (`<service>.<namespace>.svc.cluster.local`), exigindo configurações distintas por ambiente.
   - Lacunas de segurança declaradas em `docs/platform/IMPLEMENTATION-STATUS.md` (§7.1): ausência de cofre de segredos, KMS e PKI em `dev`, e dependência de privilégio `root` com montagem de `/var/run/docker.sock` no `telemetry-agent`.
   - Ausência de reconciliação declarativa GitOps (`ArgoCD`) e de operadores oficiais para banco de dados, streams/consumers de mensageria, coletores de telemetria, certificados e injeção de segredos.
2. A plataforma prevê os serviços de produto **SVM** (*Secret Vault Manager*), **EKM** (*Encryption Key Manager*) e **CLM** (*Certificate Lifecycle Manager*), que também sustentam a própria infraestrutura da plataforma (na organização `core`). Em produção (`prd`), por isolamento de raio de explosão e *auto-unseal* cruzado, cada um desses três papéis roda em seu próprio cluster OpenBao dedicado, enquanto em desenvolvimento (`dev`), para viabilizar a execução local em um único nó `kind`, uma única instância standalone do OpenBao deve atender aos três papéis sem alterar contratos de rede, autenticação ou caminhos (`AGENTS.md` §2.6).
3. Na camada de observabilidade (decisão `0062`), o nome `platform-telemeter` destoava dos demais componentes do namespace `telemetry` (`telemetry-agent` e `telemetry-router`) e carregava o termo `platform` (já extinto no banco de dados pela decisão `0099`).

## Decisão

### 1. Cluster Kubernetes Local (`kind`), Registry Local e GitOps (`ArgoCD` + `Kustomize`)

1. O ambiente `dev` passa a executar em um cluster Kubernetes local provisionado via **`kind`** sobre Docker Desktop (`infrastructure/k8s/kind/cluster.yaml`), acompanhado de um container registry local (`localhost:5001`) conectado à rede do cluster.
2. Toda a infraestrutura e as features são declaradas via **Kustomize** (`base/` compartilhada entre todos os ambientes + `overlays/{dev,stg,prd}`) e reconciliadas continuamente pelo **ArgoCD**, utilizando *Sync Waves* e *PreSync Hooks* para ordenação de dependências e migrações.

### 2. Topologia de Namespaces Kubernetes e DNS Nativo

1. Substitui-se o domínio `*.smarkee.internal` pelo DNS padrão do Kubernetes (`<service>.<namespace>.svc.cluster.local`), tornando os endereços em `config.toml` e no gateway idênticos entre `dev`, `stg` e `prd`:
   - **Namespaces de infraestrutura (1 por papel):** `database`, `messaging`, `identity`, `gateway`, `mail`, `telemetry` e `vault`.
   - **Namespaces de módulos de produto (1 por módulo):** `core`, `ipm`, `sum`, `bsm` (e futuros `svm`, `ekm`, `clm`).
   - **Namespaces de operadores do cluster (padronização uniformizada `<papel>-operator`, `AGENTS.md` §15.1):** `gitops-operator`, `database-operator`, `telemetry-operator`, `cert-manager-operator`, `external-secrets-operator` e `messaging-operator`.

### 3. Adoção de Operadores Oficiais do Ecossistema Kubernetes (`AGENTS.md` §2.7)

Sempre que existir operador oficial estável e mantido pelo fabricante/CNCF, ele é adotado no lugar de scripts imperativos:
1. **`database` — CloudNativePG (`cnpg`, `postgresql.cnpg.io/v1`):** gerencia o cluster PostgreSQL 18 (`ssot`), com `instances: 1` em `overlays/dev` e `instances: 3` com alta disponibilidade e backup PITR em `overlays/stg` e `overlays/prd`, TLS emitido via `cert-manager` e `managed.roles` integrado aos `Secret`s sincronizados do cofre.
2. **`messaging` — NACK (`jetstream.nats.io/v1beta2`):** o broker NATS JetStream (`2.15.2-alpine`) roda como `StatefulSet` com `nats-server-config-reloader`, healthcheck nativo em `127.0.0.1:8222/healthz?js-enabled-only=true` e sidecar `prometheus-nats-exporter` lendo `127.0.0.1:8222` e expondo `:7777/metrics` no próprio `Service` `messaging.messaging.svc.cluster.local`. Os Streams (`DESIRED`, `UPDATED`, `AUDIT`) e Consumers das features são reconciliados declarativamente via CRDs `kind: Stream` e `kind: Consumer` pelo NACK.
3. **`telemetry` e features — OpenTelemetry Operator (`opentelemetry.io/v1beta1`):** reconcilia os CRDs `kind: OpenTelemetryCollector` da plataforma e das features.
4. **`cert-manager` + `trust-manager`:** emitem e renovam certificados TLS internos da plataforma assinados pela PKI da organização `core` (`clm.vault.svc.cluster.local`) e distribuem o bundle de CA confiável nos namespaces.
5. **`External Secrets Operator` (`ESO`, `external-secrets.io/v1`):** lê os segredos de cada componente no cofre da organização `core` (`svm.vault.svc.cluster.local`) e materializa os `Secret`s montados em `/run/secrets/<VAR>`, mantendo inalterado o contrato da decisão `0067`.
6. **Exceção documentada (`identity`):** o Zitadel v4 (`v4.20.0`) não possui operador Kubernetes oficial; segue o padrão oficial do `zitadel-charts` v10 (`Deployment` `identity` + `Deployment` `identity-login` + `PreSync Job` `setup` sobre banco PostgreSQL gerenciado pelo CloudNativePG).

### 4. Arquitetura do `vault` (`/svm`, `/ekm`, `/clm`) e Relacionamento 1:1 com o `identity`

1. **Três `Service`s DNS desde o `dev` no namespace K8s `vault` (`AGENTS.md` §2.6):**
   - `svm.vault.svc.cluster.local:8200` (*Secret Vault Manager* — mount `/svm`, engine `kv-v2`)
   - `ekm.vault.svc.cluster.local:8200` (*Encryption Key Manager* — mount `/ekm`, engine `transit`)
   - `clm.vault.svc.cluster.local:8200` (*Certificate Lifecycle Manager* — mount `/clm`, engine `pki`)
   - No `overlays/dev`, os três `Service`s selecionam o mesmo `StatefulSet` `vault` (`openbao/openbao:2.7.2`, 1 instância com armazenamento `raft`). Nos `overlays/stg` e `overlays/prd`, cada `Service` seleciona seu próprio cluster OpenBao dedicado e isolado (`svm`, `ekm`, `clm`).
2. **Mapeamento 1:1 entre Namespaces do `vault` e Organizações do `identity` (estendendo a decisão `0006`):**
   - Cada organização no `identity` possui um namespace correspondente em `/v1/sys/namespaces/<namespace>` nos serviços `svm`, `ekm` e `clm`:
     - `core/` para a organização `core` (onde residem os segredos, chaves e CAs dos serviços de infraestrutura e componentes da plataforma).
     - `operator/` para a organização `operator`.
     - `<organizationId>/` para cada organização de cliente criada por `ipm/organization`.
   - Todo namespace do `vault` registra em seu `custom_metadata` os identificadores da organização correspondente no `identity`, utilizando estritamente a nomenclatura de papel (`AGENTS.md` §15.1):
     - `identity_org_id`: ID da organização no `identity`.
     - `identity_org_name`: nome da organização no `identity`.
3. **Autenticação vinculada ao `identity` e ao Kubernetes:**
   - Os namespaces do `vault` configuram autenticação OIDC/JWT (`auth/jwt` e `auth/oidc`) apontando para o provedor `identity` (`http://identity.identity.svc.cluster.local:8080`), restringindo o acesso via *bound claims* ao `identity_org_id` daquele namespace.
   - No namespace `core/`, a autenticação `auth/kubernetes` permite que o `cert-manager` (política `clm-issuer`) e o `External Secrets Operator` (política `svm-reader`) atuem com menor privilégio estrito.

### 5. Observabilidade no Kubernetes e Renomeação para `telemetry-sink`

1. O coletor de gravação de infraestrutura e fallback da plataforma (antes `platform-telemeter`) passa a se chamar **`telemetry-sink`**, formando no namespace `telemetry` a tríade:
   - **`telemetry-agent`** (`mode: daemonset`): lê `/var/log/pods` (`readOnly: true`) diretamente no formato CRI (`containerd`) e coleta métricas via `kubeletstats` (API do Kubelet com RBAC `nodes/stats` somente leitura), `postgresql`, `sql_query/outbox` e `prometheus/infra`, eliminando definitivamente o uso de `root` e `/var/run/docker.sock`.
   - **`telemetry-router`** (`mode: statefulset`): roteia logs e spans para os telemeters das features ou para o `telemetry-sink`, mantendo `sending_queue` persistente em disco (`file_storage`) sem colisão de lock entre rollouts.
   - **`telemetry-sink`** (`mode: statefulset`, DNS `telemetry-sink.telemetry.svc.cluster.local:4317`): grava os sinais de infraestrutura e o fallback de aplicação/traces.
2. Nos namespaces dos módulos (`core`, `ipm`, `sum`, `bsm`), cada feature mantém seu **`<módulo>-<tipo>-telemeter`** (`mode: statefulset`, DNS `<módulo>-<tipo>-telemeter.<módulo>.svc.cluster.local:4317`), protegido por `NetworkPolicy` que aceita tráfego na porta `4317` exclusivamente do `telemetry-router`.

## Consequências

- **Positivas:**
  - Eliminação das diferenças arquiteturais e de DNS entre `dev`, `stg` e `prd`: o mesmo manifesto `base/` e o mesmo `config.toml` servem a todos os ambientes.
  - Fechamento das lacunas declaradas de desenvolvimento em `docs/platform/IMPLEMENTATION-STATUS.md` (§7.1): fim do socket do Docker no `telemetry-agent`, adoção do formato CRI (`containerd`), PKI interna (`clm`), cofre de segredos (`svm`) e KMS (`ekm`) desde o `dev`.
  - Preparação direta da fundação para as futuras features de produto `svm`, `ekm` e `clm` por organização.
- **Negativas / Atenção:**
  - O provisionamento local requer `kind`, `kubectl` e os operadores em execução no Docker Desktop, automatizados por `scripts/dev/cluster-up`.
