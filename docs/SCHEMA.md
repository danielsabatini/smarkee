# Especificação de Schemas

> **Escopo:** governança, organização, modelagem, versionamento, compatibilidade e validação dos schemas do projeto.
>
> **Papel:** Fonte de Verdade das regras de schemas.
>
> **Responsabilidade:** Definir como schemas são concebidos, identificados, organizados, versionados, validados e consumidos, de forma independente da linguagem de programação, formato de serialização, broker de mensageria, banco de dados ou provedor de infraestrutura.

## 1. Introdução

Schemas são contratos formais que definem a estrutura, os tipos, as restrições e a semântica estrutural dos dados intercambiados entre componentes do sistema.

Este documento estabelece as regras gerais para criação e evolução dos schemas. A especificação é agnóstica quanto ao mecanismo utilizado para representar o contrato.

Exemplos de formatos possíveis incluem JSON Schema, Protobuf, Avro, OpenAPI Schema e outros. O formato utilizado é uma decisão de implementação do contrato e não altera as regras semânticas definidas neste documento.

A arquitetura separa claramente quatro responsabilidades:

```text
MESSAGING.md
    ↓
define a semântica da mensagem

SCHEMA.md
    ↓
define as regras para criação e evolução dos schemas

schemas/
    ↓
define o contrato formal de cada recurso/mensagem

components / features
    ↓
implementam e consomem os contratos

NATS.md
    ↓
define o transporte da mensageria por NATS
```

## 2. Objetivo

Os objetivos deste documento são:

- estabelecer uma regra única e explícita para schemas;
- evitar contratos implícitos espalhados pelo código;
- garantir consistência entre componentes e domínios;
- permitir validação automática dos contratos;
- controlar evolução e compatibilidade;
- reduzir acoplamento entre schema, linguagem, transporte e infraestrutura;
- preservar simplicidade, robustez e resiliência durante a evolução dos contratos.

## 3. Fonte de Verdade e Precedência

Existem dois níveis distintos de fonte de verdade.

### 3.1. SCHEMA.md

`docs/SCHEMA.md` é a fonte de verdade para **as regras de governança e modelagem de schemas**.

Define, entre outros aspectos:

- organização dos schemas;
- convenções de nomenclatura;
- estrutura mínima;
- versionamento;
- compatibilidade;
- regras de evolução;
- validação;
- referências entre schemas;
- política para campos opcionais, obrigatórios e desconhecidos.

### 3.2. Arquivo do schema

Cada arquivo localizado em `schemas/` é a fonte de verdade para **o contrato formal daquele schema específico**.

Exemplo:

```text
schemas/ipm/agent/desired.schema.json
```

é a fonte de verdade do contrato formal de `Agent Desired`.

Nenhum documento de implementação, código Python, migration, configuração de broker ou exemplo pode redefinir silenciosamente esse contrato.

### 3.3. Precedência

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

`MESSAGING.md` continua sendo a fonte de verdade para a **semântica de mensageria**. `SCHEMA.md` não redefine essa semântica; define como ela é representada formalmente em schemas.

## 4. Princípios

### 4.1. Explícito é melhor que implícito

Todo contrato relevante deve ser expresso explicitamente.

Evitar depender de convenções não documentadas, comportamento do parser, coerção automática ou conhecimento implícito no código.

### 4.2. Semântica antes da representação

Primeiro define-se o significado do dado. Depois escolhe-se como representá-lo no schema.

```text
Conceito de domínio
    ↓
Semântica
    ↓
Contrato
    ↓
Representação do schema
```

### 4.3. Um contrato, uma responsabilidade

Um schema deve representar um contrato coeso.

Evitar schemas genéricos que agregam conceitos sem relação apenas para reduzir a quantidade de arquivos.

### 4.4. Independência tecnológica

O contrato não deve depender de:

- Python ou outra linguagem;
- framework;
- banco de dados;
- NATS ou outro broker;
- Kubernetes;
- cloud provider;
- implementação interna de um componente.

