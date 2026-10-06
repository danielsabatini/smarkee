# Especificação de Schemas

> **Escopo:** governança, organização, modelagem, versionamento, compatibilidade, segurança e validação dos schemas do projeto.
>
> **Papel:** Fonte de Verdade das regras de schemas.
>
> **Responsabilidade:** Definir como schemas são concebidos, identificados, organizados, versionados, protegidos, validados e consumidos, de forma independente de produto, domínio, linguagem de programação, formato de serialização, broker de mensageria, banco de dados ou provedor de infraestrutura.

# 1. Introdução

Schemas são contratos formais que definem a estrutura, os tipos, as restrições e a semântica estrutural dos dados intercambiados entre componentes do sistema.

Este documento estabelece as regras gerais para criação, proteção e evolução dos schemas. Ele não define contratos de nenhum produto ou domínio específico: cada contrato pertence ao seu domínio e vive em `schemas/`.

A arquitetura separa quatro responsabilidades:

```text
MESSAGING.md
    ↓
define a semântica da mensagem

SCHEMA.md
    ↓
define as regras para criação, proteção e evolução dos schemas

schemas/
    ↓
define o contrato formal de cada recurso/mensagem

implementações
    ↓
produzem e consomem os contratos
```

O transporte e a segurança do control loop são definidos em documentos próprios (ver a seção de referências).

# 2. Objetivo

- estabelecer uma regra única e explícita para schemas;
- evitar contratos implícitos espalhados pelo código;
- garantir consistência entre componentes e domínios;
- permitir validação automática dos contratos;
- controlar evolução e compatibilidade, inclusive de mensagens retidas;
- proteger as fronteiras de confiança por meio dos contratos;
- reduzir acoplamento entre schema, produto, linguagem, transporte e infraestrutura.

# 3. Fonte de Verdade e Precedência

Existem dois níveis distintos de fonte de verdade.

## 3.1 `SCHEMA.md`

É a fonte de verdade para **as regras de governança, modelagem, segurança e evolução de schemas**.

## 3.2 Arquivo do schema

Cada arquivo localizado em `schemas/` é a fonte de verdade para **o contrato formal daquele schema específico**.

Nenhum documento de implementação, código, migration, configuração de broker ou exemplo pode redefinir silenciosamente esse contrato.

## 3.3 Precedência

Quando houver conflito:

```text
AGENTS.md
    >
docs/SCHEMA.md
    >
schemas/<contract>
    >
implementação
```

`MESSAGING.md` continua sendo a fonte de verdade para a **semântica de mensageria**, inclusive para a definição dos campos do envelope. `SCHEMA.md` não redefine essa semântica: define como ela é representada formalmente, protegida e evoluída em schemas.

# 4. Princípios

- **Explícito é melhor que implícito.** Todo contrato relevante é expresso explicitamente, sem depender de coerção automática, comportamento do parser ou convenção não documentada.
- **Semântica antes da representação.** Primeiro define-se o significado do dado, depois o contrato e só então a representação.
- **Um contrato, uma responsabilidade.** Evitar schemas genéricos que agregam conceitos sem relação.
- **Compatibilidade explícita.** Toda evolução considera produtores e consumidores.
- **Simplicidade.** Não adicionar campos, abstrações, referências ou camadas de versionamento sem necessidade real.
- **Segurança por padrão.** O contrato é uma fronteira de segurança: restringe, limita e classifica.

# 5. Agnosticismo

## 5.1 Produto e domínio

Este documento e as regras que ele define não mencionam nem dependem de produto, módulo ou recurso específico. Exemplos usam nomes neutros (`sample`, `item`).

Contratos de um produto vivem no domínio desse produto, dentro de `schemas/`. Um schema só entra em `common/` quando houver reutilização real entre domínios.

## 5.2 Tecnologia

O contrato não deve depender de linguagem, framework, banco de dados, broker, orquestrador de contêineres, provedor de nuvem ou implementação interna de um componente.

## 5.3 Formato

O formato de representação (por exemplo, JSON Schema, Protobuf, Avro, OpenAPI Schema) é uma decisão de implementação do contrato e não altera as regras semânticas deste documento.

O arquivo de um schema é nomeado `<contrato>.v<MAJOR>.schema.<ext>`, em que `<ext>` depende do formato adotado. Quando o projeto escolher o formato, a escolha deve ser registrada como decisão em `.decisions/`.

Os exemplos deste documento usam JSON apenas para ilustrar.

# 6. Organização dos Schemas

