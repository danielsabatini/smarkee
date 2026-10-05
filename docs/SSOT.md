# Especificação do SSOT

> **Escopo:** o que o SSOT guarda, com quais garantias de gravação, concorrência, idempotência, publicação, segurança, evolução e recuperação.
>
> **Papel:** Fonte de Verdade do modelo e das garantias do SSOT.
>
> **Responsabilidade:** Definir o modelo lógico, as invariantes e o comportamento de gravação do SSOT de forma independente de produto, domínio, fornecedor e tecnologia de armazenamento. A implementação em uma tecnologia específica pertence a um documento próprio.

# 1. Introdução

O SSOT (*Single Source of Truth*) é o registro durável da intenção e do estado consolidado de cada recurso gerenciado pelo Resource Control Loop (`RESOURCE-CONTROL-LOOP.md`).

A arquitetura separa quatro responsabilidades:

```text
MESSAGING.md
    ↓
define a semântica das mensagens

SCHEMA.md
    ↓
define as regras dos contratos

SSOT.md
    ↓
define o que é guardado e as garantias de gravação

POSTGRESQL.md
    ↓
define como a implementação de referência cumpre essas garantias
```

# 2. Objetivo

- definir de forma única o que o SSOT guarda e o que não guarda;
- garantir que a intenção, o estado consolidado e as mensagens a publicar sejam gravados de forma atômica;
- tornar a gravação segura sob repetição, concorrência e falha parcial;
- impedir que o armazenamento defina o significado do domínio;
- permitir trocar a tecnologia de armazenamento sem alterar o modelo.

# 3. Fonte de Verdade e Precedência

```text
AGENTS.md
    >
SSOT.md
    >
documento de implementação do armazenamento
    >
implementação
```

`MESSAGING.md` é a fonte de verdade das mensagens e do envelope. `SCHEMA.md` é a fonte de verdade dos contratos formais. `RESOURCE-CONTROL-LOOP.md` define o padrão de convergência. Este documento não redefine esses temas: define como o resultado deles é gravado.

O agent `ssot` é uma instrução de metodologia e aponta para este documento. Ele não é fonte de regras.

# 4. Princípios

- **O dado precede o armazenamento.** Primeiro o significado, as invariantes e o ciclo de vida; só depois a representação.
- **Um único escritor.** O Manager é o único componente do loop que escreve no SSOT.
- **Atomicidade em torno da mensagem.** Cada mensagem consumida é tratada em uma única unidade atômica de gravação.
- **Correção por regras semânticas, não por memória de entrega.** Idempotência não depende de lembrar todas as mensagens já vistas.
- **Segurança por padrão.** Acesso mínimo, dado classificado, nada sensível em log.
- **Simplicidade.** Guardar somente o que o controle do recurso exige.

# 5. Agnosticismo

O modelo não depende de produto, domínio, fornecedor externo nem tecnologia de armazenamento. Conceitos de um fornecedor específico não entram no modelo; usam-se `externalResourceId`, `externalReference` e `providerReference`.

Um tipo de recurso concreto é descrito por um contrato de domínio (`SCHEMA.md`), e não por este documento. Os exemplos usam nomes neutros.

# 6. Escopo: o que é guardado

## 6.1 Guardado

- a identidade e a intenção do recurso (`desired` e seus controles);
- o último estado observado e o seu resultado (`observed`, `presence`, `observedAt`);
- o estado consolidado (`phase`, `conditions`);
- as gerações e a versão para controle de concorrência;
- as operações assíncronas em andamento ou concluídas (`Operation`);
- as mensagens aguardando publicação (outbox);
- o registro de mensagens recebidas, apenas para reduzir reprocessamento (inbox).

## 6.2 Não guardado

- o **histórico completo** de observações e de mudanças: pertence ao registro de auditoria, que é um consumidor do transporte e não participa da operação do loop;
- segredos: apenas referências (`SCHEMA.md`);
- projeções de interface, métricas e relatórios: são construídos por consumidores.