### 4.5. Compatibilidade explícita

A evolução de um schema deve considerar explicitamente compatibilidade para produtores e consumidores.

### 4.6. Simplicidade

Não adicionar campos, abstrações, referências ou camadas de versionamento sem necessidade real.

### 4.7. Segurança por padrão

Schemas não devem expor segredos, credenciais ou material criptográfico. Dados sensíveis devem possuir classificação e tratamento apropriados.

## 5. Organização dos Schemas

Os schemas devem ficar no diretório raiz:

```text
schemas/
```

A organização deve refletir o domínio funcional e não a tecnologia usada para transportar ou processar o contrato.

Estrutura recomendada:

```text
schemas/
├── common/
│   ├── message-envelope.schema.json
│   ├── condition.schema.json
│   └── metadata.schema.json
└── ipm/
    ├── agent/
    │   ├── desired.schema.json
    │   └── observed.schema.json
    ├── runner/
    │   ├── desired.schema.json
    │   └── observed.schema.json
    └── tool/
        ├── desired.schema.json
        └── observed.schema.json
```

### 5.1. `common/`

Contém contratos verdadeiramente compartilhados por múltiplos domínios.

Exemplos:

```text
message-envelope
metadata
condition
resource-reference
```

Um schema somente deve entrar em `common/` quando houver reutilização real e semântica comum.

Não criar abstrações comuns antecipadamente.

### 5.2. Domínios

Schemas específicos devem ficar sob o domínio que possui sua semântica.

Exemplo:

```text
schemas/ipm/agent/
```

não deve ser movido para `common/` apenas porque outro componente também consome `Agent`.

## 6. Tipos de Schema

O projeto pode possuir diferentes tipos de contrato. A classificação deve ser semântica, não tecnológica.

Tipos comuns incluem:

```text
Resource
Command / Intent
Desired
Observed
Event / Fact
Request
Response
Configuration
```

A existência de um tipo específico não implica que ele deva ser usado. O contrato deve ser escolhido conforme a necessidade real.

Para sistemas declarativos, os principais contratos são:

```text
Desired
Observed
```

### 6.1. Desired

Representa o estado pretendido de um recurso.

Não deve ser tratado como confirmação de execução.

Exemplo conceitual:

```json
{
  "resourceId": "01JABCDEF...",
  "desiredGeneration": 4,
  "lifecycle": "active",
  "configuration": {
    "replicas": 3
  }
}
```

### 6.2. Observed

Representa o estado efetivamente observado de um recurso externo ou operacional.

Exemplo conceitual:

```json
{
  "resourceId": "01JABCDEF...",
  "observedGeneration": 4,
  "lifecycle": "active",
  "runtime": {
    "replicas": 3
  }
}
```

`Desired` e `Observed` não devem ser usados como sinônimos de transporte ou resultado de uma chamada.

## 7. Identidade e Nomenclatura

Os schemas devem aplicar nomenclatura explícita e estável.

Evitar nomes genéricos quando existir uma definição mais precisa.

Preferir:

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

Evitar:

```text
id
type
status
version
generation
timestamp
```

quando o contexto não tornar o significado inequívoco.

### 7.1. Identificador do recurso

`resourceId` representa a identidade estável do recurso.

Quando apropriado, deve ser opaco e independente do nome legível do recurso.

Exemplo:

```json
{
  "resourceId": "550e8400-e29b-41d4-a716-446655440000",
  "resourceName": "agent-production"
}
```

O nome pode mudar sem necessariamente alterar a identidade.

### 7.2. Identificadores externos

Identificadores fornecidos por sistemas externos não devem contaminar o contrato genérico com nomes específicos de fornecedores.

Preferir:

```text
externalResourceId
providerReference
externalReference
```

em vez de:

```text
zitadelId
awsResourceId
azureResourceId
providerXId
```

quando o contrato precisa permanecer agnóstico.

## 8. Estrutura de Contrato