Os schemas ficam no diretório raiz `schemas/`. A organização reflete o domínio funcional, e não a tecnologia usada para transportar ou processar o contrato.

```text
schemas/
├── common/
│   ├── message-envelope.v1.schema.<ext>
│   ├── condition.v1.schema.<ext>
│   └── ...
└── <domain>/
    └── <resource>/
        ├── desired.v1.schema.<ext>
        ├── desired.example.json
        ├── observed.v1.schema.<ext>
        └── observed.example.json
```

## 6.1 `common/`

Contém contratos verdadeiramente compartilhados por múltiplos domínios, por exemplo: envelope, condition, metadata e referência a recurso. Não criar abstrações comuns antecipadamente.

## 6.2 Domínios

Schemas específicos ficam sob o domínio que possui sua semântica. Um schema não deve ser movido para `common/` apenas porque outro componente também o consome.

# 7. Família de Contratos

Os contratos são classificados semanticamente, não tecnologicamente. Para sistemas declarativos, cada recurso possui uma família de contratos, correspondente aos tipos de mensagem de `MESSAGING.md`:

| Contrato | Localização | Conteúdo |
|---|---|---|
| Envelope | `common/` | Campos do envelope definidos em `MESSAGING.md` |
| `requested` | Domínio do recurso | Intenção do cliente |
| `desired` | Domínio do recurso | Estado pretendido e controle de reconciliação |
| `observed` | Domínio do recurso | Estado lido do sistema externo |
| `action` | `common/` | Decisão de reconciliação (motivo) |
| `completed` e `failed` | `common/` | Resultado da operação, referência externa e causa da falha |
| `updated` | `common/` | Resumo da alteração consolidada |
| Resource (visão consolidada) | Domínio do recurso | `phase`, `conditions`, `desired` e `observed` expostos pela API |
| API (request e response) | Domínio do recurso | Contrato de borda das chamadas síncronas. O pedido de criação ou alteração é mapeado para `requested`, e a resposta expõe a visão consolidada |
| Condition | `common/` | Fato consolidado do recurso |

A existência de um contrato não implica que ele deva ser usado: cada recurso define os que precisa. Esta lista é a família esperada e deve ser formalizada em `schemas/` quando os recursos forem modelados.

## 7.1 `desired`

Representa o estado pretendido de um recurso. Não deve ser tratado como confirmação de execução.

Os contratos `desired` de recursos declarativos possuem estes campos de controle:

| Campo | Valores | Significado |
|---|---|---|
| `lifecycle` | `present`, `absent` | Intenção de existência. A remoção é declarada, e não um comando |
| `reconciliation` | `active`, `suspended` | Quando `suspended`, o Reconciler não decide. Padrão: `active` |

Exemplo conceitual do conteúdo (`data`):

```json
{
  "lifecycle": "present",
  "reconciliation": "active",
  "configuration": {
    "replicas": 3
  }
}
```

`desiredGeneration` e `resourceVersion` são campos do envelope e do recurso, definidos em `MESSAGING.md`.

`desiredGeneration` só muda quando muda a **especificação** (`lifecycle` ou os campos de configuração). Alterar apenas `reconciliation` não a incrementa, pois isso reiniciaria a contagem de falhas por geração. O Manager é o único publicador de `desired` de um recurso; quando duas mensagens possuem a mesma geração, a mais recente é a que foi entregue por último no mesmo endereço.

## 7.2 `observed`

Representa o estado efetivamente observado de um recurso externo ou operacional. O resultado da observação (`presence`: `present`, `absent` ou `unknown`) e o momento (`observedAt`) são campos do envelope.

Exemplo conceitual do conteúdo (`data`):

```json
{
  "runtime": {
    "replicas": 3
  },
  "externalResourceId": "ext-0001"
}
```

`desired` e `observed` não devem ser usados como sinônimos de transporte ou de resultado de uma chamada.

## 7.3 Vocabulários distintos

Conceitos diferentes usam campos diferentes e valores diferentes:

| Conceito | Campo | Valores |
|---|---|---|
| Intenção de existência | `lifecycle` (em `desired`) | `present`, `absent` |
| Resultado da observação | `presence` (no envelope de `observed`) | `present`, `absent`, `unknown` |
| Fase consolidada do recurso | `phase` (na visão consolidada) | Definida pelo padrão do control loop (`RESOURCE-CONTROL-LOOP.md`) |

Não reutilizar um desses campos para outro significado.

## 7.4 `requested`

Os contratos `requested` possuem estes campos de controle, atribuídos pela API (`writer = server`) e usados pelo Manager para a idempotência do pedido (`SSOT.md`, Operation):