# 7. Modelo Lógico

## 7.1 Resource

Registro consolidado de um recurso. Existe um conjunto de registros por tipo de recurso, todos com a mesma estrutura.

| Elemento | Significado |
|---|---|
| Identidade | `resourceId` estável, opaco e válido conforme `SCHEMA.md` |
| Intenção | `lifecycle`, `reconciliation` e o conteúdo declarativo de `desired` |
| Observação | último `observed`, `presence` e `observedAt` |
| Consolidação | `phase` e `conditions` |
| Versionamento | `desiredGeneration` e `resourceVersion` |
| Falhas | contagem de falhas da geração corrente |
| Contrato | `schemaVersion` do contrato com que o conteúdo foi gravado |
| Tempo | `createdAt` e `updatedAt` |

## 7.2 Operation

Registro de uma solicitação assíncrona (`RESOURCE-CONTROL-LOOP.md`): identifica a solicitação, o recurso, a geração, o solicitante, o estado do processamento, a chave de idempotência da solicitação e os tempos. Não se confunde com o Resource.

## 7.3 Outbox

Registro de cada mensagem que o Manager deve publicar, gravado **na mesma unidade atômica** da alteração que a originou. Contém a identidade da mensagem, o endereço lógico, o conteúdo, a ordem de gravação e o instante de publicação.

## 7.4 Inbox

Registro curto de identidades de mensagens já tratadas. Reduz reprocessamento, mas **não é a garantia de correção** (ver idempotência de entrada).

# 8. Dicionário de Dados

| Campo | Definição | Tipo conceitual | Obrigatório | Mutabilidade | Escritor | Sensibilidade |
|---|---|---|---|---|---|---|
| `resourceId` | Identidade estável do recurso | texto no padrão comum | Sim | Imutável | Servidor (na criação) | `internal` |
| `lifecycle` | Intenção de existência | enumeração fechada: `present`, `absent` | Sim | Mutável | Manager | `internal` |
| `reconciliation` | Controle da reconciliação | enumeração fechada: `active`, `suspended` | Sim | Mutável | Manager | `internal` |
| `desired` | Conteúdo declarativo do recurso | objeto do contrato do recurso | Sim | Mutável | Manager | por campo do contrato |
| `desiredGeneration` | Versão lógica da especificação | inteiro crescente | Sim | Automática | Manager | `internal` |
| `resourceVersion` | Versão persistida, para concorrência otimista | valor opaco | Sim | Automática | Manager | `internal` |
| `observed` | Último estado lido do sistema externo | objeto do contrato do recurso | Não | Mutável | Manager | por campo do contrato |
| `presence` | Resultado da observação | enumeração fechada: `present`, `absent`, `unknown` | Não | Mutável | Manager | `internal` |
| `observedAt` | Momento da observação | instante | Não | Mutável | Manager | `internal` |
| `phase` | Fase consolidada | enumeração fechada: `Pending`, `Reconciling`, `Ready`, `Failed`, `Deleting` | Sim | Mutável | Manager | `internal` |
| `conditions` | Fatos consolidados do recurso | lista de condition | Sim | Mutável | Manager | `internal` |
| `failureCount` | Falhas da geração corrente | inteiro | Sim | Automática | Manager | `internal` |
| `schemaVersion` | Versão do contrato do conteúdo | `MAJOR.MINOR` | Sim | Mutável | Manager | `internal` |
| `createdAt`, `updatedAt` | Instantes de criação e de alteração | instante | Sim | Automática | Manager | `internal` |

Campos de `desired` e `observed` herdam a sensibilidade declarada no contrato do recurso. Um campo `confidential` não é gravado em log, em mensagem de erro nem em métrica.

# 9. Invariantes