Um schema deve separar claramente:

```text
Identidade
Metadados
Semântica do recurso
Estado desejado/observado
Referências
Campos de domínio
```

Para recursos declarativos, uma estrutura conceitual recomendada é:

```text
Resource
├── resourceId
├── metadata
├── desired
└── observed
```

A implementação exata depende do domínio. Não é obrigatório representar essa árvore literalmente.

## 9. Envelope e Payload

O envelope de mensagem e o payload de domínio são conceitos distintos.

### 9.1. Envelope

O envelope contém metadados necessários ao transporte e rastreamento lógico da mensagem.

Exemplo agnóstico:

```json
{
  "messageId": "01JABC...",
  "messageType": "agent.observed",
  "schemaVersion": "1.0",
  "producer": "worker.runner",
  "resourceId": "01JXYZ...",
  "correlationId": "01JCORR...",
  "causationId": "01JCAUSE...",
  "orderingKey": "agent:01JXYZ...",
  "createdAt": "2026-10-04T14:00:00Z",
  "payload": {}
}
```

O exemplo é ilustrativo e agnóstico. Os campos do envelope são definidos em `MESSAGING.md`, incluindo os campos de decisão e rastreabilidade: `presence` (resultado da observação), `actionId` (identidade determinística da decisão) e `requestedBy` (solicitante). Este documento define as regras de evolução e validação do envelope, e não redefine a semântica desses campos.

### 9.2. Payload

O payload contém o contrato específico do domínio.

O envelope não deve absorver atributos de domínio apenas para facilitar uma implementação específica de broker.

### 9.3. Separação

O schema do envelope pode ser compartilhado:

```text
schemas/common/message-envelope.schema.json
```

Enquanto o payload pode possuir um schema próprio:

```text
schemas/ipm/agent/observed.schema.json
```

## 10. Versionamento

Todo schema deve possuir uma estratégia explícita de versionamento.

`schemaVersion` deve identificar a versão do contrato e não a versão da aplicação que o produz.

Exemplo:

```text
1.0
1.1
2.0
```

A estratégia exata de versionamento pode ser SemVer ou outra convenção documentada, mas deve ser consistente no projeto.

### 10.1. Mudanças compatíveis

Exemplos normalmente compatíveis dependem do formato e das regras de consumo, mas podem incluir:

- adicionar um campo opcional;
- adicionar um valor apenas quando consumidores desconhecidos puderem tolerá-lo;
- adicionar metadados que não alterem a interpretação existente.

Compatibilidade nunca deve ser presumida apenas pela sintaxe da mudança.

### 10.2. Mudanças incompatíveis

Exemplos:

- remover campo utilizado;
- alterar o tipo de um campo;
- alterar a semântica de um campo existente;
- tornar obrigatório um campo que antes era opcional;
- renomear um campo sem estratégia de migração.

Mudanças incompatíveis exigem nova versão de contrato conforme a política adotada pelo projeto.

## 11. Evolução de Schemas

Antes de alterar um schema existente, avaliar:

```text
Quem produz?
Quem consome?
Qual é o período de coexistência?
A mudança é compatível?
É necessário versionar?
Existe replay histórico?
Existe persistência de mensagens antigas?
```

A evolução deve seguir preferencialmente:

```text
Nova versão
    ↓
compatibilidade
    ↓
coexistência
    ↓
migração de consumidores
    ↓
remoção controlada da versão antiga
```

Não remover um campo ou versão apenas porque o código atual deixou de utilizá-lo.

## 12. Campos Obrigatórios e Opcionais

Campos obrigatórios devem representar dados necessários para interpretar corretamente o contrato.

Campos opcionais devem ter uma razão explícita para poderem estar ausentes.

Não tornar campos opcionais apenas para facilitar produtores.

Não tornar campos obrigatórios apenas para evitar tratamento de ausência no consumidor.

### 12.1. Default

Defaults devem ser utilizados com cautela.