| Campo | Significado |
|---|---|
| `operationId` | Identidade da Operation. Derivado de forma determinística da chave de idempotência do cliente, no escopo do solicitante e do tipo de recurso, ou aleatório quando o cliente não informa a chave |
| `requestDigest` | Resumo criptográfico da forma canônica do conteúdo pedido; detecta o reuso da mesma chave com outro conteúdo |

A chave de idempotência do cliente é consumida pela API e não é transportada.

# 8. Identidade e Nomenclatura

Os schemas aplicam nomenclatura explícita e estável. Preferir:

```text
resourceId
resourceType
resourceStatus
resourceVersion
schemaVersion
desiredGeneration
observedGeneration
createdAt
updatedAt
observedAt
correlationId
causationId
messageId
```

Evitar `id`, `type`, `status`, `version`, `generation` e `timestamp` quando o contexto não tornar o significado inequívoco.

## 8.1 Identificador do recurso

`resourceId` representa a identidade estável do recurso. Deve ser opaco e independente do nome legível.

O padrão de `resourceId` é definido **uma única vez**, em `common/`, e deve ser compatível com todos os transportes suportados:

```text
^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$
```

Isto é: letras minúsculas, dígitos e hífen, de 1 a 128 caracteres, sem ponto, asterisco, sinal de maior, espaço ou outro separador. Um identificador UUID em minúsculas atende ao padrão. Um valor fora do padrão é rejeitado, e não normalizado.

Na criação, o `resourceId` é atribuído pelo servidor (`writer = server`); o cliente não escolhe a identidade.

```json
{
  "resourceId": "550e8400-e29b-41d4-a716-446655440000",
  "resourceName": "sample-item"
}
```

O nome pode mudar sem alterar a identidade.

## 8.2 Identificadores externos

Identificadores fornecidos por sistemas externos não devem contaminar o contrato genérico com nomes de fornecedores. Preferir `externalResourceId`, `providerReference` e `externalReference`, e não nomes como `vendorXId`.

# 9. Estrutura e Anotações de Contrato

Um schema separa claramente identidade, metadados, semântica do recurso, estado desejado ou observado, referências e campos de domínio.

## 9.1 Anotações de campo

Além de tipo e restrições, cada campo de um contrato declarativo pode ser anotado. As anotações são **abstratas**: a forma de expressá-las depende do formato adotado (por exemplo, palavras-chave de extensão).

| Anotação | Valores | Significado |
|---|---|---|
| `writer` | `client`, `server` | Quem pode preencher o campo. Campos `server` são atribuídos por um componente do sistema (nunca por um cliente externo); um valor enviado por cliente para esse campo é rejeitado |
| `mutability` | `immutable`, `mutable` | Se o campo pode ser alterado após a criação |
| `managed` | `true`, `false` | Se participa da comparação entre `desired` e `observed` |
| `normalization` | nome da regra | Regra aplicada antes da comparação. As regras possuem nome e definição únicos em `common/` (por exemplo, `trim`, `lowercase`, `sort`); uma regra nova exige alteração em `common/` |
| `providerDefault` | `true`, `false` | Se o provider pode preenchê-lo quando ausente em `desired`; nesse caso, o valor observado não é drift |
| `sensitivity` | ver segurança dos contratos | Classificação do dado |
| `enumPolicy` | `closed`, `open` | Política de evolução de um enum (ver evolução) |

A comparação entre `desired` e `observed` (`RESOURCE-CONTROL-LOOP.md`) usa exclusivamente as anotações `managed`, `normalization` e `providerDefault`. Campos não anotados como gerenciados não geram drift.

## 9.2 Parâmetros do recurso

O contrato de um recurso declarativo define os parâmetros de domínio usados pelo control loop. Eles pertencem ao contrato, e não a cada mensagem:

| Parâmetro | Usado por | Significado |
|---|---|---|
| `observationInterval` | Observer | Período da observação periódica |
| `observationValidity` | Reconciler | Idade máxima de um `observed` para decidir (mais estrita para ações destrutivas) |
| `actionDeadline` | Reconciler | Prazo após o qual uma `action` pendente pode ser reemitida |
| `failureLimit` | Manager | Quantidade de falhas por geração antes de marcar o recurso como `Failed` |

Durações usam o formato padronizado de duração (ISO 8601). Os parâmetros são obrigatórios em todo recurso declarativo e não possuem valor padrão: um recurso sem eles não pode ser reconciliado de forma segura.

# 10. Envelope e Payload

