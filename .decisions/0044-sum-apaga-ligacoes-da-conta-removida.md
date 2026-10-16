# 0044 — O SUM apaga as ligações de uma conta removida

- **Data:** 2026-10-16
- **Status:** Aceita e implementada. Complementa a decisão 0040 (exclusão segura da conta).

## Contexto

A conta só é apagada sem serviço habilitado (decisão 0040), mas a ligação desabilitada do SUM continuava existindo, apontando para um dono que já não existe. O resíduo guarda só o `ownerAccountId` (sem dado pessoal), mas é o identificador de uma pessoa apagada.

## Decisão

- **O SUM Manager consome o `updated` de `core.account` com `removed: true`** (Stream `UPDATED`, filtro `manager.updated.core.account.>`, consumer durável `sum-service-manager-account-removed`) e apaga as ligações do dono (`DELETE FROM sum.service WHERE owner_account_id = ...`).
- **Cada módulo apaga o que é seu:** o `core` não escreve no SSOT do SUM. Sem rota, role ou permissão novas (o Manager já tinha `DELETE` em `sum.service`).
- **Idempotente:** repetir a mensagem não tem efeito; um `updated` comum da conta é confirmado e ignorado; mensagem fora do contrato é retirada do fluxo (`term`).
- **O histórico de Operations fica**, como nos demais módulos (a Account mantém o dela depois de removida). O outbox segue com o Publisher.

## Justificativa

- **Segurança:** nenhum identificador de pessoa apagada sobra no SSOT do SUM.
- **Simplicidade:** um consumer e uma instrução SQL, sem estado novo.
- **Robustez:** a fronteira entre módulos é preservada; a operação é idempotente e reentregável.

## Consequências

- O Stream `UPDATED` retém 24 h. Se o Manager do SUM ficar parado por mais que isso depois de uma remoção, a ligação órfã não é apagada sozinha; o `smarkee-dev-cleanup` cobre o dev, e a produção pede uma rotina de reconciliação (pendência).
- O consumer novo é declarado pelo `sum-service-consumer`, e a jornada e2e confere que as ligações somem junto com a conta.
