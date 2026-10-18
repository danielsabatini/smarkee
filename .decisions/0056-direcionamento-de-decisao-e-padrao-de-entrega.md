# 0056 — Direcionamento para tomada de decisão e padrão de entrega incremental

- **Data:** 2026-10-18
- **Status:** Aceita e aplicada ao `AGENTS.md`.
- **Origem:** pedido do responsável pelo projeto, a partir da figura de Henrik Kniberg sobre evolução de produto ("Not like this / Like this"): a evolução deve entregar valor em cada etapa, e não apenas aproximar o produto de sua versão final desejada.

## Contexto

O `AGENTS.md` tinha três listas de prioridade que se sobrepunham: o §2 (segurança, simplicidade, robustez, resiliência), o §5 (corretude, clareza, simplicidade, robustez, resiliência, performance, otimização) e o §34 (oito critérios de desempate, com a simplicidade na 3ª e na 8ª posição). Robustez e resiliência não tinham definição. Não havia regra sobre **em que pedaços** entregar, e nada dizia que uma decisão registrada não pode contrariar as regras gerais.

## Decisão

- **O §2 vira o "Direcionamento para Tomada de Decisão"**, com quatro partes: os pilares **segurança → simplicidade → robustez → resiliência**, cada um definido (§2.1); o **padrão de entrega** com valor em cada etapa (§2.2); a regra de que os pilares são o **piso de cada etapa** e o padrão nunca autoriza adiar um pilar (§2.3); e a **precedência**: nenhuma decisão em `.decisions/`, agent, skill ou tarefa o sobrepõe (§2.4).
- **§5 e §34 foram enxugados** e passam a apontar para o §2, sem listas próprias. O §40 perdeu as duas máximas que repetiam o §2.1. A numeração foi mantida, então as referências existentes (§16.1, §21, §24.x e outras) continuam válidas.
- **§1.1, §36.1 e §24.2** receberam uma frase cada: decisões não são nível de instrução e não sobrepõem o `AGENTS.md`; toda decisão segue o §2; a exceção de versão de API não é exceção ao §2.
- O agent `messaging` deixou de ter lista própria de prioridade e passou a seguir o §2 (AGENTS §24.1).

## Justificativa

- **Segurança e simplicidade:** uma única fonte para a ordem de decisão, sem listas que se contradizem.
- **Padrão de entrega:** cada etapa que não serve por si é risco de ficar pela metade; perguntar "e se for a última?" força a menor etapa útil (o patinete).
- **Pilares como piso:** evita ler o padrão de entrega como licença para entregar algo inseguro agora e corrigir depois.

## Consequências

- Toda decisão e plano passam a declarar, por etapa, o valor se ela for a última e o que ficou de fora.
- Uma decisão futura que contrarie o §2 é inválida; para mudar o direcionamento, altera-se o `AGENTS.md`.
- As decisões anteriores a esta (0031, 0032, 0034, 0045, 0049) chamam o 4º pilar de "disponibilidade". Para o §2.1, o nome é **resiliência**, e é isso que elas devem ser lidas como. As decisões antigas não foram reescritas, por serem registro histórico.