O envelope de mensagem e o payload de domínio são conceitos distintos.

## 10.1 Envelope

O envelope contém os metadados necessários ao transporte e ao rastreamento lógico. **Os campos são definidos em `MESSAGING.md`**; este documento define como o contrato do envelope é versionado, validado e protegido.

Exemplo, alinhado a `MESSAGING.md`, com nomes neutros:

```json
{
  "messageId": "01J...",
  "schemaVersion": "1.0",
  "messageType": "desired",
  "emitter": "manager",
  "module": "sample",
  "resourceType": "item",
  "resourceId": "01J...",
  "operation": "changed",
  "desiredGeneration": 1,
  "requestedBy": "01J...",
  "correlationId": "01J...",
  "causationId": "01J...",
  "occurredAt": "2026-10-04T14:00:00Z",
  "publishedAt": "2026-10-04T14:00:01Z",
  "data": {}
}
```

Campos de decisão e rastreabilidade do envelope (`presence`, `actionId`, `requestedBy`) têm a semântica definida em `MESSAGING.md`. No contrato do envelope, `messageId`, `resourceId` (na criação), `requestedBy`, `desiredGeneration`, `actionId` e os campos de data e hora (`occurredAt`, `publishedAt`, `observedAt`) possuem `writer = server`: cada um é atribuído pelo componente responsável, e nunca aceito de um cliente externo.

## 10.2 Payload

O payload (`data`) pertence ao contrato do recurso. O envelope não deve absorver atributos de domínio para facilitar uma implementação específica de broker.

# 11. Versionamento

Todo contrato possui versionamento explícito.

## 11.1 Formato e significado

`schemaVersion` tem o formato `MAJOR.MINOR` e identifica a versão do **contrato da mensagem**, isto é, do envelope somado ao `data` do `messageType` e do tipo de recurso (conforme `MESSAGING.md`). Não é a versão da aplicação, do recurso ou do broker.

| Mudança | Incrementa |
|---|---|
| Compatível (ver evolução) | `MINOR` |
| Incompatível | `MAJOR` |

## 11.2 Arquivos

O nome do arquivo carrega apenas o `MAJOR` (`desired.v1.schema.<ext>`). Versões `MINOR` do mesmo `MAJOR` são compatíveis entre si, de modo que o arquivo representa sempre a versão mais recente do `MAJOR`; o histórico fica no controle de versão. Cada arquivo declara o seu `schemaVersion` atual.

## 11.3 Aceitação

Um consumidor aceita uma mensagem quando suporta o seu `MAJOR`. Um `MINOR` maior que o conhecido é tolerado (campos desconhecidos são ignorados, conforme a regra do leitor tolerante). Um `MAJOR` não suportado é rejeitado explicitamente e não é descartado em silêncio.

## 11.4 Envelope

O envelope faz parte do contrato de toda mensagem. Uma mudança compatível do envelope incrementa o `MINOR` de todos os contratos. Uma mudança incompatível incrementa o `MAJOR` de todos os contratos: é uma migração global, e deve ser registrada como decisão em `.decisions/` antes de ser executada.

# 12. Evolução e Compatibilidade

Antes de alterar um schema existente, avaliar:

```text
Quem produz?
Quem consome?
Qual é o período de coexistência?
A mudança é compatível?
É necessário versionar?
Existe replay histórico?
Existe mensagem retida?
```

## 12.1 Mudanças compatíveis e incompatíveis

Compatibilidade nunca é presumida apenas pela sintaxe da mudança. As regras abaixo assumem a regra do leitor tolerante (seção de campos desconhecidos).

| Compatível (`MINOR`) | Incompatível (`MAJOR`) |
|---|---|
| Adicionar campo opcional | Remover campo utilizado |
| Relaxar uma restrição | Alterar o tipo de um campo |
| Adicionar valor a enum **aberto** | Alterar a semântica de um campo existente |
| Adicionar metadados que não alterem a interpretação | Tornar obrigatório um campo antes opcional |
| | Tornar uma restrição mais estrita |
| | Adicionar valor a enum **fechado** |
| | Renomear um campo sem estratégia de migração |

## 12.2 Sequência de evolução

```text
Nova versão
    ↓
consumidores passam a suportá-la
    ↓
produtores passam a emiti-la (coexistência)
    ↓
migração do que está retido
    ↓
remoção controlada da versão antiga
```

Os consumidores são atualizados **antes** dos produtores. Em uma mudança `MAJOR`, a versão anterior e a nova são suportadas simultaneamente durante a janela de coexistência, e a janela deve ser definida e registrada junto da mudança.

