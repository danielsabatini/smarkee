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
- os resultados de ação já contabilizados (`ActionResult`), para a idempotência de `completed` e `failed`;
- as mensagens aguardando publicação (outbox).

Não existe inbox: a idempotência de entrada é garantida pelas regras semânticas da seção de idempotência, e um registro de mensagens recebidas não acrescentaria correção.

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

Registro de uma solicitação assíncrona (`RESOURCE-CONTROL-LOOP.md`): identifica a solicitação, o recurso, a geração, o solicitante, o estado do processamento e o seu motivo, o resumo do pedido e os tempos. Não se confunde com o Resource.

A identidade da Operation (`operationId`) é atribuída pela API (`writer = server`), devolvida ao cliente e transportada no `requested`. Ela é a chave de idempotência do pedido no SSOT:

- quando o cliente informa uma chave de idempotência, a API deriva o `operationId` de forma determinística, por função de hash criptográfica sobre o módulo, o tipo de recurso, o solicitante (`requestedBy`) e a chave. A repetição do pedido com a mesma chave produz o mesmo `operationId`, e chaves iguais de solicitantes diferentes produzem identidades diferentes;
- sem chave, a API gera um `operationId` aleatório. A reentrega do mesmo `requested` pelo transporte carrega o mesmo `operationId`.

A API também calcula o **resumo do pedido** (`requestDigest`), uma função de hash criptográfica sobre a forma canônica do conteúdo pedido, e o transporta no `requested`. O resumo detecta o reuso da mesma chave com outro conteúdo.

| `operationStatus` | Significado |
|---|---|
| `accepted` | Pedido gravado; `desired` registrado no outbox |
| `in_progress` | Reconciliação da geração do pedido em andamento |
| `completed` | A geração do pedido convergiu |
| `failed` | A geração do pedido atingiu o `failureLimit` ou foi substituída por outra antes de convergir |
| `rejected` | Pedido não aplicado; o Resource não foi alterado |

Uma Operation `rejected` possui `operationStatusReason`, enumeração fechada:

| `operationStatusReason` | Significado |
|---|---|
| `conflict` | A `resourceVersion` informada está desatualizada |
| `validation` | Regra de negócio violada |
| `not_found` | O recurso não existe |

O motivo não repete valores `confidential` nem `secretReference` (`SCHEMA.md`).

## 7.3 Outbox

Registro de cada mensagem que o Manager deve publicar, gravado **na mesma unidade atômica** da alteração que a originou. Contém a identidade da mensagem, o endereço lógico, o conteúdo, a ordem de gravação e o instante de publicação.

## 7.4 ActionResult

Registro de cada `actionId` cujo resultado (`completed` ou `failed`) já foi contabilizado: identidade da ação, recurso, geração, desfecho e instante do registro. É a garantia de que um resultado reentregue não é contado de novo. Sua retenção é maior que a retenção dos resultados no transporte somada ao prazo máximo de reentrega.

# 8. Dicionário de Dados

| Campo | Definição | Tipo conceitual | Obrigatório | Mutabilidade | Escritor | Sensibilidade |
|---|---|---|---|---|---|---|
| `resourceId` | Identidade estável do recurso | texto no padrão comum | Sim | Imutável | Servidor (na criação) | `internal` |
| `lifecycle` | Intenção de existência | enumeração fechada: `present`, `absent` | Sim | Mutável | Manager | `internal` |
| `reconciliation` | Controle da reconciliação; reflete sempre o último `desired` registrado no outbox | enumeração fechada: `active`, `suspended` | Sim | Mutável | Manager | `internal` |
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
2. **`desiredGeneration` só aumenta**, e só quando a **especificação** muda ou quando a recuperação reafirma a especificação (seção de recuperação). Alterar apenas `reconciliation` não a incrementa.
3. **`resourceVersion` muda a cada gravação** do registro e é a base do controle otimista.
4. **Toda gravação que gera mensagem registra a mensagem no outbox na mesma unidade atômica.** Não existe o estado "alterado, mas sem mensagem a publicar".
5. **`observed` nunca retrocede:** uma observação só substitui a existente se for mais recente (`observedAt`).
6. **`phase` e `failureCount` são derivados** das mensagens consumidas e das invariantes, e não de entrada externa.
7. **O SSOT não executa nada** no sistema externo e não depende de resposta dele para gravar.
8. **Remoção física só ocorre após a convergência** da remoção.
9. **As unidades atômicas de um mesmo recurso são serializadas.** Duas mensagens sobre o mesmo recurso nunca são aplicadas sobre o mesmo estado lido.
10. **Uma geração publicada nunca é reutilizada com outro conteúdo.** Consumidores tratam a mesma geração como idempotente; reutilizá-la com conteúdo diferente causaria divergência silenciosa.
11. **O registro reflete o último `desired` registrado no outbox.** Toda mensagem `desired` corresponde ao conteúdo e ao controle gravados no registro na mesma unidade.

