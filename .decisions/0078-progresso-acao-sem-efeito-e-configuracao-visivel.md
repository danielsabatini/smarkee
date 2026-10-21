# 0078 — Prazo de progresso, ação sem efeito e configuração visível

- **Data:** 2026-10-21
- **Status:** Aceita e implementada nas quatro features. No `sum/service`, por enquanto só a parte do Reconciler e da configuração: o Manager do SUM não usa o template, e a condition `Progressing` chega a ele quando ele entrar no modelo do loop (etapa 3 do plano, feita pela decisão 0080).
- **Origem:** incidente de 2026-10-21. Depois de uma mudança no catálogo do SUM, só o contêiner do Manager foi recriado. O Observer seguiu com o catálogo antigo e nunca via as roles novas. O Reconciler mandava um `update` a cada 2 s, o Executor respondia `completed` sem nada a fazer, e o recurso ficou uma hora em `Reconciling`. Foram 1.807 ações sem nenhum `WARN`, e a causa não aparecia em nenhum log.

## Contexto

- O loop só reagia a `failed`: uma ação que sempre conclui sem fazer o recurso convergir não tinha freio nem aviso.
- O Kubernetes trata o mesmo problema no Deployment, com a condition `Progressing` e o `progressDeadlineSeconds`. Passado o prazo sem progresso, ela fica `False` com `ProgressDeadlineExceeded`, e o controlador segue tentando com *backoff*, sem parar (referência de mercado, decisão 0071).
- O nível de log era fixo em `INFO`, e as bibliotecas (por exemplo, o `httpx`) registravam cada chamada.

## Decisão

1. **Ação sem efeito (Reconciler, todas as features).** Uma `action` que termina `completed` e cuja observação causada ainda diverge conta como sem efeito (`ineffective_actions`). Ela entra no mesmo backoff exponencial das falhas e gera o aviso `action had no effect`. O contador zera quando o recurso converge ou numa geração nova. As decisões passam a registrar o motivo, a geração e os **nomes** dos campos divergentes (`smarkee.drift.fields`), nunca os valores.
2. **Prazo de progresso (Manager, template).** Novo parâmetro de contrato `progressDeadline` (`PT5M`) e a condition `Progressing`:
   - `True`/`Reconciling` desde a primeira observação da geração atual que não converge;
   - `True`/`Converged` quando converge;
   - `False`/`ProgressDeadlineExceeded` quando o prazo passa sem convergir. Nesse caso a fase vai para `Failed` e sai o aviso `progress deadline exceeded`, uma vez só.

   Uma geração nova reinicia o prazo. **O loop não é suspenso**, como no Kubernetes: segue no ritmo do backoff e volta a `Ready` sozinho se a causa sumir. Quem suspende continua sendo só o `failureLimit`.
3. **Nível de log configurável.** A seção `log` entra na base `RoleSettings` (template), com `level` (padrão `INFO`) e `dependencies_level` (padrão `WARNING`, para as bibliotecas). Segue o padrão de todo campo de configuração (decisão 0067): `<FEATURE>_<PAPEL>_LOG_LEVEL`, o `config.toml` ou a linha de comando. Vale para os 24 processos.
4. **Configuração visível.** Na partida, cada papel registra `configuration loaded` com o resumo (SHA-256, 12 caracteres) de cada seção da configuração, com os segredos mascarados (`smarkee.config.digest`). A mesma seção em papéis diferentes da mesma feature (por exemplo, o `catalog` do SUM) com resumos diferentes mostra a divergência numa linha.

## Verificação (dev, 2026-10-21)

O incidente foi reproduzido com o Observer do SUM rodando com o catálogo antigo:
- foram 3 ações em 4 minutos, com intervalo crescente, contra uma a cada 2 s antes;
- cada ação gerou o aviso com `smarkee.drift.fields = ["serviceRoles"]`;
- o log de partida mostrou `catalog` diferente entre o Manager (`eab8eed272f9`) e o Observer (`176a971feefb`).

Os testes unitários cobrem a condition `Progressing`, o backoff e o nível de log, e os e2e da Organization e da Account passam.

## Consequências

- **Contrato:** `x-resourceParameters.progressDeadline` nos `desired` dos quatro tipos (aditivo). Na lista de `conditions`, `Progressing` aparece ao lado de `Ready`.
- **Configuração:** `<FEATURE>_<MANAGER>_LOOP_PROGRESS_DEADLINE_SECONDS` (padrão 300) nas três features do template e `<FEATURE>_<PAPEL>_LOG_LEVEL` e `_LOG_DEPENDENCIES_LEVEL` em todos os papéis (`docs/CONFIGURATION.md` de cada feature, gerado).
- **Fica para as próximas etapas do plano:** o catálogo do SUM com uma fonte só (etapa 2), a `Progressing` no Manager do SUM (etapa 3), a Operation virar `failed` no prazo esgotado (etapa 4) e as métricas derivadas dos logs, quando a lacuna de métricas for atacada.