Não remover um campo ou versão apenas porque o código atual deixou de utilizá-lo.

## 12.3 Mensagens retidas

Mensagens de estado (`desired`, `observed`) podem ficar retidas por tempo indeterminado, pois guardam o último estado de cada recurso. A janela de suporte de uma versão deve, portanto, cobrir **a vida das mensagens retidas**, e não apenas o replay.

Antes de remover o suporte a um `MAJOR` antigo, o produtor deve republicar o estado retido na nova versão e verificar que não restam mensagens da versão antiga. Sem essa migração, um consumidor pode encontrar mensagens que não sabe interpretar.

A republicação preserva `desiredGeneration`, `resourceVersion` e o conteúdo; muda apenas a versão do contrato e o `messageId`. Os consumidores tratam a mensagem republicada com a mesma geração como idempotente.

## 12.4 Conversão na leitura

Durante a coexistência, o consumidor converte as versões que suporta para a sua representação interna atual no momento da leitura. A conversão é uma função explícita por versão, coberta por teste de contrato, e não exige que os produtores reescrevam o que já publicaram.

# 13. Campos Obrigatórios, Opcionais e Defaults

Campos obrigatórios representam dados necessários para interpretar corretamente o contrato. Campos opcionais precisam de uma razão explícita para poderem estar ausentes.

Não tornar campos opcionais apenas para facilitar produtores, nem obrigatórios apenas para evitar tratamento de ausência.

Um default altera a semântica de ausência para presença implícita. Deve ser usado somente quando essa equivalência for verdadeira para o domínio. Preferir ausência explícita a defaults que possam mascarar informação.

# 14. Tipos e Restrições

Schemas expressam as restrições conhecidas do domínio sempre que isso reduzir ambiguidade: formato de string, intervalo de inteiro, precisão, enum, cardinalidade de array e propriedades de objeto explicitamente definidas.

## 14.1 Limites obrigatórios

Expressões regulares usadas em restrições devem ser de tempo linear (sem construções que permitam retrocesso exponencial), para impedir negação de serviço pela validação.

Todo contrato define limites, para impedir payloads excessivos:

- comprimento máximo de toda string;
- quantidade máxima de itens de todo array;
- profundidade máxima de objetos aninhados;
- tamanho máximo do conteúdo (`data`) e da mensagem.

Os valores de referência iniciais são definidos em `common/` e só podem ser ampliados por contrato com justificativa:

| Limite | Valor de referência |
|---|---|
| Comprimento de string de identificação ou nome | 256 caracteres |
| Comprimento de string descritiva | 4096 caracteres |
| Itens de um array | 1000 |
| Profundidade de objetos aninhados | 8 níveis |
| Tamanho de `data` | 256 KiB |

O tamanho da mensagem nunca excede o limite do transporte. Um contrato sem limite explícito é inválido.

# 15. Campos Desconhecidos e Extensibilidade

O comportamento para propriedades desconhecidas é explícito. Os objetos de um schema são **fechados**: a definição do contrato não admite propriedades não declaradas. A extensibilidade ocorre por nova versão, e não por abertura do schema.

Existem dois modos de validação:

| Modo | Onde se aplica | Propriedade desconhecida |
|---|---|---|
| Estrito | Entrada de clientes externos e publicação por produtores | Rejeitada |
| Tolerante | Consumo de mensagens internas | Ignorada, desde que o `MAJOR` seja suportado e os campos conhecidos sejam válidos |

O modo tolerante é o que torna compatível a adição de campo opcional (`MINOR`): um consumidor antigo continua válido ao receber uma mensagem de `MINOR` mais novo.

Um consumidor tolerante nunca age sobre um campo que desconhece.

Abertura indiscriminada aumenta a possibilidade de typos silenciosos, divergência entre produtores e consumidores e comportamento inesperado.

# 16. Null, Ausência e Valores Vazios

Ausência, `null`, string vazia, array vazio e valor padrão são conceitos diferentes. O schema define explicitamente quais são válidos.

```text
campo ausente → não informado
null           → explicitamente sem valor
""             → string vazia
[]             → coleção vazia
```

Não utilizar `null` como solução genérica para qualquer campo opcional.

# 17. Data e Hora

Valores temporais possuem semântica explícita. Preferir timestamps com timezone explícito, em formato padronizado (por exemplo, `2026-10-04T14:00:00Z`).

Distinguir claramente `createdAt`, `updatedAt`, `observedAt`, `lastTransitionAt` e `expiresAt`. Não utilizar `timestamp` genérico.

