# 0071 — Referência de mercado: seguir o que já é reconhecido e funciona

- **Data:** 2026-10-20
- **Status:** Aceita e aplicada ao `AGENTS.md` (§2.7, citado no §34 e no §40). Complementa as decisões 0056, 0057 e 0058.
- **Origem:** pedido do responsável pelo projeto: "caso existam dúvidas, seguir pelo caminho de soluções já reconhecidas e funcionais do mercado, como o Kubernetes".

## Contexto

Na revisão da proteção contra exclusão (decisão 0072), o projeto tinha dois modos de concluir uma alteração: pelo loop, para os campos gerenciados no provedor, e "na hora", para os campos da plataforma. O segundo modo foi uma invenção local. A comparação com o Kubernetes (`metadata.generation`, `status.observedGeneration` e `conditions`) mostrou que ele tem **um único modo**: toda alteração do `spec` passa pelo mesmo `Reconcile`, que age ou não, e termina quando o controlador confirma a geração.

## Decisão

- **§2.7 "Referência de mercado"** no `AGENTS.md`: na dúvida sobre **como** resolver um problema, siga o caminho de uma solução reconhecida e comprovada em produção para o mesmo problema, em vez de inventar um modelo próprio.
- **Exemplo declarado:** para controle de recursos por reconciliação, a referência é o Kubernetes.
- **Regras:**
  - comprovar como a referência resolve o problema na documentação oficial (§9);
  - adotar o **modelo** (conceitos, nomes, semântica, invariantes), e não necessariamente o produto (§21);
  - declarar na decisão onde e por que o projeto diverge da referência;
  - a referência **não sobrepõe os pilares** (§2.1);
  - preferir um único modo de executar o que é do mesmo tipo.
- **§34 e §40:** a regra de conflito e a regra final passam a citar a referência de mercado como critério de desempate.

## Justificativa

- **Robustez:** um modelo usado em produção em larga escala já teve os casos de borda descobertos (gerações, observações antigas, conclusão de alterações).
- **Simplicidade:** um modo único de executar reduz casos especiais, e nomes conhecidos (como `observedGeneration`) dispensam explicação.
- **Explícito (§3):** divergir passa a ser uma escolha declarada, e não um acidente.

## Consequências

- Decisões de modelagem passam a trazer a referência usada e as divergências em relação a ela.
- A primeira aplicação é a decisão 0072.
