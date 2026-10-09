# 0006 — Organization como unidade de isolamento e identidade única

- **Data:** 2026-10-09
- **Status:** Aceita

## Contexto

Os documentos usavam *Tenant* como tipo de recurso e unidade de isolamento. A implementação de identidade (Zitadel) já possui o conceito de organização, com ID próprio, e cada Tenant seria materializado como uma organização do Zitadel. Outros sistemas também precisam de um escopo por cliente, por exemplo o namespace do OpenBao e o namespace do Kubernetes.

Com dois conceitos (Tenant na plataforma e organização no Zitadel), cada sistema passaria a ter o seu próprio identificador, e a plataforma precisaria de uma tabela de correspondência entre eles.

O `resourceId` é atribuído pela API antes de o recurso existir em qualquer sistema externo (`docs/SCHEMA.md`, *Identificador do recurso*), porque ele compõe o subject do `requested` e a criação pelo loop precisa ser idempotente. O Zitadel aceita um ID informado na criação da organização (`organization_id` em `AddOrganizationRequest`, de 1 a 200 caracteres, verificado no `org_service.proto` da v4.19.4).

## Decisão

- **Organization substitui Tenant** como tipo de recurso e unidade de isolamento (`resourceType = organization`, campo `organizationId`, subjects `*.ipm.organization.*`, serviços `*-ipm-organization-*`).
- **Identidade única:** o `resourceId` da Organization, gerado pela API (UUIDv7), é o ID da organização no Zitadel (informado em `organization_id` na criação) e o nome dos recursos derivados em outros sistemas, como o namespace do OpenBao e o do Kubernetes.
- Recursos que pertencem a uma Organization carregam `organizationId` e o reutilizam como escopo nos sistemas externos.

## Justificativa

- Um único identificador elimina tabelas de correspondência e a possibilidade de divergência entre sistemas (simplicidade, explícito sobre implícito).
- Gerar o ID na API, e não deixá-lo ser gerado pelo Zitadel, preserva o loop assíncrono: o ID existe antes do `requested`, e a criação repetida pelo Executor não produz uma segunda organização.
- Alternativa descartada: usar o ID gerado pelo Zitadel. Exigiria criar a organização de forma síncrona na API, fora do loop, ou publicar o `requested` sem `resourceId`, e o create deixaria de ser idempotente pelo ID.

## Consequências

- `docs/SCHEMA.md` (*Organization e identificadores derivados*), `MESSAGING.md`, `NATS.md`, `RESOURCE-CONTROL-LOOP.md`, `RESOURCE-CONTROL-SECURITY.md` e `POSTGRESQL.md` passam a usar Organization.
- O valor precisa ser válido em todos os sistemas: o namespace do Kubernetes limita a 63 caracteres em formato de rótulo DNS. O UUIDv7 atende; as restrições de nome de namespace do OpenBao ainda precisam ser verificadas.
- Pendente: organizações criadas pelo autocadastro do Zitadel recebem ID gerado por ele (numérico). O valor é válido, mas a forma como essas organizações passam a existir no SSOT ainda não está definida.
- Pendente: verificar o erro devolvido pelo Zitadel ao criar uma organização com ID já existente, para o Executor tratá-lo como sucesso idempotente.