A ordenação lógica de mensagens não deve depender de comparar relógios de componentes diferentes (ver `MESSAGING.md`).

# 18. Enumeradores

Todo enum declara a sua política de evolução (`enumPolicy`):

| Política | Quando | Consumidor diante de valor desconhecido |
|---|---|---|
| `closed` | O conjunto é realmente fechado | Rejeita a mensagem; adicionar valor é `MAJOR` |
| `open` | O conjunto pode crescer | Trata como valor desconhecido e não age sobre ele; adicionar valor é `MINOR` |

Não utilizar enum para um conjunto que provavelmente evoluirá sem estratégia de compatibilidade. Os vocabulários da seção de contratos (`lifecycle`, `reconciliation`, `presence`) são `closed`.

# 19. Referências entre Schemas

Schemas podem referenciar outros schemas quando isso representa reutilização semântica real, como `metadata` e `condition` em `common/`.

Evitar cadeias profundas de referências. Um schema deve continuar compreensível sem exigir a leitura de uma grande árvore de dependências.

Referências são resolvidas apenas dentro de `schemas/`. É proibido resolver referência remota (por URL) em tempo de validação, para evitar dependência externa e leitura de conteúdo não confiável.

# 20. Segurança dos Contratos

O contrato é uma fronteira de segurança.

## 20.1 Segredos

Schemas e mensagens não contêm senhas, tokens, chaves privadas, credenciais de acesso nem material criptográfico bruto. Um contrato que precise representar um segredo transporta uma **referência segura** (por exemplo, `secretReference`), e não o segredo.

## 20.2 Classificação

Todo campo possui a anotação `sensitivity`, com uma destas classes:

| Classe | Tratamento |
|---|---|
| `public` | Pode ser exposto sem restrição |
| `internal` | Restrito ao sistema; não exposto a clientes sem necessidade |
| `confidential` | Dados pessoais ou de negócio; não registrar em log, limitar acesso e retenção |
| `secretReference` | Referência a segredo; nunca o valor |

A classificação é obrigatória e não possui valor padrão: um contrato com campo sem `sensitivity` é inválido. Campos `confidential` não aparecem em logs, mensagens de erro, exemplos reais nem métricas.

## 20.3 Campos atribuídos pelo servidor

Campos com `writer = server` são atribuídos por um componente do sistema: `requestedBy`, `operationId` e `requestDigest` pela API, `desiredGeneration` pelo Manager, `actionId` pelo Reconciler. Um valor enviado por cliente externo para um campo desse tipo é **rejeitado** na API, e não sobrescrito silenciosamente. Isso impede a falsificação de identidade, de geração e de decisão.

Entre componentes internos, quem pode emitir cada campo é controlado pela autorização do emissor (`RESOURCE-CONTROL-SECURITY.md`).

## 20.4 Validação nas fronteiras de confiança

A validação é **obrigatória** em:

- entrada de clientes externos (modo estrito);
- publicação por produtores (modo estrito);
- antes de qualquer escrita em um sistema externo, sobre os campos que serão usados (modo tolerante para os demais).

## 20.5 Limites e erros

- todo contrato possui os limites da seção de tipos e restrições;
- mensagens de erro de validação identificam o campo e a regra violada, e **não repetem valores** classificados como `confidential` ou `secretReference`.

## 20.6 Alteração dos schemas

Os schemas definem o que o sistema aceita. Por isso:

- toda alteração em `schemas/` passa por revisão de um responsável do domínio;
- alterações no envelope, em anotações `writer` e `sensitivity`, em limites e em contratos de campos `confidential` exigem também revisão de segurança;
- as ferramentas de validação e de geração de código têm versão fixada (`AGENTS.md`, dependências).

# 21. Validação

Todo schema pode ser validado automaticamente, em pelo menos três momentos:

```text
CI/CD
    ↓
validação estrutural do próprio schema, dos exemplos e da compatibilidade

Publicação/produção
    ↓
validação do contrato (modo estrito)

Consumo
    ↓
validação de entrada (modo tolerante), obrigatória nas fronteiras de confiança
```

## 21.1 Falha de validação em tempo de execução

- uma mensagem que falha na validação ou que possui `MAJOR` não suportado é uma **falha permanente**: não é reprocessada em ciclo, e segue a política de quarentena do transporte, preservando a mensagem original e o motivo;
- as rejeições são observáveis, com contagem por contrato e por versão, sem registrar valores `confidential`;
- uma entrada externa inválida é rejeitada na borda, com erro que identifica o campo e a regra.