1. **`resourceId` é único e imutável** dentro do tipo.
2. **`desiredGeneration` só aumenta**, e só quando a **especificação** muda. Alterar apenas `reconciliation` não a incrementa.
3. **`resourceVersion` muda a cada gravação** do registro e é a base do controle otimista.
4. **Toda gravação que gera mensagem registra a mensagem no outbox na mesma unidade atômica.** Não existe o estado "alterado, mas sem mensagem a publicar".
5. **`observed` nunca retrocede:** uma observação só substitui a existente se for mais recente (`observedAt`).
6. **`phase` e `failureCount` são derivados** das mensagens consumidas e das invariantes, e não de entrada externa.
7. **O SSOT não executa nada** no sistema externo e não depende de resposta dele para gravar.
8. **Remoção física só ocorre após a convergência** da remoção.

# 10. Unidade Atômica de Gravação

Cada mensagem consumida pelo Manager é tratada em **uma unidade atômica**. A confirmação ao transporte ocorre **somente depois** da gravação durável.

## 10.1 `requested`

1. verificar duplicidade da solicitação (chave de idempotência);
2. validar o pedido e as regras de negócio;
3. conferir a `resourceVersion` informada (atualizações);
4. gravar o recurso: incrementar `desiredGeneration` somente se a especificação mudou;
5. registrar a Operation;
6. registrar no outbox a mensagem `desired`;
7. confirmar a gravação e, então, confirmar a mensagem ao transporte.

## 10.2 `observed`

1. verificar duplicidade;
2. descartar a mensagem se `observedAt` não for mais recente que o gravado;
3. gravar `observed`, `presence` e `observedAt`, e recalcular `conditions` e `phase`;
4. registrar no outbox a mensagem `updated`;
5. confirmar.

## 10.3 `completed` e `failed`

1. verificar duplicidade;
2. atualizar a Operation e as `conditions`;
3. em `failed`, incrementar `failureCount` da geração; ao atingir o `failureLimit` do contrato, definir `phase = Failed` e registrar no outbox o `desired` com `reconciliation = suspended` (mesma geração);
4. registrar no outbox a mensagem `updated`;
5. confirmar.

## 10.4 Nova geração

Quando a especificação muda, `desiredGeneration` aumenta, `failureCount` é zerado e a reconciliação volta a `active`, salvo declaração em contrário no pedido.

# 11. Concorrência

O controle é **otimista**. Uma atualização informa a `resourceVersion` que leu. Se o registro foi alterado depois, a atualização é rejeitada e o solicitante recebe um conflito explícito. A atualização não sobrescreve silenciosamente uma alteração concorrente.

Atualizações do mesmo recurso por mensagens internas (observação e resultado) são serializadas pela própria unidade atômica de gravação; em caso de conflito, a unidade é repetida a partir do estado atual.

# 12. Idempotência de Entrada

Mensagens do transporte podem ser entregues mais de uma vez e, para mensagens de estado, **muito depois** da primeira entrega (por exemplo, quando um consumidor reconstrói seu estado). Por isso a correção não depende de lembrar todas as mensagens já vistas.

| Mensagem | Regra semântica de idempotência |
|---|---|
| `requested` | Chave de idempotência da solicitação, única por tipo de recurso, com prazo definido pelo domínio |
| `observed` | Monotonia de `observedAt`: observação não mais recente é descartada |
| `completed`, `failed` | Identidade da ação (`actionId`): o resultado de uma ação já registrada não é contado de novo |

O inbox registra identidades de mensagens para evitar trabalho repetido **dentro de uma janela curta**. A perda ou a expiração do inbox não compromete a correção.

# 13. Outbox

A publicação das mensagens registradas no outbox é feita por um **relay**, que é um componente de infraestrutura e não executa regra de negócio.

- a entrega é *pelo menos uma vez*: uma falha entre publicar e marcar como publicada resulta em republicação;
- toda mensagem publicada leva a sua identidade (`messageId`) também como chave de deduplicação do transporte, quando suportado; os consumidores continuam idempotentes;
- a **ordem de gravação por recurso é preservada na publicação**. Isso é necessário porque mensagens de `desired` de mesma geração (por exemplo, a suspensão da reconciliação) são ordenadas pela ordem de publicação (`MESSAGING.md`);
- um atraso na publicação é observável (idade da mensagem mais antiga não publicada);
- mensagens publicadas são removidas após um prazo de retenção.

