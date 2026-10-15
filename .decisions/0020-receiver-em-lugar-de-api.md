# 0020 — Receiver em lugar de API como nome do papel

- **Data:** 2026-10-11
- **Status:** Aceita. Renomeia o papel `api` das decisões anteriores (0006 a 0019). Não altera nenhum comportamento.
- **Rotas:** os caminhos citados aqui (`/v1/users`, `/v1/organizations`, `/v1/<tipos>`) foram substituídos pelo padrão da decisão 0030 (`/v1/<módulo>/<tipos>`).

## Contexto

Os papéis do loop são agentes nomeados por um substantivo terminado em "r" (manager, publisher, observer, reconciler, executor). O primeiro papel era chamado `api`, que nomeia uma interface, e não um agente, e destoava dos demais. O papel recebe os pedidos do cliente (`POST`, `PATCH`, `DELETE`), autentica, autoriza, valida, atribui as identidades e publica `requested`, e também atende as leituras (`GET`) pelas views do SSOT.

## Decisão

- O papel passa a se chamar **Receiver** (`receiver` em identificadores).
- **O que muda:**
  - projeto, pacote e imagem: `<módulo>-<tipo>-receiver` / `<módulo>_<tipo>_receiver` (pasta `features/<módulo>/<tipo>/receiver/`);
  - identidade de mensageria: `<módulo>-<tipo>-receiver`, no lugar de `api-<módulo>-<tipo>`; passa a seguir o mesmo padrão `<módulo>-<tipo>-<papel>` dos demais papéis (sem prefixo; o prefixo `srv-` usado em versões anteriores desta decisão foi retirado em 2026-10-12, por decisão do usuário, em todas as identidades, nomes de conexão e docs);
  - **emissor** da mensagem `requested`: `receiver`, no lugar de `api` (enum `emitter` do envelope), e o Subject `receiver.requested.<módulo>.<tipo>.<resourceId>.<operação>` (Stream `REQUESTED`);
  - papel de banco: `<módulo>_<tipo>_receiver` (login `..._receiver_login`);
  - variáveis de ambiente: `<MÓDULO>_<TIPO>_RECEIVER_<SEÇÃO>_<CAMPO>`;
  - contêiner e serviço de Compose: `<módulo>-<tipo>-receiver.smarkee.internal`; rota do gateway.
- **O que não muda:**
  - a **interface HTTP** continua sendo a API do recurso: `/v1/<tipos>`, o OpenAPI, os contratos `api-error`, `api-accepted-response`, `api-create-request` e `api-update-request`, o host público `api-dev.smarkee.com.br` e a configuração `apiUrl` do CLI. O Receiver é o componente que expõe essa API;
  - termos de sistemas externos: API do Zitadel (Admin, Management, v2), API do JetStream (`$JS.API`), API do SonarQube;
  - a ordem de acesso e de desenvolvimento "API → CLI → console web" da decisão 0013, que fala da API como superfície;
  - o histórico: as decisões anteriores foram atualizadas apenas no nome do papel.
- O contrato `emitter` muda de valor. Como ainda não há consumidor externo, a mudança é feita sem janela de compatibilidade, e os modelos gerados dos componentes foram regerados.

## Justificativa

- Nome de agente, como os outros papéis, e que descreve o que o componente faz no loop (recebe o pedido), sem se confundir com "a API" como interface ou com APIs de sistemas externos.
- A identidade de mensageria passa a seguir o padrão único `<módulo>-<tipo>-<papel>`.
- Alternativa descartada: manter `api`. Preservaria o nome nos contratos, mas deixaria o papel destoante, e o custo de trocar é menor agora, antes de existir consumidor externo ou ambiente Kubernetes.

## Consequências

- Em dev, foram recriados: o Stream `REQUESTED` (Subject `receiver.requested.>`) e os consumers `core-user-manager-requested` e `ipm-organization-manager-requested`; os papéis de banco `core_user_receiver` e `ipm_organization_receiver` (os `..._api` foram removidos); as rotas do gateway.
- Quem usa a API HTTP não percebe a mudança.