## 21.2 Verificações da pipeline

A pipeline detecta pelo menos:

- sintaxe inválida;
- referências quebradas;
- schema inconsistente;
- incompatibilidade conforme a política de evolução;
- exemplos inválidos;
- versionamento incorreto;
- contrato sem limites ou sem classificação de sensibilidade.

# 22. Artefatos Derivados

Modelos de código, validadores, documentação de API e migrations derivados de um schema são **arquivos gerados**. Seguem o `AGENTS.md`:

1. a fonte é o schema;
2. altera-se o schema, e não o artefato;
3. o artefato é regenerado;
4. a CI regenera e compara: qualquer diferença entre o artefato versionado e o gerado falha a pipeline.

A estrutura de persistência (por exemplo, tabelas do SSOT) é uma representação mapeada do contrato e não é o contrato. Os testes de contrato verificam que o mapeamento preserva a semântica. O modelo lógico e o dicionário de dados do SSOT estão em `SSOT.md`.

# 23. Exemplos

Exemplos de payloads fazem parte da documentação do contrato, mas não substituem o schema formal. Ficam próximos ao contrato (`<contrato>.example.json`).

Exemplos devem ser válidos contra o schema, representar casos reais, evitar dados sensíveis e ser pequenos. Um exemplo não introduz campos ou semânticas que o schema não reconheça.

# 24. Relacionamento com Mensageria e com o Control Loop

```text
MESSAGING.md
→ o que a mensagem significa e quais são os campos do envelope

SCHEMA.md
→ como contratos são definidos, protegidos e evoluídos

schemas/
→ estrutura formal do contrato

RESOURCE-CONTROL-LOOP.md
→ como os contratos participam do ciclo de convergência
```

Um subject, tópico, queue, stream ou consumer não redefine o significado de um schema. Um schema não contém detalhes específicos de broker.

O control loop depende destes contratos:

- a comparação `desired` × `observed` usa as anotações `managed`, `normalization` e `providerDefault`;
- a suspensão da reconciliação usa o campo `reconciliation`;
- os prazos e limites do loop são os parâmetros de recurso;
- os campos `writer = server` sustentam a segurança descrita em `RESOURCE-CONTROL-SECURITY.md`.

# 25. Ciclo de Vida do Contrato

Cada camada do sistema valida e produz o contrato que lhe cabe. O contrato **não é um único objeto que atravessa tudo sem mudar**: cada etapa tem seu contrato, e as transformações entre eles são explícitas.

1. **Cliente / interface:** submete a intenção conforme o contrato `requested`.
2. **API:** autentica, valida estritamente o pedido, atribui os campos `writer = server` e publica `requested`.
3. **Mensageria:** transporta o envelope com o contrato do `messageType`, sem alterar a semântica.
4. **Manager:** valida regras de negócio, produz `desired` e consolida a visão do recurso (`phase`, `conditions`).
5. **Observer:** produz `observed` a partir da leitura do sistema externo.
6. **Reconciler:** produz `action`.
7. **Executor:** valida os campos que usará e produz `completed` ou `failed`.
8. **Persistência (SSOT):** guarda a representação mapeada do contrato.

A sequência recomendada para modelar um recurso declarativo é:

```text
Requisitos
    ↓
Conceitos de domínio
    ↓
Dicionário de dados
    ↓
Contrato do recurso (com anotações e parâmetros)
    ↓
Ciclo de vida
    ↓
Semântica de reconciliação
    ↓
Schema formal
    ↓
Persistência / implementação
```

`schemas/` não deve ser utilizado para descobrir a semântica de um domínio que ainda não foi modelado.

# 26. Testes de Contrato

Mudanças em schemas possuem testes de contrato quando houver consumidores independentes:

```text
schema aceita payload válido
schema rejeita payload inválido
exemplos são válidos
a nova versão aceita toda mensagem válida da versão anterior (leitura retroativa)
a versão anterior, em modo tolerante, aceita mensagem do MINOR mais novo (leitura futura)
modo tolerante ignora campo desconhecido de MINOR mais novo
modo estrito rejeita campo desconhecido
campos com writer = server são rejeitados quando enviados por cliente
referências permanecem resolvíveis
artefatos derivados coincidem com a regeneração
```

Os testes são automatizados na CI.

# 27. Checklists

## 27.1 Criação de um schema

