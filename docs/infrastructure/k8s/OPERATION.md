# Manual Operacional do Cluster Kubernetes da Smarkee (`kind`, `ArgoCD`, `vault` e Operadores)

> **Escopo:** guia de operação diária (*runbook/playbook*) para engenheiros e desenvolvedores no cluster Kubernetes local (`kind`). Cobre o ciclo de vida do cluster, fluxos de desenvolvimento iterativo (código Python e manifestos Kustomize), acesso a UIs e serviços no host, catálogo de utilitários em `scripts/dev/`, checklists de saúde operacional e procedimentos de diagnóstico e resolução de problemas (*troubleshooting*).
>
> **Documento de referência arquitetural:** [`docs/infrastructure/k8s/INFRASTRUCTURE.md`](INFRASTRUCTURE.md).
>
> **Decisão técnica:** [`.decisions/0102-kubernetes-kind-argocd-vault-e-operadores.md`](../../../.decisions/0102-kubernetes-kind-argocd-vault-e-operadores.md).

---

## Sumário

1. [Visão Geral e Filosofia Operacional](#1-visão-geral-e-filosofia-operacional)
2. [Ciclo de Vida do Cluster Local](#2-ciclo-de-vida-do-cluster-local)
   - 2.1 [Inicialização Idempotente (`cluster-up`)](#21-inicialização-idempotente-cluster-up)
   - 2.2 [Pausar e Retomar o Cluster](#22-pausar-e-retomar-o-cluster)
   - 2.3 [Destruição e Reinício Limpo (*Clean Slate*)](#23-destruição-e-reinício-limpo-clean-slate)
3. [Fluxos de Desenvolvimento Diário (*Dev Loops*)](#3-fluxos-de-desenvolvimento-diário-dev-loops)
   - 3.1 [Desenvolvimento de Código de Features (`k8s-dev`)](#31-desenvolvimento-de-código-de-features-k8s-dev)
   - 3.2 [Desenvolvimento de Manifestos Kustomize e Sincronização GitOps](#32-desenvolvimento-de-manifestos-kustomize-e-sincronização-gitops)
   - 3.3 [Inspeção e Acompanhamento de Logs em Tempo Real](#33-inspeção-e-acompanhamento-de-logs-em-tempo-real)
4. [Acesso a Serviços, UIs e Ferramentas](#4-acesso-a-serviços-uis-e-ferramentas)
   - 4.1 [Portas Expostas Diretamente no Host (`127.0.0.1`)](#41-portas-expostas-diretamente-no-host-127001)
   - 4.2 [Túneis Temporários via `kubectl port-forward`](#42-túneis-temporários-via-kubectl-port-forward)
   - 4.3 [Credenciais e Autenticação em Desenvolvimento](#43-credenciais-e-autenticação-em-desenvolvimento)
5. [Catálogo de Utilitários Oficiais (`scripts/dev/`)](#5-catálogo-de-utilitários-oficiais-scriptsdev)
6. [Checklists de Saúde e Inspeção Operacional](#6-checklists-de-saúde-e-inspeção-operacional)
   - 6.1 [Checklist Rápido de 1 Minuto](#61-checklist-rápido-de-1-minuto)
   - 6.2 [Inspeção Específica por Camada](#62-inspeção-específica-por-camada)
7. [Guia de Diagnóstico e Resolução de Problemas (*Troubleshooting*)](#7-guia-de-diagnóstico-e-resolução-de-problemas-troubleshooting)
   - 7.1 [Pod em `CrashLoopBackOff` ou `ImagePullBackOff`](#71-pod-em-crashloopbackoff-ou-imagepullbackoff)
   - 7.2 [Vault Selado (`Sealed: true`)](#72-vault-selado-sealed-true)
   - 7.3 [ArgoCD: Aplicação `OutOfSync` ou `Degraded`](#73-argocd-aplicação-outofsync-ou-degraded)
   - 7.4 [NATS JetStream: Consumidor Travado ou Mensagens em Atraso](#74-nats-jetstream-consumidor-travado-ou-mensagens-em-atraso)
   - 7.5 [`ExternalSecret` em Falha (`SecretStoreNotReady`)](#75-externalsecret-em-falha-secretstorenotready)
   - 7.6 [Certificado TLS do `cert-manager` não Emitido](#76-certificado-tls-do-cert-manager-não-emitido)
   - 7.7 [Telemetria não Gravando nos Arquivos `.jsonl` do Host](#77-telemetria-não-gravando-nos-arquivos-jsonl-do-host)

---

## 1. Visão Geral e Filosofia Operacional

A infraestrutura Kubernetes de desenvolvimento da Smarkee foi desenhada para atingir **paridade absoluta com homologação (`stg`) e produção (`prd`)** sem sacrificar a velocidade do desenvolvedor no ciclo diário:

1. **Mesmos Contratos de Produção:** Operadores nativos de Kubernetes (`CloudNativePG`, `cert-manager`, `trust-manager`, `External Secrets Operator`, `OpenTelemetry Operator`, `NACK` e `ArgoCD`) controlam toda a infraestrutura. Não há emuladores improvisados nem scripts pontuais de inicialização no cluster.
2. **Ciclo GitOps Transparente em Dev:** O cluster consome os mesmos manifestos Kustomize que vão a produção. Em `dev`, um servidor Git interno (`git-server` no namespace `gitops-operator`) reflete as alterações do diretório local automaticamente, sem exigir que o desenvolvedor crie commits ou envie branches para repositórios remotos para testar alterações de infraestrutura.
3. **Ciclo Rápido de Aplicação (*Fast Dev Loop*):** Alterações no código Python de qualquer feature são compiladas, enviadas ao registry OCI local (`localhost:5001`), pré-carregadas no containerd do cluster e reiniciadas em segundos via `./scripts/dev/k8s-dev`.

---

## 2. Ciclo de Vida do Cluster Local

### 2.1 Inicialização Idempotente (`cluster-up`)

O script `./scripts/dev/cluster-up` é o ponto de entrada único para provisionar o ambiente local completo. Ele é **estritamente idempotente**: se o cluster já existir, ele verifica a presença dos componentes e prossegue sem sobrescrever o estado desnecessariamente.

```bash
./scripts/dev/cluster-up
```

#### O que o comando executa sequencialmente:
1. **Diretórios de Telemetria no Host:** Garante a existência dos diretórios locais de logs, métricas e traces em `infrastructure/dev/telemetry-sink/` e `features/*/*/telemeter/` antes da criação do cluster (necessário para os `extraMounts` do Docker).
2. **Limpeza de Portas Locais:** Interrompe contêineres legados do Docker Compose que possam estar ocupando portas essenciais (`5432`, `4222`, `8080`, `8025`, `9180`).
3. **Container Registry Local (`localhost:5001`):** Inicia o contêiner `smarkee-registry` (`registry:3.1.2`) na rede `bridge` do Docker, permitindo push/pull sem autenticação.
4. **Criação do Cluster Kind (`smarkee`):** Instancia o nó de controle (`kindest/node:v1.37.0`) configurado com os mapeamentos de portas em `127.0.0.1` e os bind mounts de repositório e telemetria.
5. **Conexão de Rede:** Conecta o contêiner do registry à mesma rede de ponte Docker do cluster kind (`kind`), garantindo resolução mútua de DNS.
6. **Configuração de Registro no Containerd:** Cria o arquivo de hosts do containerd no nó do cluster (`/etc/containerd/certs.d/localhost:5001/hosts.toml`) apontando para o IP interno do `smarkee-registry`.
7. **Namespaces da Plataforma:** Aplica os 17 namespaces canônicos definidos em `infrastructure/k8s/operators/namespaces/namespaces.yaml`.
8. **Instalação dos 7 Operadores Oficiais:** Instala e aguarda prontidão das CRDs e Pods de:
   - `cert-manager` e `trust-manager` (`cert-manager-operator`)
   - `cloudnative-pg` (`database-operator`)
   - `external-secrets` (`external-secrets-operator`)
   - `opentelemetry-operator` (`telemetry-operator`)
   - `nack-jetstream-controller` (`messaging-operator`)
   - `argocd` e `git-server` (`gitops-operator`)
9. **Inicialização do Cofre (`vault-bootstrap`):** Executa o bootstrap do OpenBao (`vault-0`), realiza o *unseal*, configura os namespaces `core/` e `operator/`, habilita os mounts `/svm`, `/ekm`, `/clm`, configura a PKI e popula os segredos de desenvolvimento.
10. **Aplicações Raiz do GitOps:** Aplica `smarkee-root` no ArgoCD, que por sua vez orquestra o provisionamento sincronizado em ondas (*sync waves*) de toda a plataforma e das 9 features de produto.

### 2.2 Pausar e Retomar o Cluster

Para economizar recursos de CPU e memória da máquina de desenvolvimento sem perder o estado persistido do PostgreSQL, Vault ou NATS JetStream:

#### Para suspender a execução:
```bash
docker stop smarkee-control-plane smarkee-registry
```

#### Para retomar a execução:
```bash
docker start smarkee-registry smarkee-control-plane
```

> **Atenção — Unseal do Vault após reiniciar:**
> Quando o contêiner do nó kind é reiniciado, o pod `vault-0` volta ao estado inicial selado (`Sealed: true`). Para deslacrá-lo rapidamente usando o arquivo salvo em `.workspace/vault-init.json`:
> ```bash
> ./scripts/dev/vault-bootstrap
> ```
> O script detecta que o cofre já foi inicializado, reaplica as chaves de unseal instantaneamente e valida os segredos.

### 2.3 Destruição e Reinício Limpo (*Clean Slate*)

Caso seja necessário recriar o ambiente integralmente do zero:

```bash
# 1. Destruir o cluster kind e o container registry
kind delete cluster --name smarkee
docker rm -f smarkee-registry 2>/dev/null || true

# 2. Limpar os artefatos temporários de bootstrap
rm -f .workspace/kind-cluster.yaml .workspace/vault-init.json

# 3. Provisionar um novo cluster zerado
./scripts/dev/cluster-up
```

---

## 3. Fluxos de Desenvolvimento Diário (*Dev Loops*)

### 3.1 Desenvolvimento de Código de Features (`k8s-dev`)

Ao implementar ou alterar lógica de negócio nos serviços Python de qualquer feature (`features/<módulo>/<tipo>/...`), o desenvolvedor conta com o utilitário `./scripts/dev/k8s-dev` para publicar e testar no cluster em segundos.

```bash
# Sintaxe:
./scripts/dev/k8s-dev <módulo>/<tipo> [papel]
```

#### Exemplos Práticos:

```bash
# 1. Reconstruir e atualizar todos os papéis (api, publisher, controller) de uma feature:
./scripts/dev/k8s-dev core/account

# 2. Reconstruir e reiniciar apenas o papel 'api' de ipm/organization:
./scripts/dev/k8s-dev ipm/organization api

# 3. Reconstruir e reiniciar apenas o controller de sum/service:
./scripts/dev/k8s-dev sum/service controller
```

#### O que o comando faz nos bastidores:
1. Executa `./scripts/dev/build-push <módulo>/<tipo>`, gerando a imagem OCI com a tag local `localhost:5001/smarkee-<módulo>-<tipo>:dev`.
2. Publica a imagem no registry local em `localhost:5001`.
3. Executa `crictl pull` dentro do nó `smarkee-control-plane`, garantindo que o `containerd` do Kubernetes atualize imediatamente sua camada local com os novos bytes da imagem.
4. Executa `kubectl -n <módulo> rollout restart deployment/...` para os deployments alvo.
5. Executa `kubectl -n <módulo> rollout status deployment/... --timeout=90s`, aguardando a subida limpa dos novos pods antes de liberar o terminal.

### 3.2 Desenvolvimento de Manifestos Kustomize e Sincronização GitOps

Ao alterar manifestos declarativos de infraestrutura em `infrastructure/k8s/` ou manifestos de features em `features/<módulo>/<tipo>/k8s/`:

#### Como funciona a sincronização no cluster local:
1. A raiz do repositório da sua máquina está montada em tempo real dentro do nó kind em `/workspace/smarkee` (via `extraMounts` em `infrastructure/k8s/kind/cluster.yaml`).
2. O Deployment `git-server` (namespace `gitops-operator`) roda um daemon Git interno servindo na porta `9418` (`git://git-server.gitops-operator.svc.cluster.local:9418/smarkee.git`).
3. A cada **10 segundos**, um loop de sincronização no `git-server` copia os diretórios `infrastructure/k8s/` e `features/*/*/k8s/` do bind mount para um repositório Git interno e comita automaticamente na branch `dev`.
4. **Vantagem direta:** Não é necessário fazer `git commit` ou `git push` no seu repositório de trabalho para que o ArgoCD veja as alterações nos manifestos. Basta salvar os arquivos no disco.

#### Forçar Sincronização Imediata no ArgoCD (*Hard Refresh & Sync*):
Por padrão, o ArgoCD faz polling de alterações a cada 3 minutos. Para forçar a reconciliação imediata da aplicação que você acabou de alterar:

```bash
# Forçar detecção imediata de mudanças pelo ArgoCD:
kubectl -n gitops-operator annotate application <nome-da-app> argocd.argoproj.io/refresh=hard --overwrite

# Exemplo para a feature ipm-organization:
kubectl -n gitops-operator annotate application ipm-organization argocd.argoproj.io/refresh=hard --overwrite

# Exemplo para a infraestrutura de mensageria:
kubectl -n gitops-operator annotate application smarkee-messaging argocd.argoproj.io/refresh=hard --overwrite
```

#### Disparar Sincronização Declarativa Imediata:
```bash
kubectl -n gitops-operator patch application <nome-da-app> --type merge -p '{"operation":{"sync":{"prune":true}}}'
```

#### Validar Manifestos Kustomize Localmente antes de sincronizar:
Para inspecionar o YAML final gerado pelo Kustomize antes de deixar o ArgoCD aplicar:
```bash
kubectl kustomize features/ipm/organization/k8s/overlays/dev
kubectl kustomize infrastructure/k8s/platform/gateway/overlays/dev
```

### 3.3 Inspeção e Acompanhamento de Logs em Tempo Real

Para acompanhar o comportamento dos serviços:

```bash
# Logs do controller de uma feature específica (streaming):
kubectl -n ipm logs -f deployment/ipm-organization-controller

# Logs de todos os pods de uma feature simultaneamente:
kubectl -n ipm logs -l app.kubernetes.io/part-of=ipm-organization -f --max-log-requests=10

# Logs do gateway de API (APISIX):
kubectl -n gateway logs -f deployment/gateway

# Logs do conector de sincronização do gateway (ADC):
kubectl -n gateway logs -f deployment/gateway-sync

# Logs do operador do banco de dados (CloudNativePG):
kubectl -n database-operator logs -f deployment/cnpg-controller-manager

# Logs do operador de mensageria (NACK):
kubectl -n messaging-operator logs -f deployment/nack-jetstream-controller
```

---

## 4. Acesso a Serviços, UIs e Ferramentas

### 4.1 Portas Expostas Diretamente no Host (`127.0.0.1`)

O nó do cluster kind possui mapeamento direto de portas em `127.0.0.1` (`extraPortMappings`). Os serviços abaixo podem ser acessados diretamente pelo navegador, cliente HTTP ou ferramentas locais sem necessidade de configurar `kubectl port-forward`:

| Serviço | URL no Host / Porta | Namespace | Serviço K8s / NodePort | Finalidade | Credenciais em Dev |
|---|---|---|---|---|---|
| **Gateway de API** | `http://127.0.0.1:8080` | `gateway` | `gateway` (`30080`) | Ponto de entrada de APIs HTTP da plataforma | Bearer Token JWT (Zitadel) |
| **Gateway Admin & UI** | `http://127.0.0.1:9180` (UI em `/ui/`) | `gateway` | `gateway-admin` (`30180`) | Admin API e Interface Web embutida do Apache APISIX Dashboard | Chave em `gateway-secret` (`APISIX_ADMIN_KEY`) |
| **PostgreSQL SSOT** | `127.0.0.1:5432` | `database` | `database-external` (`30432`) | Banco de dados relacional principal | Usuário: `postgres` / Sem senha ou senha em `database-app` |
| **NATS Core** | `nats://127.0.0.1:4222` | `messaging` | `messaging-external` (`30422`) | Mensageria e JetStream CLI / SDKs | Usuário: `smarkee` / Senha no Vault (`/svm/core/messaging`) |
| **NATS Monitoring** | `http://127.0.0.1:8222` | `messaging` | `messaging-monitoring` (`30822`) | Métricas HTTP e inspeção interna do servidor NATS | Sem autenticação |
| **OpenBao / Vault** | `http://127.0.0.1:8200` | `vault` | `vault-nodeport` (`30200`) | API e UI do cofre de segredos (`/svm`, `/ekm`, `/clm`) | **OIDC Federado:** Login via Zitadel (`admin` / `Smarkee@Dev2026!`). Root Token apenas em `.workspace/vault-init.json` (break-glass) |
| **Mailpit Web UI** | `http://127.0.0.1:8025` | `mail` | `mail-external` (`30025`) | Caixa de entrada de e-mails capturados em `dev` | Sem autenticação |
| **ArgoCD Server** | `https://127.0.0.1:8443` | `gitops-operator` | `argocd-server` (`30443`) | Interface Web e API do ArgoCD GitOps | Usuário: `admin` / Senha em `argocd-initial-admin-secret` |
| **OCI Registry** | `http://localhost:5001` | *(Docker Host)* | Contêiner `smarkee-registry` | Container registry OCI local para imagens de dev | Sem autenticação |

### 4.2 Túneis Temporários via `kubectl port-forward`

Para serviços que não expõem NodePort nativa ou quando for desejado isolar o canal de comunicação:

```bash
# 1. Provedor de Identidade (Zitadel API direta):
kubectl -n identity port-forward svc/identity 8085:8080
# Acesso: http://127.0.0.1:8085

# 2. Zitadel Login UI direta:
kubectl -n identity port-forward svc/identity-login 8086:8080
# Acesso: http://127.0.0.1:8086

# 3. Servidor de E-mail SMTP direto (envio de testes):
kubectl -n mail port-forward svc/mail 1025:1025

# 4. etcd do Gateway de API:
kubectl -n gateway port-forward svc/gateway-etcd 2379:2379

# 5. OpenTelemetry Sink (recebimento de telemetria OTLP no host):
kubectl -n telemetry port-forward svc/telemetry-sink 4317:4317
```

### 4.3 Credenciais e Autenticação em Desenvolvimento

#### 1. Autenticação no OpenBao (Vault) via Zitadel OIDC (Decisões 0103 e 0104):
Conforme as decisões `0103` e `0104`, o uso operacional de `root_token` foi eliminado. Operadores humanos autenticam via OIDC federado com o Zitadel:

- **Interface Web:** Acesse `http://127.0.0.1:8200/ui/`, selecione o método `OIDC` e autentique com o usuário operador (`admin` / `Smarkee@Dev2026!`). O role padrão assumido é `vault.platformAdmin`.
- **CLI Local `bao` / `vault`:**
  ```bash
  export BAO_ADDR="http://127.0.0.1:8200"
  bao login -method=oidc role=vault.platformAdmin
  ```
  (ou `role=vault.platformViewer` para auditoria e inspeção restrita à leitura).
  O navegador abrirá na tela de login do Zitadel e retornará com token nominal associado às políticas atômicas CRUD correspondentes (`vault.platform.*`, `svm.secret.*`, `ekm.key.*` e `clm.certificate.*`).

- **Recuperação de Desastre (Break-glass / Bootstrap):**
  Apenas quando o Zitadel ou a federação OIDC estiver indisponível, utilize o token raiz temporariamente:
  ```bash
  export BAO_ADDR="http://127.0.0.1:8200"
  export BAO_TOKEN="$(jq -r .root_token .workspace/vault-init.json)"
  bao token lookup
  ```

#### 2. Senha Inicial de Administrador do ArgoCD:
Para obter a senha do usuário `admin` do ArgoCD:
```bash
kubectl -n gitops-operator get secret argocd-initial-admin-secret \
  -o jsonpath="{.data.password}" | base64 -d && echo
```
Acesse `https://127.0.0.1:8443`, ignore o aviso de certificado autoassinado (em `dev`), e entre com `admin` e a senha obtida.

#### 3. Conexão com o Banco de Dados SSOT (`psql`):
O banco `ssot` está exposto na porta `5432` do host:
```bash
# Conectar como superusuário postgres:
psql -h 127.0.0.1 -p 5432 -U postgres -d ssot

# Conectar com o papel de uma feature (ex: ipm_organization_api_login):
PASS=$(kubectl -n ipm get secret ipm-organization-api-db -o jsonpath='{.data.password}' | base64 -d)
PGPASSWORD="${PASS}" psql -h 127.0.0.1 -p 5432 -U ipm_organization_api_login -d ssot
```

#### 4. Interface Web e Admin API do Apache APISIX:
Acesse no navegador: **`http://127.0.0.1:9180/ui/`**

Para autenticar na interface gráfica ou na Admin API via terminal, obtenha a chave ativa gerada no Vault:
```bash
APISIX_KEY=$(kubectl -n gateway get secret gateway-secret -o jsonpath='{.data.APISIX_ADMIN_KEY}' | base64 -d)
echo "Chave do APISIX: ${APISIX_KEY}"
```
- **No navegador:** cole a chave no campo de autenticação/API Key solicitado pelo dashboard.
- **No terminal:** utilize o header `-H "X-API-KEY: ${APISIX_KEY}"` contra `http://127.0.0.1:9180/apisix/admin/routes`.

---

## 5. Catálogo de Utilitários Oficiais (`scripts/dev/`)

A tabela abaixo resume todos os utilitários disponíveis no diretório `scripts/dev/`:

| Utilitário | Invocação | Finalidade e Descrição |
|---|---|---|
| **`cluster-up`** | `./scripts/dev/cluster-up` | Provisiona de forma idempotente o cluster `kind`, container registry, 17 namespaces, 7 operadores, bootstrap do Vault e as aplicações raiz no ArgoCD. |
| **`vault-bootstrap`** | `./scripts/dev/vault-bootstrap` | Inicializa e faz unseal do OpenBao, configura namespaces `core/` e `operator/`, monta `/svm`, `/ekm`, `/clm`, provisiona PKI e popula credenciais em dev. |
| **`build-push`** | `./scripts/dev/build-push [feature...]` | Constrói as imagens OCI da plataforma e das features, publica no registry local (`localhost:5001`) e atualiza o containerd do nó kind via `crictl pull`. |
| **`k8s-dev`** | `./scripts/dev/k8s-dev <módulo>/<tipo> [papel]` | Ciclo rápido de desenvolvimento: executa `build-push` e faz `rollout restart` e `rollout status` nos Deployments alvo no cluster. |
| **`check`** | `./scripts/dev/check` | Executa a suíte de verificação completa nos 15 componentes do projeto (limites arquiteturais, integridade do template via `sync.py --check`, linter `ruff`, type checker `pyright` e testes unitários e de integração). |
| **`cleanup`** | `(cd scripts/dev/cleanup && uv run smarkee-dev-cleanup [--apply] [--orphans])` | Varre e expurga resíduos de testes E2E no provedor Zitadel, no banco `ssot`, nos streams do NATS JetStream e no Mailpit. Por padrão roda em simulação (*dry-run*); utilize `--apply` para efetivar. |
| **`retention`** | `(cd scripts/dev/retention && uv run smarkee-dev-retention [--apply] [--older-than 24h])` | Aplica a política de retenção no banco SSOT, expurgando registros antigos e já entregues em `<tipo>_outbox` e chaves vencidas em `<tipo>_idempotency` via papéis `*_maintenance_login`. |
| **`republish`** | `(cd scripts/dev/republish && uv run smarkee-dev-republish [--apply])` | Reconstrói e republica mensagens `desired` a partir do estado vigente persistido no banco SSOT (utilizado após restaurações de backup ou recuperações de desastre). |
| **`telemetry-reset`** | `(cd scripts/dev/telemetry-reset && uv run smarkee-dev-telemetry-reset [--apply])` | Pausa temporariamente os coletores no Kubernetes, remove os arquivos locais `.jsonl` de telemetria e os cursores `file_storage`, e reinicia a cadeia de observabilidade limpa. |

---

## 6. Checklists de Saúde e Inspeção Operacional

### 6.1 Checklist Rápido de 1 Minuto

Execute o bloco abaixo para uma auditoria completa de saúde do cluster:

```bash
echo "=== 1. ArgoCD Applications ==="
kubectl -n gitops-operator get applications -o custom-columns=NAME:.metadata.name,SYNC:.status.sync.status,HEALTH:.status.health.status

echo "=== 2. Pods fora de Running/Completed ==="
kubectl get pods -A | grep -vE 'Running|Completed|STATUS' || echo "Todos os Pods saudáveis!"

echo "=== 3. Status do Vault (OpenBao) ==="
kubectl -n vault exec vault-0 -- bao status | grep -E 'Initialized|Sealed|Storage Type'

echo "=== 4. Cluster PostgreSQL (CloudNativePG) ==="
kubectl -n database-operator get clusters.postgresql.cnpg.io -n database

echo "=== 5. Streams do NATS JetStream ==="
kubectl -n messaging get streams.jetstream.nats.io
```

*Critério de sucesso:* Todas as 18 aplicações do ArgoCD devem estar `Synced` e `Healthy`; nenhum Pod em `CrashLoopBackOff` ou `Error`; Vault com `Initialized: true` e `Sealed: false`; Cluster PostgreSQL com status `Cluster in healthy state`; Streams `DESIRED`, `UPDATED` e `AUDIT` presentes e saudáveis.

### 6.2 Inspeção Específica por Camada

#### Camada de Banco de Dados (CloudNativePG):
```bash
# Inspecionar detalhes da instância PostgreSQL:
kubectl -n database describe cluster database

# Inspecionar schemas existentes no banco ssot:
kubectl -n database exec -it database-1 -- psql -U postgres -d ssot -c '\dn'

# Inspecionar tabelas de recursos e outbox:
kubectl -n database exec -it database-1 -- psql -U postgres -d ssot -c '\dt ipm.*'
```

#### Camada de Mensageria (NATS JetStream via NACK):
```bash
# Listar Streams gerenciados pelo operador NACK:
kubectl -n messaging get streams.jetstream.nats.io

# Inspecionar consumidores JetStream ativos:
kubectl -n messaging get consumers.jetstream.nats.io

# Inspecionar estatísticas do Stream via CLI dentro do pod NATS:
kubectl -n messaging exec -it messaging-0 -- nats stream report
```

#### Camada de Segredos e Certificados (`cert-manager` e `External Secrets`):
```bash
# Conferir emissores de certificados (ClusterIssuer):
kubectl get clusterissuers

# Conferir certificados emitidos e prontidão:
kubectl get certificates -A

# Conferir sincronização de segredos do Vault via External Secrets:
kubectl get clustersecretstores
kubectl get externalsecrets -A
```

---

## 7. Guia de Diagnóstico e Resolução de Problemas (*Troubleshooting*)

### 7.1 Pod em `CrashLoopBackOff` ou `ImagePullBackOff`

#### Sintoma:
O Pod de uma feature ou serviço não inicia e fica em `ImagePullBackOff`, `ErrImagePull` ou `CrashLoopBackOff`.

#### Diagnóstico:
```bash
# 1. Identificar o motivo no describe do Pod:
kubectl -n <namespace> describe pod <nome-do-pod>

# 2. Ler os logs de saída de erro da inicialização:
kubectl -n <namespace> logs <nome-do-pod> --previous
```

#### Resolução:
- **Se o erro for `ErrImagePull` / `ImagePullBackOff`:**
  A imagem da feature ainda não foi enviada para o registry local ou o containerd não a baixou. Execute o build e envio:
  ```bash
  ./scripts/dev/build-push <módulo>/<tipo>
  ```
  Se o erro persistir, verifique se o container registry está em execução:
  ```bash
  docker ps --filter "name=smarkee-registry"
  ```
  Caso esteja parado, execute: `docker start smarkee-registry`.

- **Se o erro for `CrashLoopBackOff` por falha de segredo ou banco:**
  Verifique se o `Secret` esperado pelo Deployment foi criado pelo External Secrets Operator:
  ```bash
  kubectl -n <namespace> get secret
  ```
  Se a `Secret` estiver ausente, consulte a seção 7.5.

---

### 7.2 Vault Selado (`Sealed: true`)

#### Sintoma:
Os pods de aplicação começam a falhar com erro de autenticação, o `ExternalSecret` não sincroniza novas credenciais e o status do Vault acusa `Sealed: true`.

#### Diagnóstico:
```bash
kubectl -n vault exec vault-0 -- bao status
```
Saída indicando o problema:
```text
Key             Value
---             -----
Initialized     true
Sealed          true
```

#### Resolução:
Reaplique as chaves de unseal utilizando o utilitário oficial:
```bash
./scripts/dev/vault-bootstrap
```
Alternativamente, se desejar deslacrar manualmente com a chave contida em `.workspace/vault-init.json`:
```bash
UNSEAL_KEY=$(jq -r .unseal_keys_b64[0] .workspace/vault-init.json)
kubectl -n vault exec -it vault-0 -- bao operator unseal "${UNSEAL_KEY}"
```

---

### 7.3 ArgoCD: Aplicação `OutOfSync` ou `Degraded`

#### Sintoma:
No `kubectl -n gitops-operator get applications`, uma ou mais aplicações constam com status `OutOfSync` ou `Degraded`.

#### Diagnóstico:
```bash
# Ver as mensagens detalhadas de erro da reconciliação:
kubectl -n gitops-operator get application <nome-da-app> -o jsonpath='{.status.conditions}' | jq .
kubectl -n gitops-operator get application <nome-da-app> -o jsonpath='{.status.operationState.message}'
```

#### Causas Comuns e Resoluções:
1. **Cache desatualizado do repositório Git interno:**
   O `git-server` acabou de commitar e o ArgoCD ainda não fez o poll. Execute o hard-refresh:
   ```bash
   kubectl -n gitops-operator annotate application <nome-da-app> argocd.argoproj.io/refresh=hard --overwrite
   ```
2. **Erro de validação de schema ou campos imutáveis:**
   Se uma alteração de manifesto tentou alterar um campo imutável (ex: `selector` de Deployment ou `clusterIP` de Service), delete manualmente o recurso conflitante para que o ArgoCD o recrie de acordo com o Kustomize:
   ```bash
   kubectl -n <namespace> delete deployment <nome-do-deployment>
   ```

---

### 7.4 NATS JetStream: Consumidor Travado ou Mensagens em Atraso

#### Sintoma:
Mensagens `desired` são gravadas no outbox e publicadas, mas o controller não reage e o estado observado do recurso não transita para `Ready`.

#### Diagnóstico:
```bash
# Inspecionar o status dos consumidores JetStream:
kubectl -n messaging exec -it messaging-0 -- nats consumer report
```
Verifique a coluna `Num Ack Pending` ou `Num Redelivered`. Se houver mensagens pendentes de ACK ou muitas redeliveries:

```bash
# Inspecionar detalhes do consumidor específico da feature:
kubectl -n messaging exec -it messaging-0 -- nats consumer info DESIRED <módulo>-<tipo>-controller
```

#### Resolução:
1. Verifique os logs do controller para identificar se o payload causou erro de decodificação ou validação de schema:
   ```bash
   kubectl -n <módulo> logs deployment/<módulo>-<tipo>-controller --tail=100
   ```
2. Reinicie o deployment do controller para reestabelecer a conexão NATS e liberar a fila de processamento:
   ```bash
   kubectl -n <módulo> rollout restart deployment/<módulo>-<tipo>-controller
   ```

---

### 7.5 `ExternalSecret` em Falha (`SecretStoreNotReady`)

#### Sintoma:
O objeto `ExternalSecret` fica com condição `Ready: False` e motivo `SecretStoreNotReady` ou `VaultServerError`.

#### Diagnóstico:
```bash
kubectl -n <namespace> describe externalsecret <nome-do-recurso>
```

#### Causas e Resoluções:
1. **O Vault está selado:** Siga o procedimento da seção 7.2 para deslacrar o Vault.
2. **ClusterSecretStore não consegue autenticar via ServiceAccount:**
   Verifique o status do `ClusterSecretStore`:
   ```bash
   kubectl describe clustersecretstore vault-svm
   ```
   Se indicar erro de token, confirme se a ServiceAccount `external-secrets` no namespace `external-secrets-operator` existe e se a Role no Vault (`external-secrets-role`) foi criada pelo `vault-bootstrap`:
   ```bash
   ./scripts/dev/vault-bootstrap
   ```

---

### 7.6 Certificado TLS do `cert-manager` não Emitido

#### Sintoma:
A `Secret` do tipo `kubernetes.io/tls` não é gerada e o objeto `Certificate` fica com status `Ready: False`.

#### Diagnóstico:
```bash
# 1. Inspecionar o Certificate:
kubectl -n <namespace> describe certificate <nome-do-cert>

# 2. Inspecionar o CertificateRequest gerado:
kubectl -n <namespace> get certificaterequests
kubectl -n <namespace> describe certificaterequest <nome-do-cr>

# 3. Ler logs do cert-manager:
kubectl -n cert-manager-operator logs -l app=cert-manager --tail=50
```

#### Resolução:
Se o erro indicar falha de permissão no Vault PKI (`/clm`), verifique se o `ClusterIssuer` aponta para a URL interna correta (`http://clm.vault.svc.cluster.local:8200/v1/clm`) e se a role `cert-manager-role` está autorizada a emitir certificados. Reaplique `./scripts/dev/vault-bootstrap` se necessário.

---

### 7.7 Telemetria não Gravando nos Arquivos `.jsonl` do Host

#### Sintoma:
Ao rodar `./scripts/dev/check` ou `pytest tests/telemetry`, os testes falham informando que nenhum arquivo `.jsonl` foi encontrado nos diretórios locais de `infrastructure/dev/telemetry-sink/` ou `features/*/*/telemeter/`.

#### Diagnóstico:
```bash
# 1. Conferir status dos coletores OpenTelemetry:
kubectl -n telemetry get opentelemetrycollectors

# 2. Conferir logs do telemetry-sink:
kubectl -n telemetry logs deployment/telemetry-sink-collector

# 3. Conferir permissões dos diretórios locais no host:
ls -la infrastructure/dev/telemetry-sink/logs/app
```

#### Resolução:
1. Se os diretórios não existiam antes do cluster kind ter sido criado, o Docker monta esses caminhos como pertencentes ao usuário `root`, impedindo a escrita do coletor. Execute a redefinição limpa:
   ```bash
   (cd scripts/dev/telemetry-reset && uv run smarkee-dev-telemetry-reset --apply)
   ```
2. Reinicie o coletor para reabrir os manipuladores de arquivo:
   ```bash
   kubectl -n telemetry rollout restart deployment/telemetry-sink-collector
   ```