Um default altera a semântica de ausência para presença implícita. Deve ser usado somente quando essa equivalência for verdadeira para o domínio.

Preferir ausência explícita a defaults que possam mascarar informação.

## 13. Tipos e Restrições

Schemas devem expressar as restrições conhecidas do domínio sempre que isso reduzir ambiguidade.

Exemplos:

```text
string com formato definido
integer com range
number com precisão conhecida
enum para conjunto fechado
array com cardinalidade conhecida
object com propriedades explicitamente definidas
```

Exemplo conceitual em JSON Schema:

```json
{
  "type": "object",
  "properties": {
    "resourceId": {
      "type": "string",
      "minLength": 1
    },
    "replicas": {
      "type": "integer",
      "minimum": 1
    }
  },
  "required": ["resourceId", "replicas"]
}
```

O exemplo demonstra uma representação possível. Não torna JSON Schema obrigatório para o projeto.

## 14. Campos Desconhecidos e Extensibilidade

O comportamento para propriedades desconhecidas deve ser explícito.

Sempre que a ferramenta de schema permitir, definir deliberadamente se campos adicionais são:

```text
permitidos
restritos
ou permitidos somente em extensões conhecidas
```

Para contratos críticos e control-plane, a opção mais restritiva é preferível quando não houver necessidade real de extensibilidade aberta.

Abertura indiscriminada aumenta a possibilidade de:

- typos silenciosos;
- divergência entre produtores e consumidores;
- contratos inconsistentes;
- comportamento inesperado.

## 15. Null, Ausência e Valores Vazios

Ausência, `null`, string vazia, array vazio e valor padrão são conceitos diferentes.

O schema deve definir explicitamente quais são válidos.

Exemplo:

```text
campo ausente → não informado
null           → explicitamente sem valor
""             → string vazia
[]              → coleção vazia
```

Não utilizar `null` como solução genérica para qualquer campo opcional.

## 16. Data e Hora

Valores temporais devem possuir semântica explícita.

Preferir timestamps com timezone explícito, em formato padronizado, quando representar um instante global.

Exemplo:

```text
2026-10-04T14:00:00Z
```

Distinguir claramente:

```text
createdAt
updatedAt
observedAt
lastTransitionAt
expiresAt
```

Não utilizar `timestamp` genérico quando a semântica puder ser explicitada.

## 17. Enumeradores

Enums devem ser utilizados quando o conjunto válido é realmente fechado ou controlado.

Exemplo:

```text
lifecycle:
- active
- deleting
- deleted
```

Não utilizar enum apenas para codificar um conjunto que provavelmente evoluirá de forma aberta sem estratégia de compatibilidade.

A evolução de enums deve considerar consumidores antigos.

## 18. Referências entre Schemas

Schemas podem referenciar outros schemas quando isso representa reutilização semântica real.

Exemplo:

```text
schemas/common/metadata.schema.json
schemas/common/condition.schema.json
schemas/ipm/agent/observed.schema.json
```

Evitar cadeias profundas de referências que dificultem compreensão, validação e versionamento.

Um schema deve continuar compreensível sem exigir a leitura de uma grande árvore de dependências.

## 19. Segurança e Dados Sensíveis

Schemas não devem conter:

- senhas;
- tokens;
- chaves privadas;
- secrets;
- credenciais de acesso;
- material criptográfico bruto.

Quando um contrato precisar representar uma referência a um segredo, deve transportar uma referência segura, e não o segredo em si.

Campos sensíveis devem possuir classificação quando aplicável.

Exemplo:

```text
secretReference
```

é preferível a:

```text
password
privateKey
accessToken
```

quando a intenção é referenciar um segredo externo.

## 20. Validação

Todo schema deve poder ser validado automaticamente.

A validação deve ocorrer em pelo menos três momentos, conforme aplicável:

```text
CI/CD
    ↓
validação estrutural

Publicação/produção
    ↓
validação do contrato

Consumo
    ↓
validação de entrada quando necessária
```