```text
[ ] O conceito de domínio está definido?
[ ] O contrato possui uma responsabilidade clara?
[ ] Existe schema semelhante reutilizável?
[ ] Deve estar em common ou em um domínio específico?
[ ] Os nomes são explícitos e livres de produto ou fornecedor em common?
[ ] resourceId foi separado de resourceName e segue o padrão comum?
[ ] lifecycle, presence e phase não foram confundidos?
[ ] Campos obrigatórios estão justificados?
[ ] Null e ausência foram diferenciados?
[ ] Tipos, restrições e limites estão explícitos?
[ ] Cada campo tem sensibilidade e writer?
[ ] Campos gerenciados, normalização e defaults do provider estão anotados?
[ ] Parâmetros do recurso estão definidos?
[ ] Enums declaram enumPolicy?
[ ] O versionamento e a compatibilidade foram avaliados?
[ ] Existem exemplos que validam contra o schema?
[ ] A validação pode ser automatizada?
```

## 27.2 Alteração de um schema

```text
[ ] Identificar produtores e consumidores.
[ ] Identificar versões em uso.
[ ] Classificar a mudança (MINOR ou MAJOR).
[ ] Definir a janela de coexistência (MAJOR).
[ ] Avaliar replay e mensagens retidas; planejar a republicação.
[ ] Avaliar impacto em desired/observed e no control loop.
[ ] Avaliar impacto em APIs, componentes e artefatos derivados.
[ ] Atualizar exemplos e testes de contrato.
[ ] Obter a revisão exigida (domínio e, quando aplicável, segurança).
[ ] Atualizar documentação relacionada.
[ ] Registrar decisão arquitetural quando necessário.
```

# 28. Anti-Padrões

São proibidos ou devem ser fortemente evitados:

- definir contrato apenas em código;
- duplicar o mesmo contrato em múltiplos arquivos sem justificativa;
- usar nomes genéricos e ambíguos;
- esconder semântica importante em convenções implícitas;
- adicionar schemas em `common/` sem reutilização real;
- versionar apenas porque o arquivo mudou fisicamente;
- alterar semântica sem alterar versão;
- transportar secrets no schema ou nas mensagens;
- colocar detalhes de broker no schema de domínio;
- colocar nome de produto, fornecedor ou módulo específico em `common/` ou neste documento;
- deixar o cliente preencher campos de identidade, geração ou decisão;
- contrato sem limites de tamanho;
- reutilizar `lifecycle`, `presence` ou `phase` para outro significado;
- remover o suporte a uma versão sem migrar o estado retido;
- editar manualmente artefato gerado;
- utilizar exemplos que não validam contra o schema;
- tratar `ACK` de mensageria como confirmação de validade ou convergência do recurso.

# 29. Estrutura de Referência

Uma estrutura inicial recomendada, restrita ao que este documento governa:

```text
.
├── docs/
│   ├── MESSAGING.md
│   ├── SCHEMA.md
│   └── ...
└── schemas/
    ├── common/
    │   ├── message-envelope.v1.schema.<ext>
    │   └── condition.v1.schema.<ext>
    └── <domain>/
        └── <resource>/
            ├── desired.v1.schema.<ext>
            ├── desired.example.json
            ├── observed.v1.schema.<ext>
            └── observed.example.json
```

A estrutura é um ponto de partida. Novos diretórios somente devem ser criados quando houver necessidade semântica ou operacional real.

# 30. Critérios de Sucesso

A governança de schemas é considerada adequada quando:

- cada contrato possui uma fonte de verdade única;
- schemas são independentes de produto e de tecnologia de implementação;
- os vocabulários de `lifecycle`, `presence` e `phase` permanecem consistentes;
- identidade e nomenclatura são explícitas;
- toda mudança pode ser classificada quanto à compatibilidade e possui janela de coexistência;
- o estado retido pode ser interpretado ou migrado;
- schemas são validados automaticamente, inclusive nas fronteiras de confiança;
- campos de servidor não podem ser falsificados por clientes;
- exemplos e artefatos derivados são verificáveis;
- componentes não dependem de contratos implícitos espalhados pelo código.

# 31. Referências

- [MESSAGING.md](MESSAGING.md): semântica de mensageria e campos do envelope.
- [RESOURCE-CONTROL-LOOP.md](RESOURCE-CONTROL-LOOP.md): padrão de convergência que consome estes contratos.
- [RESOURCE-CONTROL-SECURITY.md](RESOURCE-CONTROL-SECURITY.md): segurança do control loop.
- [SSOT.md](SSOT.md): modelo e garantias de gravação do SSOT.
- [NATS.md](NATS.md): implementação do transporte.
- `schemas/`: fonte de verdade dos contratos formais individuais.
