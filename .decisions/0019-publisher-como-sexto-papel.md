# 0019 — Publisher como sexto papel

- **Data:** 2026-10-11
- **Status:** Aceita. Substitui, na decisão 0017, a parte que faz do relay um modo do Manager. Ajusta a decisão 0015 (o relay deixa de ser papel *e* deixa de ser modo: volta a ser projeto próprio, com o nome `publisher`) e complementa a 0018.

## Contexto

A decisão 0017 fundiu o relay do outbox ao Manager (subcomandos `serve` e `relay`, mesma imagem), com o argumento de que o relay não era um papel do padrão. Ao implementá-la, e depois ao revisar o resultado, ficou claro que:

- o relay **sempre** é necessário em todo tipo de recurso, porque o Manager grava o recurso e a mensagem na mesma transação (outbox) e alguém precisa levá-la ao transporte;
- ele não tem regra de negócio: lê linhas `(sequence, message_id, subject, payload)` e publica;
- ele já era um processo, um *deployment*, um papel de banco e uma identidade de mensageria próprios. Um "modo" do Manager só escondia isso atrás de um subcomando, e deixava o Manager com duas responsabilidades e duas credenciais na mesma imagem;
- os demais papéis têm nomes de agente terminados em "r" (manager, reconciler, observer, executor); "relay" destoava.

## Decisão

- O loop passa a ter **seis papéis**: `receiver`, `manager`, `publisher`, `observer`, `reconciler` e `executor`.
- O **Publisher** publica no transporte, em ordem por recurso, o que o Manager registrou no outbox. Não executa regra de negócio.
- É um **projeto autocontido** por tipo de recurso (decisão 0015), em `features/<módulo>/<tipo>/publisher/` (por exemplo, `features/core/user/publisher`), com código, dependências, testes, imagem e versão próprios. O código é duplicado por tipo, como nos demais papéis (duplicação aceita pela 0015).
- Nomes: projeto e imagem `<módulo>-<tipo>-publisher`, pacote `<módulo>_<tipo>_publisher`, identidade NATS `<módulo>-<tipo>-publisher`, papel de banco `<módulo>_<tipo>_publisher` (login `<módulo>_<tipo>_publisher_login`), variáveis `<MÓDULO>_<TIPO>_PUBLISHER_<SEÇÃO>_<CAMPO>`.
- O **emissor** da mensagem continua `manager` (`emitter`): o `emitter` identifica **quem decidiu** (o Manager), e o Publisher é quem **entrega** (a identidade de mensageria que publica). Em 2026-10-12 o usuário confirmou manter esse desenho e documentá-lo melhor (`RESOURCE-CONTROL-LOOP.md` §6.6.1 e §6.6.2); o campo opcional `publishedBy` do envelope (preenchido pelo Publisher, `writer = server`) torna a entrega visível na própria mensagem, sem mudar o Subject (contrato estendido de forma compatível; ainda sem consumidor externo, por isso `schemaVersion` permanece `1.0`); a alternativa de um emissor `publisher` foi descartada por mudar o Subject sempre que o mecanismo de entrega mudar. Nenhum contrato de mensagem muda.
- O Manager volta a ter um único comportamento (sem subcomandos), com o papel de banco que só **insere** no outbox. O Publisher só **lê** o outbox e atualiza `published_at`.
- Mantêm-se, sem mudança: trava consultiva de sessão (uma instância ativa por outbox), publicação sequencial, `Nats-Msg-Id` igual ao `messageId`, a política de erro permanente e a saúde (decisão 0018) e a estrutura interna por camadas (decisão 0017).

## Justificativa

- Privilégio, escala e domínio de falha diferentes são os critérios da decisão 0015 para separar componentes; o Publisher os atende, e um papel por componente é o padrão do projeto.
- Um processo com uma responsabilidade e uma credencial é mais fácil de entender, operar e proteger do que uma imagem com subcomandos.
- A separação mantém a troca de tecnologia por componente: o Publisher pode ser trocado por captura de mudanças (CDC) ou reescrito em outra linguagem sem tocar no Manager, porque o outbox é o contrato.
- Alternativa descartada: relay como modo do Manager (decisão 0017): escondia um processo e uma credencial próprios atrás de subcomandos e deixava a imagem do Manager com duas responsabilidades.
- Alternativa descartada: um único Publisher genérico de plataforma, implantado por tipo. Evitaria a duplicação, mas contraria a regra de nenhum componente compartilhado entre features (0015) e foi preterida pelo usuário em favor do projeto autocontido por tipo. Se a duplicação virar problema medido, volta-se à decisão com evidência.

## Consequências

- `docs/loop/RESOURCE-CONTROL-LOOP.md`, `SSOT.md`, `POSTGRESQL.md`, `NATS.md`, `RESOURCE-CONTROL-SECURITY.md`, `MESSAGING.md`, os agents e as skills passam a descrever seis papéis e o Publisher.
- No User: projeto `features/core/user/publisher` criado; o Manager perdeu o modo `relay`. No banco de dev, os papéis `core_user_relay` e `core_user_relay_login` foram substituídos por `core_user_publisher` e `core_user_publisher_login`, e as variáveis `CORE_USER_RELAY_*` por `CORE_USER_PUBLISHER_*`.
- A Organization (`features/ipm/organization`) adotou o Publisher ao ser refeita a partir do User (decisão 0038): `relay/` virou `publisher/` e o papel de banco `ipm_organization_relay`, `ipm_organization_publisher`.
- O teste de caos (`E2E_CHAOS=1`) passa a derrubar o Publisher.