A pipeline deve detectar pelo menos:

- sintaxe inválida;
- referências quebradas;
- schema inconsistente;
- incompatibilidade conforme a política adotada;
- exemplos inválidos;
- versionamento incorreto.

## 21. Exemplos

Exemplos de payloads fazem parte da documentação do contrato, mas não substituem o schema formal.

Cada schema relevante pode possuir exemplos próximos ao contrato:

```text
schemas/ipm/agent/
├── observed.schema.json
├── observed.example.json
├── desired.schema.json
└── desired.example.json
```

Exemplos devem:

- ser válidos contra o schema;
- representar casos reais;
- evitar dados sensíveis;
- ser pequenos e compreensíveis.

Um exemplo não deve introduzir campos ou semânticas que o schema não reconheça.

## 22. Relacionamento com Mensageria

`SCHEMA.md` e `MESSAGING.md` possuem responsabilidades diferentes.

```text
MESSAGING.md
→ o que a mensagem significa

SCHEMA.md
→ como contratos são definidos e evoluídos

schemas/
→ estrutura formal do contrato

NATS.md
→ como o contrato é transportado pelo NATS
```

Um subject, tópico, queue, stream ou consumer não deve redefinir o significado de um schema.

Da mesma forma, um schema não deve conter detalhes específicos do broker.

## 23. Relacionamento com SSOT e Ciclo de Vida End-to-End

O schema representa o contrato formal dos dados ao longo de todo o seu ciclo de vida no ecossistema, garantindo integridade desde a entrada do usuário até a persistência final como Fonte Única da Verdade (SSOT).

### 23.1. Agnosticismo de Produto

O schema dita como um recurso é validado, criado, atualizado e apagado independentemente do produto final. As regras definidas no schema aplicam-se uniformemente a todos os domínios de negócio e serviços.

### 23.2. Fluxo pelo Ecossistema

O mesmo contrato (ou envelope compatível) deve percorrer todas as camadas do sistema de forma íntegra e sem mutações semânticas arbitrárias, passando por:

1. **CLI / UI**: Onde o operador (humano ou máquina) submete a intenção (`Desired`) de criação, atualização ou remoção baseando-se estritamente na estrutura do schema formal.
2. **API**: Onde a requisição de borda é recebida, autenticada e estruturalmente validada contra o schema antes de qualquer processamento.
3. **Messaging (Broker / NATS)**: Onde a intenção validada é envelopada e roteada assincronamente para os serviços responsáveis, mantendo a identidade e o payload definidos no contrato.
4. **Manager / Orchestrators**: Onde as regras de negócio de alto nível processam o estado desejado, verificam dependências e orquestram a execução, consumindo o payload original.
5. **Workers / Executors**: Onde a ação real ocorre, gerando o estado efetivo (`Observed`).
6. **Banco de Dados (SSOT)**: Onde os estados de *Desired* e *Observed* são finalmente consolidados e persistidos em conformidade estrutural rígida com o schema, tornando-se a Fonte Única da Verdade histórica do recurso.

Essa fluidez exige que os schemas não sejam desenhados apenas para o banco de dados ou apenas para a API, mas como um modelo unificado de dados para o ciclo end-to-end do recurso.

A sequência recomendada para recursos declarativos é:

```text
Requisitos
    ↓
Conceitos de domínio
    ↓
Dicionário de dados
    ↓
Contrato do recurso
    ↓
Ciclo de vida
    ↓
Semântica de reconciliação
    ↓
Schema formal
    ↓
Persistência / implementação
```

`schemas/` não deve ser utilizado como mecanismo para descobrir a semântica de um domínio que ainda não foi modelado.

## 24. Compatibilidade e Testes de Contrato

Mudanças em schemas devem possuir testes de contrato quando houver consumidores independentes.

Testes recomendados:

```text
schema aceita payload válido
schema rejeita payload inválido
exemplos são válidos
versão anterior continua compatível quando requerido
referências permanecem resolvíveis
```

