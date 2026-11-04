# Imagens de apoio

Imagens estáticas usadas como referência visual. Elas **não** são geradas a partir do código e **não** descrevem, por si, a implementação atual. Os diagramas mantidos em sincronia com a implementação são os de [`features/cam/account/docs/`](../../features/cam/account/docs/) (fonte Mermaid ao lado de cada SVG).

| Arquivo | Situação |
|---|---|
| `Infográfico do Fluxo de Eventos IPM Tenant.png` | **Histórico.** Usa a nomenclatura anterior: recurso `tenant` (hoje, `organization`), emissor `api` e Subjects `api.requested.ipm.tenant.*`. Hoje o Subject tem 4 tokens (`desired|updated.<módulo>.<tipo>.<id>`, decisão 0101) e não há `requested`; os nomes e a gramática antigos não valem. Serve só como estilo de apresentação dos fluxos |
| `infra-overview.png` | **Proposta de arquitetura alvo** (Kubernetes com Knative, OpenBao, Argo CD e a pilha de observabilidade). Não é a implementação: o ambiente de dev roda em Kubernetes (`kind`, ArgoCD, OpenBao, CloudNativePG, NACK, OpenTelemetry; decisões 0102 e 0103, `docs/infrastructure/k8s/INFRASTRUCTURE.md`), sem Knative. Serve só como visão de alvo |