# 10. Unidade Atômica de Gravação

Cada mensagem consumida pelo Manager é tratada em **uma unidade atômica**. A confirmação ao transporte ocorre **somente depois** da gravação durável.

Toda unidade **começa obtendo acesso exclusivo ao registro do recurso** e só então lê o estado atual (invariante 9). Isso serializa as mensagens do mesmo recurso, inclusive `observed` e `completed`/`failed` processados em paralelo por instâncias diferentes, e impede que uma sobrescreva as `conditions` calculadas pela outra.

## 10.1 `requested`

1. obter acesso exclusivo ao registro, quando ele existir. Na criação ainda não há registro: a unicidade da identidade da Operation e do `resourceId` impede que duas entregas simultâneas do mesmo pedido gravem duas vezes;
2. verificar se a Operation (`operationId`) já existe; se existir, a mensagem é uma reentrega ou uma repetição do cliente e é apenas confirmada, sem nova gravação. Se o `requestDigest` for diferente do gravado, o reuso da chave é registrado como sinal de observabilidade, e a Operation original prevalece;
3. validar o pedido e as regras de negócio; em violação, registrar a Operation como `rejected` (`validation` ou `not_found`);
4. conferir a `resourceVersion` informada (atualizações); se estiver desatualizada, registrar a Operation como `rejected` (`conflict`);
5. gravar o recurso: incrementar `desiredGeneration` somente se a especificação mudou;
6. registrar a Operation como `accepted`;
7. registrar no outbox a mensagem `desired`;
8. confirmar a gravação e, então, confirmar a mensagem ao transporte.

Um pedido `rejected` não altera o Resource e não gera `desired`.

Antes de publicar, a API consulta a Operation pelo `operationId`: se ela existir com o mesmo `requestDigest`, a API devolve a Operation existente sem publicar; com resumo diferente, a API rejeita o pedido de imediato. Essa consulta evita publicações repetidas, e o passo 2 cobre as repetições simultâneas que passam por ela.

## 10.2 `observed`

1. obter acesso exclusivo ao registro; se o recurso não existir, descartar a mensagem;
2. descartar a mensagem se `observedAt` não for mais recente que o gravado;
3. gravar `observed`, `presence` e `observedAt`, e recalcular `conditions` e `phase`;
4. registrar no outbox a mensagem `updated`;
5. confirmar.

A monotonia por `observedAt` compara instantes do Observer. Ela é válida porque um recurso é observado por uma instância por vez (partição por `resourceId`, `RESOURCE-CONTROL-LOOP.md`) e porque os relógios do ambiente são sincronizados. Durante a redistribuição de partições, duas instâncias podem observar o mesmo recurso; um desvio de relógio entre elas menor que o `observationInterval` do contrato faz, no pior caso, uma observação ser descartada e substituída pela próxima.

## 10.3 `completed` e `failed`

1. obter acesso exclusivo ao registro;
2. registrar o `actionId` em `ActionResult`; se ele já existir, a mensagem é uma reentrega e é apenas confirmada;
3. atualizar a Operation e as `conditions`;
4. se a geração do resultado for diferente da `desiredGeneration` atual, o resultado não altera `failureCount` nem `phase`: ele se refere a uma especificação substituída;
5. em `failed` da geração atual, incrementar `failureCount`; ao atingir o `failureLimit` do contrato, definir `phase = Failed`, gravar `reconciliation = suspended` no registro e registrar no outbox o `desired` com `reconciliation = suspended` (mesma geração);
6. registrar no outbox a mensagem `updated`;
7. confirmar.

## 10.4 Nova geração

Quando a especificação muda, `desiredGeneration` aumenta, `failureCount` é zerado e a reconciliação volta a `active`, salvo declaração em contrário no pedido.

# 11. Concorrência

O controle para o **solicitante** é **otimista**. Uma atualização informa a `resourceVersion` que leu. Se o registro foi alterado depois, a atualização é rejeitada e a Operation registra o conflito explícito (`rejected`, `conflict`). A atualização não sobrescreve silenciosamente uma alteração concorrente.

