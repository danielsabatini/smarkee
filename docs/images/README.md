# Imagens de apoio

Imagens estáticas usadas como referência visual. Elas **não** são geradas a partir do código e **não** descrevem, por si, a implementação atual. Os diagramas mantidos em sincronia com a implementação são os de [`features/core/account/docs/`](../../features/core/account/docs/) (fonte Mermaid ao lado de cada SVG).

| Arquivo | Situação |
|---|---|
| `Infográfico do Fluxo de Eventos IPM Tenant.png` | **Histórico.** Usa a nomenclatura anterior: recurso `tenant` (hoje, `organization`), emissor `api` (hoje, `receiver`) e Subjects `api.requested.ipm.tenant.*`. A gramática do Subject, os tipos de mensagem e as operações valem; os nomes não. Serve só como estilo de apresentação dos fluxos |
| `infra-overview.png` | **Proposta de arquitetura alvo** (Kubernetes com Knative, OpenBao, Argo CD e a pilha de observabilidade). Não é a implementação: em dev há apenas Docker Compose (`infrastructure/dev`). Não há decisão registrada em `.decisions/` que adote Knative, Argo CD ou essa pilha; o OpenBao aparece nas decisões só como um sistema futuro, com um namespace por Organization (decisão 0006) |
