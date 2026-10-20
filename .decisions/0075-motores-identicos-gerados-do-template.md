# 0075 — Motores idênticos gerados do template; regra do tipo continua na feature

- **Data:** 2026-10-20
- **Status:** Aceita e implementada. Fecha a questão que a decisão 0064 deixou em aberto ("gerar os motores ou extrair uma biblioteca comum, antes da quarta feature") e estende a 0064 e a 0065.
- **Origem:** pedido do responsável pelo projeto para deixar o agent `feature` e as suas skills prontos para criar uma feature nova; a pré-condição do agent exigia esta decisão a partir da terceira feature.

## Contexto

A 0064 levou ao template o que era idêntico entre as features e deixou os motores dos papéis para depois, à espera de evidência. A evidência veio do trabalho de 2026-10-20:

- **Medição** (`core/account` × `ipm/organization`, nomes normalizados, fora do template): idênticos o motor do Observer, o motor do Executor, a revalidação e os erros do Executor, a convergência e os erros do Manager, e os erros, as linhas das views e os pedidos do Receiver. Entre 95% e 99%: o motor do Reconciler, os consumers e o store do Manager, o handler de `requested` e o transporte do Executor, com diferenças que são regra do tipo (cota por dono, valor único, nomes de tabela).
- **Custo da cópia:** a regra do `observedGeneration` (decisão 0072) mora no motor do Observer. Copiado à mão, esquecê-la passa pelos testes unitários e só aparece no e2e, com toda Operation parada em `accepted`.

## Decisão

- **Gerar, não extrair.** O que é idêntico entre as features vai para o template, como perfil opcional, e é gravado em cada feature pelo `sync.py` (decisão 0064). **Não** se cria biblioteca comum de runtime: cada feature continua com os seus arquivos, sem dependência entre features, e o contexto de build do Docker não muda (decisões 0046 e 0063).
- **Critério:** um arquivo entra num perfil quando é idêntico em pelo menos duas features depois dos marcadores, e não tem regra do tipo. O que diferir por regra de negócio fica na feature, copiado do modelo.
- **Perfil novo `loop-engines`:** `observer/engine/observer.py`, `executor/engine/executor.py`, `executor/domain/revalidation.py`, `executor/domain/errors.py`, `manager/domain/convergence.py`, `manager/domain/errors.py` e o teste `tests/observer/unit/test_engine.py`, que cobre o envio do `observedGeneration`.
- **Perfil `receiver-http` ampliado:** `receiver/domain/errors.py`, `records.py` e `requests.py`.
- **Marcador novo `@@TYPE_CLASS@@`** (`Account`, `Organization`): o prefixo de classe do tipo, como em `AccountObserverSettings`.
- **Gancho em vez de exceção:** a única diferença do motor do Observer (o `organization_id` nos logs da Organization) virou a função `log_identifiers(resource_id)` em `observer/domain/observation.py`, de cada feature.
- **Feature nova:** se ela segue um modelo que declara os perfis, declara os mesmos perfis logo depois do `sync.py --new` e escreve os arquivos de contrato que cada perfil exige (`docs/FEATURE-BOOTSTRAP.md`, passo 3). O `pyright` mostra o que ainda falta. Uma feature cujo papel precise de um motor diferente não declara o perfil e registra a divergência.
- **Continuam na feature**, porque têm regra do tipo: o motor do Reconciler e a decisão dele, o Manager fora do perfil `manager-handlers` (store, `requested`, consumers, política), as `actions` e os drivers do provedor, a observação, os `settings.py` e `main.py`, o `app.py` do Receiver. Voltar a medir quando uma feature nova repetir algum deles.

## Justificativa

- **Robustez:** os invariantes do loop (geração confirmada, revalidação antes de agir, single-flight) passam a ter uma fonte só, com o teste junto.
- **Simplicidade:** o mecanismo já existe e é verificado (`sync.py --check` e o teste `schemas/tests/test_feature_template.py`); não entra dependência nem pacote novo.
- **Segurança:** cada feature segue com o próprio código e as próprias credenciais; nada passa a ser compartilhado em runtime.

## Consequências

- A pré-condição do agent `feature` ("decisão sobre os motores antes da quarta feature") está cumprida.
- Alterar um motor do perfil é alterar o template e rodar o `sync.py` e a suíte de cada feature (AGENTS §22).
- O `sum/service` não declara os perfis: o Manager e os motores dele têm outra forma.