Como a API responde de forma assíncrona, o conflito é conhecido pela Operation. A API pode conferir a `resourceVersion` antes de publicar, para devolver o conflito de imediato; essa conferência é uma conveniência, e a decisão é sempre do Manager.

Entre **mensagens internas**, a serialização é pelo acesso exclusivo ao registro no início da unidade (invariante 9). A unidade é repetida a partir do estado atual somente em falha transitória da gravação.

# 12. Idempotência de Entrada

Mensagens do transporte podem ser entregues mais de uma vez e, para mensagens de estado, **muito depois** da primeira entrega (por exemplo, quando um consumidor reconstrói seu estado). Por isso a correção não depende de lembrar todas as mensagens já vistas.

| Mensagem | Regra semântica de idempotência |
|---|---|
| `requested` | Identidade da Operation (`operationId`), derivada da chave de idempotência do cliente no escopo do solicitante e do tipo de recurso, ou aleatória sem chave. O prazo é a retenção da Operation |
| `observed` | Monotonia de `observedAt`: observação não mais recente é descartada |
| `completed`, `failed` | Identidade da ação (`actionId`) registrada em `ActionResult`: o resultado de uma ação já registrada não é contado de novo |

A chave de idempotência é escopada ao solicitante: chaves iguais de solicitantes diferentes são independentes, e um solicitante nunca recebe a Operation de outro. A chave em si não precisa ser guardada nem transportada: ela é consumida pela API na derivação do `operationId`.

A retenção da Operation é maior que o prazo máximo de reentrega do `requested`; a de `ActionResult`, maior que a retenção dos resultados no transporte.

# 13. Outbox

A publicação das mensagens registradas no outbox é feita por um **relay**, que é um componente de infraestrutura e não executa regra de negócio.

- a entrega é *pelo menos uma vez*: uma falha entre publicar e marcar como publicada resulta em republicação;
- a publicação é **sequencial**: a próxima mensagem só é publicada depois da confirmação do transporte para a anterior, e um erro interrompe o lote. Publicar várias mensagens em paralelo permitiria que uma mensagem antiga, repetida após um erro, fosse gravada depois de uma nova e passasse a ser o último estado retido;
- **uma única instância** do relay publica por vez cada outbox. Ao perder a garantia de exclusividade, a instância descarta o lote em memória e para de publicar imediatamente;
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
| Rejeição | Operation `rejected` com motivo; o Resource não muda |
| Remoção | `lifecycle = absent`, `phase = Deleting`; após a convergência (`presence = absent`), remoção física do registro |

Após a remoção física, o último `desired` (`lifecycle = absent`) permanece no transporte até a limpeza administrativa (`RESOURCE-CONTROL-LOOP.md`). O SSOT não depende dessa mensagem.

Operações concluídas têm retenção limitada. O que precisa ser mantido a longo prazo pertence ao registro de auditoria.

# 15. Leitura e Consistência

- a API lê o SSOT em **modo somente leitura**, por uma interface de leitura própria e versionada, e não pela estrutura de armazenamento, para expor o estado atual do recurso e das operações;
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
- após restauração a um ponto anterior, aplica-se o procedimento de recuperação abaixo **antes** de liberar o Manager e o relay.

## 18.1 Recuperação após restauração

Restaurar o SSOT a um ponto anterior faz `desiredGeneration` voltar ao valor daquele ponto, enquanto o transporte retém `desired` publicados depois dele. Sem tratamento, uma nova alteração reutilizaria uma geração já publicada com outro conteúdo (invariante 10), e mensagens já publicadas voltariam a ficar pendentes no outbox e poderiam substituir o último estado retido por um anterior.

O procedimento é executado por infraestrutura, com o Manager e o relay parados:

1. descartar as mensagens pendentes do outbox: elas são anteriores ao ponto restaurado e podem já ter sido publicadas;
2. para cada recurso do SSOT, ler o último `desired` retido no transporte;
3. se o transporte não tiver `desired` do recurso, ou tiver geração menor, registrar no outbox o `desired` do SSOT com a geração do SSOT;
4. se o transporte tiver a mesma geração e o mesmo conteúdo, não fazer nada;
5. se o transporte tiver geração maior, ou a mesma geração com conteúdo diferente, gravar `desiredGeneration` como a geração do transporte mais um e registrar no outbox o `desired` do SSOT com essa geração;
6. listar, sem alterar, os recursos que existem no transporte e não existem no SSOT (criados depois do ponto restaurado). A decisão de recriar o registro ou publicar a remoção é do operador, porque é destrutiva;
7. registrar o relatório da recuperação e só então liberar o Manager e o relay.