Sempre que possível, os testes devem ser automatizados na CI.

## 25. Checklist para Criação de um Schema

Antes de criar um novo schema:

```text
[ ] O conceito de domínio está definido?
[ ] O contrato possui uma responsabilidade clara?
[ ] Existe schema semelhante reutilizável?
[ ] Deve estar em common ou em um domínio específico?
[ ] Os nomes são explícitos?
[ ] resourceId foi separado de resourceName quando aplicável?
[ ] Desired e Observed estão semanticamente corretos?
[ ] Campos obrigatórios estão realmente justificados?
[ ] Null e ausência foram diferenciados?
[ ] Tipos e restrições estão explícitos?
[ ] Campos desconhecidos possuem política explícita?
[ ] O versionamento está definido?
[ ] A compatibilidade foi avaliada?
[ ] Há referências excessivas?
[ ] Existem dados sensíveis?
[ ] O schema possui exemplos?
[ ] Os exemplos validam contra o schema?
[ ] A validação pode ser automatizada?
```

## 26. Checklist para Alteração de um Schema

Antes de alterar um schema existente:

```text
[ ] Identificar produtores e consumidores.
[ ] Identificar versões atualmente em uso.
[ ] Avaliar compatibilidade.
[ ] Avaliar replay de dados históricos.
[ ] Avaliar persistência de mensagens antigas.
[ ] Avaliar impacto em Desired/Observed.
[ ] Avaliar impacto em APIs e componentes.
[ ] Atualizar exemplos.
[ ] Atualizar testes de contrato.
[ ] Atualizar documentação relacionada.
[ ] Registrar decisão arquitetural quando necessário.
```

## 27. Anti-Padrões

São proibidos ou devem ser fortemente evitados:

- definir contrato apenas em código;
- duplicar o mesmo contrato em múltiplos arquivos sem justificativa;
- usar nomes genéricos e ambíguos;
- esconder semântica importante em convenções implícitas;
- adicionar schemas em `common/` sem reutilização real;
- versionar apenas porque o arquivo mudou fisicamente;
- alterar semântica sem alterar versão conforme a política de compatibilidade;
- transportar secrets diretamente no schema;
- colocar detalhes de NATS, Kafka ou outro broker no schema de domínio;
- criar uma camada de abstração apenas para evitar alguns campos repetidos;
- utilizar exemplos que não validam contra o schema;
- tratar `ACK` de mensageria como confirmação de validade ou convergência do recurso.

## 28. Estrutura de Referência

Uma estrutura inicial recomendada para o projeto é:

```text
.
├── docs
│   ├── MESSAGING.md
│   ├── NATS.md
│   └── SCHEMA.md
├── schemas
│   ├── common
│   │   ├── message-envelope.schema.json
│   │   └── condition.schema.json
│   └── ipm
│       └── agent
│           ├── desired.schema.json
│           ├── desired.example.json
│           ├── observed.schema.json
│           └── observed.example.json
├── components
├── features
├── platform
└── infrastructure
```

A estrutura é um ponto de partida. Novos diretórios somente devem ser criados quando houver uma necessidade semântica ou operacional real.

## 29. Critérios de Sucesso

A governança de schemas é considerada adequada quando:

- cada contrato possui uma fonte de verdade única;
- schemas são independentes de tecnologia de implementação;
- a semântica de `Desired` e `Observed` permanece consistente;
- identidade e nomenclatura são explícitas;
- mudanças de contrato podem ser avaliadas quanto à compatibilidade;
- schemas podem ser validados automaticamente;
- exemplos são verificáveis;
- contratos históricos podem ser interpretados durante a janela de retenção/replay necessária;
- componentes não dependem de contratos implícitos espalhados pelo código.

## 30. Referências

- [MESSAGING.md](MESSAGING.md) — semântica de mensageria.
- [NATS.md](NATS.md) — implementação de mensageria em NATS.
- `schemas/` — fonte de verdade dos contratos formais individuais.
