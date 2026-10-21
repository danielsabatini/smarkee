# 0079 — Catálogo do SUM com uma fonte só, e rollout quando ele muda

- **Data:** 2026-10-21
- **Status:** Aceita e implementada em dev (etapa 2 do plano que veio do incidente da decisão 0078). Revisa a decisão 0033 no ponto "roles copiadas do catálogo ao ligar".
- **Origem:** incidente de 2026-10-21. A mesma variável (`SUM_SERVICE_MANAGER_CATALOG_ROLES`) alimentava três cópias do catálogo (Manager, Observer e Executor). Só o Manager foi recriado depois da mudança, e o recurso ficou uma hora sem convergir. Além disso, quem ligou o serviço antes da mudança só recebia as roles novas desligando e ligando de novo.

## Decisão

1. **O catálogo existe só no Manager.** O `desired` passa a levar, além de `serviceRoles` (o que o usuário deve ter), o campo aditivo **`managedRoles`**: as roles que a ligação controla, ou seja, as do catálogo mais as que saíram dele depois. O Observer e o Executor leem as roles só do `desired`; a seção `catalog` e a variável deles deixam de existir.
   - **Observer:** observa as roles do usuário dentro de `managedRoles`.
   - **Executor:** com a ligação ativa, concede `serviceRoles` e revoga `managedRoles − serviceRoles`; com ela desligada, revoga `managedRoles`.
   - **Reconciler:** a ligação ativa diverge se falta uma role de `serviceRoles` ou se sobra uma de `managedRoles − serviceRoles`.
2. **Rollout do catálogo** (modelo do rollout do Deployment do Kubernetes quando o template muda). Na partida, antes dos consumers, o Manager compara cada ligação com o que o catálogo de agora produz. Se o `desired` muda, grava uma geração nova, uma Operation `update` de `system:catalog` e o `desired` no outbox, e o loop aplica a mudança, inclusive para quem ligou antes. Uma role que sai do catálogo continua em `managedRoles` e é revogada. Cada ligação é uma unidade atômica, com a linha bloqueada, e repetir não grava nada. Um serviço que saiu do catálogo não é alterado: quem decide é o operador.
3. **Migração aditiva `0005`:** a Operation do SUM aceita o tipo `update`.

## Compatibilidade

- `managedRoles` é opcional no schema. Um `desired` antigo (sem o campo) é lido como `managedRoles = serviceRoles`. O rollout acrescenta o campo a todas as ligações, ligadas e desligadas, na primeira partida do Manager com esta versão.
- A configuração `SUM_SERVICE_OBSERVER_CATALOG_ROLES` e `SUM_SERVICE_EXECUTOR_CATALOG_ROLES` sai do `compose.yaml` (contrato de configuração: só o Manager a recebe).

## Verificação (dev, 2026-10-21)

- A ligação real do dev, gravada sem `managedRoles`, ganhou a geração 2 com uma Operation `update` de `system:catalog`, voltou a `Ready` com as 11 roles, e a Operation foi `completed`.
- Os logs de partida mostram que o Observer e o Executor não têm mais a seção `catalog`.
- O teste de integração do rollout passa contra o SSOT real (geração nova, Operation do sistema, outbox, idempotência), além dos testes unitários das regras e dos papéis.

## Consequências

- **Trocar o catálogo:** basta editar o `.env` e rodar `docker compose up -d` na pasta da feature (`features/sum/service/README.md`). As roles novas precisam existir antes no projeto de roles e no Grant para a `register`.
- **Fica para a etapa 3:** o Manager do SUM entrar no modelo do loop (`observed_generation`, condition `Progressing`).
