# 0072 — Toda alteração percorre o loop; a Operation conclui na observação da geração

- **Data:** 2026-10-20
- **Status:** Aceita e implementada em `ipm.organization` e `core.account`. Revisa a decisão 0043 no ponto "alterar só a proteção conclui na hora". Primeira aplicação da decisão 0071 (referência de mercado: Kubernetes).
- **Origem:** avaliação do responsável pelo projeto: "o sistema é totalmente baseado em reconciliação, e qualquer regra que diga diferente disso temos que rever".

## Contexto

A decisão 0043 fez a alteração só da proteção contra exclusão (`deletionProtection`, campo da plataforma, `x-managed: false`) concluir a Operation **na própria transação do `requested`**, sem passar pela fase `Reconciling` e antes de qualquer observação. Era um segundo modo de executar, diferente do de todo o resto.

Efeitos verificados:

- a Operation dizia "concluída" sem o loop ter confirmado a geração;
- a geração nova, publicada mesmo assim, atropelava uma reconciliação em andamento. Uma reprodução contra o SSOT real mostrou o `create` virar `failed` com o recurso `Ready`: o resultado da action antiga era ignorado (geração substituída), e o `observed` seguinte encerrava como `failed` a Operation de geração anterior;
- o `updated` não dizia a que geração se referia, e o consumidor não sabia se a alteração tinha terminado.

O documento do loop (§36) também dizia que `observedGeneration` não serve como prova de convergência, porque o provedor não conhece a geração.

## Referência (Kubernetes)

- toda alteração do `spec` incrementa `metadata.generation`;
- o controlador roda sempre o mesmo `Reconcile`: compara, age ou não age;
- quando termina, grava `status.observedGeneration` e as `conditions`. "Terminou" significa `observedGeneration == generation` com `Ready=True`;
- um campo que o sistema externo não tem segue o mesmo caminho: o `Reconcile` não encontra o que fazer e confirma a geração;
- o bloqueio de exclusão é verificado na hora, pelo próprio API server (finalizers ou política de admissão), a partir do que está gravado.

## Decisão

1. **Um único modo.** Toda alteração do `desired`, inclusive em campo da plataforma, percorre o loop. O Manager grava a nova geração, a fase vai para `Reconciling` (ou `Deleting`), a Operation fica `accepted` e o `desired` vai para o outbox. O Reconciler compara: emite `action` se houver divergência em campo gerenciado, senão não faz nada (noop). O Observer observa a nova geração, e o `observed` conclui a Operation.
2. **`observed_generation` no SSOT** (coluna nova): a última geração cuja convergência o Manager confirmou. Nula até a primeira confirmação, só cresce e nunca passa de `desired_generation` (`CHECK` no banco).
3. **A confirmação exige uma observação posterior à geração.** O Observer informa no `observedGeneration` do envelope (campo que já existia no contrato) a geração que conhecia **antes** de ler o provedor. O Manager só confirma a geração vigente quando o conteúdo converge **e** o `observedGeneration` da observação é igual a ela. Uma leitura anterior à geração não a confirma, mesmo com o conteúdo igual: é o caso de uma alteração só em campo da plataforma.
4. **O `updated` leva `desiredGeneration` e `observedGeneration`** (campos opcionais e aditivos em `schemas/common/updated.v1.schema.json`). Iguais, com `phase` `Ready`: a última alteração terminou. `observedGeneration` menor: em andamento. Quem garante o par é o Manager: ele é o único que grava o SSOT e o único emissor do `updated`, e grava os dois na mesma transação, com a linha bloqueada. O Publisher não altera o conteúdo.
5. **Pedido sem geração nova** (nada mudou, ou só a `reconciliation` do operador): a Operation acompanha a geração vigente. Fica `completed` na hora se ela já estiver confirmada; senão fica `accepted` e conclui com a confirmação.
6. **Inalterado:** a verificação da proteção no `delete` continua na hora, no Receiver (`409 DeletionProtected`) e no Manager (`rejected/protected`), a partir do `desired`, como a admissão do Kubernetes. Nesta decisão, `deletionProtection` continuava `x-managed: false`; a decisão 0074 o tornou gerenciado, gravado como metadado no provedor.

## Divergências em relação ao Kubernetes (§2.7)

- **Quem confirma a geração** é o Manager, a partir do `observed` do Observer, e não o próprio controlador que age. O loop do projeto separa observar, decidir e executar (`RESOURCE-CONTROL-LOOP.md`).
- **A Operation** (um registro por pedido) não existe no Kubernetes. Uma Operation substituída por uma geração nova antes de convergir continua `failed` (`SSOT.md` §10.2). Alinhar isso (por exemplo, com um status `superseded`) fica para uma decisão própria.

## Justificativa

- **Segurança:** a proteção continua verificada na hora no `delete`. Nada passa a ser aceito antes de ser confirmado.
- **Simplicidade:** um caminho único, sem caso especial no Manager. O `managed_changed` foi removido das políticas.
- **Robustez:** a Operation só conclui com evidência (observação posterior à geração), e o par de gerações tem invariante no banco.
- **Explícito (§3):** o `updated` diz qual geração terminou.

## Consequências

- **Contrato (aditivo):** `desiredGeneration` e `observedGeneration` no `updated`; o Observer passa a preencher o `observedGeneration` do envelope `observed`.
- **Migrações:** `ipm/organization` `0004` e `core/account` `0008` (coluna, `CHECK` e preenchimento dos registros `Ready`).
- **Comportamento:** `protect`/`unprotect` e o `PATCH` da Account deixam de concluir na hora: concluem quando o Observer confirma a geração (normalmente em segundos, porque ele observa a cada nova geração). O `--wait` da CLI já espera a Operation `completed` e não mudou. Alterar a proteção de um recurso suspenso (`Failed`) volta a reconciliá-lo, como qualquer nova geração (`SSOT.md` §10.4).
- **Implantação:** Observer e Manager vão juntos (mesma imagem por feature, decisão 0063). Um Observer antigo, sem `observedGeneration`, não confirma gerações: as Operations ficam em andamento até ele ser trocado.
- **Fora desta etapa:** expor `observedGeneration` na view do Receiver (`GET`) e aplicar o mesmo ao `sum/service`, que tem outro Manager.
- **Próximo passo, feito na decisão 0074:** `deletionProtection` gravado como metadado no Zitadel, para que o provedor mostre a particularidade e o loop corrija o drift. Esta decisão continua valendo: a 0074 só acrescenta um campo gerenciado.