# 14. Ciclo de Vida do Registro

| Etapa | Gravação |
|---|---|
| Criação | Resource com `phase = Pending`, `lifecycle = present`; Operation; outbox (`desired`) |
| Alteração | Nova geração; Operation; outbox (`desired`) |
| Reconciliação | `phase = Reconciling` até a convergência observada; depois `Ready` |
| Falha | `failureCount`; no limite, `phase = Failed` e reconciliação suspensa |
| Suspensão e retomada | Alteração de `reconciliation` sem nova geração; outbox (`desired`) |
| Remoção | `lifecycle = absent`, `phase = Deleting`; após a convergência (`presence = absent`), remoção física do registro |

Após a remoção física, o último `desired` (`lifecycle = absent`) permanece no transporte até a limpeza administrativa (`RESOURCE-CONTROL-LOOP.md`). O SSOT não depende dessa mensagem.

Operações concluídas têm retenção limitada. O que precisa ser mantido a longo prazo pertence ao registro de auditoria.

# 15. Leitura e Consistência

- a API lê o SSOT em **modo somente leitura** para expor o estado atual do recurso e das operações;
- a leitura reflete o que o Manager já gravou. Pode estar atrasada em relação ao sistema externo e ao transporte, e isso é esperado: a convergência é eventual;
- a leitura nunca é usada para decidir uma ação sobre o sistema externo. Quem decide é o Reconciler, a partir do estado recebido pelo transporte.

# 16. Segurança

- somente o Manager do tipo escreve nos registros do tipo; a API lê; o relay lê e marca publicação; a administração do esquema pertence à infraestrutura;
- cada serviço usa identidade própria e privilégios mínimos, escopados ao seu tipo de recurso;
- nenhum serviço do loop possui privilégio de alterar a estrutura nem de remover registros fora do seu papel;
- dados `confidential` e `secretReference` seguem `SCHEMA.md`: não aparecem em log, erro nem métrica, e referências a segredo nunca são resolvidas pelo SSOT;
- o acesso é autenticado e criptografado em trânsito, e o dado é protegido em repouso conforme a classificação;
- credenciais do SSOT são fornecidas por mecanismo seguro de gestão de segredos;
- alterações de estrutura são feitas somente por infraestrutura, versionadas e revisadas.

Os requisitos de segurança do loop estão em `RESOURCE-CONTROL-SECURITY.md`.

# 17. Evolução e Migração

- a estrutura de cada tipo de recurso é gerada a partir de um modelo único (`AGENTS.md`, arquivos gerados); a fonte é o modelo e o contrato, e não a estrutura criada;
- uma mudança compatível de contrato (`MINOR`) não exige migração do conteúdo gravado;
- uma mudança incompatível (`MAJOR`) segue a sequência de `SCHEMA.md`: coexistência, conversão na leitura, migração do conteúdo retido e remoção controlada da versão antiga;
- o `schemaVersion` gravado em cada registro permite identificar o que ainda está em versão antiga;
- migrações são aditivas primeiro (expandir), depois migram o conteúdo e só então removem o antigo (contrair).

# 18. Recuperação e Continuidade

O SSOT é a **única fonte** de Operation, de `conditions` e do histórico consolidado de falhas. Por isso:

- deve existir cópia de segurança com recuperação a um ponto no tempo, e a restauração deve ser testada periodicamente;
- replicação para alta disponibilidade **não substitui** cópia de segurança;
- os objetivos de recuperação (ponto e tempo) são parâmetros do ambiente;
- a reconstrução do SSOT a partir do transporte é **apenas parcial**: o transporte retém o último `desired` e o último `observed` de cada recurso, mas não Operation, `conditions` nem `failureCount`;
- com o SSOT indisponível, o Manager não aceita novos pedidos nem atualiza o estado, mas o loop continua operando sobre o `desired` já publicado;
- após restauração a um ponto anterior, o Manager reavalia o estado e republica o `desired` quando necessário. A geração não retrocede, e os consumidores tratam republicações como idempotentes.

# 19. Observabilidade

Devem ser observáveis, sem expor dados sensíveis:

- idade da mensagem mais antiga não publicada no outbox;
- tamanho do inbox e do outbox;
- conflitos de concorrência e repetições da unidade atômica;
- latência e falhas de gravação;
- quantidade de recursos por `phase`;
- recursos em `Failed` e com `reconciliation = suspended`;
- tempo desde a última observação por tipo de recurso (`observedAt`).

# 20. Anti-Padrões

- escrever no SSOT por um componente que não seja o Manager;
- gravar a alteração e publicar a mensagem em unidades separadas;
- confirmar a mensagem ao transporte antes da gravação durável;
- depender do inbox para a correção da idempotência;
- decidir ação sobre o sistema externo com base na leitura do SSOT;
- tratar a estrutura de armazenamento como o contrato;
- guardar histórico completo de observações no registro do recurso;
- guardar segredo, e não a sua referência;
- usar um único campo genérico para intenção, observação e fase;
- alterar `desiredGeneration` quando muda apenas o controle de reconciliação;
- remover fisicamente antes da convergência da remoção;
- conceder privilégios de estrutura a serviços de runtime.

# 21. Checklist

- [ ] O Manager é o único escritor?
- [ ] Cada mensagem consumida é tratada em uma unidade atômica, com confirmação após a gravação?
- [ ] Toda gravação que gera mensagem registra o outbox na mesma unidade?
- [ ] A ordem por recurso é preservada na publicação?
- [ ] A idempotência de `requested`, `observed` e `completed`/`failed` é semântica?
- [ ] `desiredGeneration` só muda quando a especificação muda?
- [ ] A atualização informa e confere a `resourceVersion`?
- [ ] O dicionário de dados está completo, com sensibilidade e escritor?
- [ ] O que é guardado e o que não é está definido?
- [ ] Os privilégios são mínimos e por tipo de recurso?
- [ ] A estrutura é gerada a partir de um modelo, e a migração segue o `SCHEMA.md`?
- [ ] Existe cópia de segurança com recuperação a um ponto no tempo e teste de restauração?
- [ ] Os sinais de observabilidade estão disponíveis?

# 22. Critérios de Sucesso

O SSOT está adequado quando:

- uma falha entre gravar e publicar não perde nem duplica de forma nociva uma mensagem;
- duas atualizações concorrentes nunca se sobrescrevem em silêncio;
- repetir qualquer mensagem consumida não altera o resultado;
- o modelo é compreensível sem conhecer a tecnologia de armazenamento;
- a tecnologia de armazenamento pode ser trocada sem alterar este documento;
- o estado pode ser recuperado a um ponto no tempo conhecido.

# 23. Referências

- [MESSAGING.md](MESSAGING.md): semântica das mensagens e do envelope.
- [SCHEMA.md](SCHEMA.md): contratos formais, versionamento e classificação.
- [RESOURCE-CONTROL-LOOP.md](RESOURCE-CONTROL-LOOP.md): padrão de convergência.
- [RESOURCE-CONTROL-SECURITY.md](RESOURCE-CONTROL-SECURITY.md): segurança do loop.
- [POSTGRESQL.md](POSTGRESQL.md): implementação de referência do armazenamento.

# 24. Fonte de Verdade

Este documento é a fonte de verdade do **modelo e das garantias de gravação do SSOT**. A implementação em uma tecnologia específica adapta-se a ele, e uma limitação da tecnologia não altera o modelo: a adaptação permanece confinada ao documento de implementação.