O SSOT restaurado é a intenção vigente. Pedidos aceitos depois do ponto restaurado são perdidos, e suas Operations deixam de existir; essa perda é limitada pelo objetivo de ponto de recuperação do ambiente. Mensagens `updated` desse intervalo não são republicadas.

O procedimento é idempotente: repeti-lo sobre o mesmo estado não altera mais nada. Ele faz parte do teste periódico de restauração.

# 19. Observabilidade

Devem ser observáveis, sem expor dados sensíveis:

- idade da mensagem mais antiga não publicada no outbox;
- tamanho do outbox, de `ActionResult` e das Operations;
- Operations `rejected` por motivo e reusos de chave de idempotência com outro conteúdo;
- tempo de espera pelo acesso exclusivo ao registro e repetições da unidade atômica;
- latência e falhas de gravação;
- quantidade de recursos por `phase`;
- recursos em `Failed` e com `reconciliation = suspended`;
- tempo desde a última observação por tipo de recurso (`observedAt`).

# 20. Anti-Padrões

- escrever no SSOT por um componente que não seja o Manager;
- gravar a alteração e publicar a mensagem em unidades separadas;
- confirmar a mensagem ao transporte antes da gravação durável;
- ler o estado do recurso e gravá-lo sem acesso exclusivo ao registro;
- contar um resultado sem registrar o seu `actionId`, ou contá-lo contra uma geração diferente da sua;
- escopar a chave de idempotência apenas ao tipo de recurso, sem o solicitante;
- publicar o outbox em paralelo ou por mais de uma instância ao mesmo tempo;
- liberar o Manager após uma restauração sem o procedimento de recuperação;
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
- [ ] Toda unidade começa com acesso exclusivo ao registro do recurso?
- [ ] Rejeições são registradas na Operation com motivo?
- [ ] Toda gravação que gera mensagem registra o outbox na mesma unidade?
- [ ] A ordem por recurso é preservada na publicação?
- [ ] A idempotência de `requested`, `observed` e `completed`/`failed` é semântica, com `operationId` derivado da chave escopada ao solicitante e `ActionResult`?
- [ ] `desiredGeneration` só muda quando a especificação muda?
- [ ] A atualização informa e confere a `resourceVersion`?
- [ ] O dicionário de dados está completo, com sensibilidade e escritor?
- [ ] O que é guardado e o que não é está definido?
- [ ] Os privilégios são mínimos e por tipo de recurso?
- [ ] A estrutura é gerada a partir de um modelo, e a migração segue o `SCHEMA.md`?
- [ ] Existe cópia de segurança com recuperação a um ponto no tempo e teste de restauração, incluindo o procedimento de recuperação?
- [ ] Os sinais de observabilidade estão disponíveis?

# 22. Critérios de Sucesso

O SSOT está adequado quando:

- uma falha entre gravar e publicar não perde nem duplica de forma nociva uma mensagem;
- duas atualizações concorrentes nunca se sobrescrevem em silêncio, sejam pedidos ou mensagens internas;
- repetir qualquer mensagem consumida não altera o resultado;
- o modelo é compreensível sem conhecer a tecnologia de armazenamento;
- a tecnologia de armazenamento pode ser trocada sem alterar este documento;
- o estado pode ser recuperado a um ponto no tempo conhecido sem reutilizar uma geração já publicada.

# 23. Referências

- [MESSAGING.md](MESSAGING.md): semântica das mensagens e do envelope.
- [SCHEMA.md](SCHEMA.md): contratos formais, versionamento e classificação.
- [RESOURCE-CONTROL-LOOP.md](RESOURCE-CONTROL-LOOP.md): padrão de convergência.
- [RESOURCE-CONTROL-SECURITY.md](RESOURCE-CONTROL-SECURITY.md): segurança do loop.
- [POSTGRESQL.md](POSTGRESQL.md): implementação de referência do armazenamento.

# 24. Fonte de Verdade

Este documento é a fonte de verdade do **modelo e das garantias de gravação do SSOT**. A implementação em uma tecnologia específica adapta-se a ele, e uma limitação da tecnologia não altera o modelo: a adaptação permanece confinada ao documento de implementação.
