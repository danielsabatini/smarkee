---
name: Feature Registers
description: Guia de procedimentos para registrar uma feature nova nos arquivos compartilhados fora da pasta da feature (gateway, telemetria, banco, identidade, CLI, scripts de dev). Use depois de `sync.py --new`, ao fechar os passos 5 a 9 do roteiro, ou para auditar se uma feature foi registrada por inteiro.
---

# Feature Registers

## 1. Papel desta skill

Esta skill é um **guia de procedimentos** que lista, confere e aplica os registros de uma feature **fora** de `features/<módulo>/<tipo>/`. O `sync.py --new` cria só a pasta da feature (decisão 0064); estes registros são alterações em arquivos compartilhados e ficam com quem cria a feature.

```text
O que registrar e onde → docs/FEATURE-BOOTSTRAP.md, passos 5 a 9 (fonte da verdade)
Fluxo completo         → skill feature-bootstrap
Banco / broker         → skills postgresql e nats
```

Não repita o conteúdo do roteiro: use esta skill como lista de conferência e comandos de busca.

---

## 2. Princípios

* **Menor mudança** (`AGENTS.md` §7, §30): acrescente a entrada da feature ao arquivo existente; não reorganize nem renomeie o que já está lá.
* **Liste cada arquivo compartilhado tocado** no resultado, porque são arquivos de outras features e da plataforma.
* **Nada destrutivo** (§20): não aplique migração em banco existente, não recrie volume, não suba a stack sem o responsável saber.
* **Segurança** (§4): senhas sem default e nenhum segredo real em arquivo versionado.

---

## 3. Registros

Confira cada linha. Se a feature `core/account` já aparece num arquivo, a feature nova precisa de uma entrada equivalente (use-a como referência de forma).

| Registro | Arquivo | Quando |
|---|---|---|
| Papéis de banco do módulo | `infrastructure/dev/database/bootstrap/<módulo>.sql` | módulo novo: arquivo novo; tipo novo: acrescenta o papel do tipo |
| Rota da API | `infrastructure/dev/gateway/bootstrap/adc.yaml` | sempre, uma por tipo |
| Audience da rota | `infrastructure/dev/gateway/.env.example` e `compose.yaml` do gateway | sempre: `SMARKEE_GATEWAY_AUTH_AUDIENCE_<MÓDULO>_<TIPO>` |
| Telemetria | `infrastructure/dev/telemetry-router/config.yaml` | sempre: log, trace e exportador `<módulo>-<tipo>-telemeter` |
| Conformidade de identidade | `infrastructure/dev/identity/conformance/tests/test_structure.py` | sempre: `ENV_FILES` e `EXPECTED_AUDIENCE`; com Observer e Executor com identidade, `EXPECTED_REGISTER` e `EXPECTED_PROJECT_IDS` |
| Projeto de roles e contas de serviço | provedor de identidade (Zitadel) | módulo novo: projeto novo; contas do Observer e do Executor |
| Backup | `scripts/dev/backup/src/smarkee_dev_backup/model.py` | sempre: `ENV_FILES` e `FEATURE_DIRECTORIES` |
| Limpeza de testes | `scripts/dev/cleanup/src/smarkee_dev_cleanup/model.py` | se o recurso criar dados em teste: `Kind` e padrões de nome. A limpeza pelo loop espera `observed_generation = desired_generation` na tabela do tipo (decisão 0072) |
| Perfis do template | `templates/feature/sync.py` (`PROFILES`) | feita no passo 3 (skill `feature-bootstrap`): os perfis do modelo (`receiver-http`, `manager-handlers`, `loop-engines`, `identity-metadata`); aqui só confira que a feature está nas tuplas certas |
| CLI `sk` | `clients/cli/src/sk/features/<módulo>/` e `sk/commands/` | se o recurso tiver comando; textos da CLI em inglês (decisão 0035) |

O `.gitignore` do telemeter e o teste de pacotes de `schemas/tests/test_feature_template.py` **não** precisam de edição: valem para qualquer feature.

---

## 4. Procedimento

1. Escolha uma feature de referência e liste onde ela está registrada:

   ```bash
   grep -rln "core[._-]account\|CORE_ACCOUNT\|core/account" \
     infrastructure scripts clients templates schemas docs \
     --include='*.py' --include='*.yaml' --include='*.yml' --include='*.sql' --include='*.example' --include='*.toml' \
     | grep -v '/\.venv/\|/__pycache__/'
   ```

2. Para cada arquivo da tabela da seção 3, acrescente a entrada da feature nova, na forma da de referência.
3. Repita a busca com `<módulo>[._-]<tipo>` e compare as duas listas: toda linha da referência deve ter correspondente na feature nova, salvo o que o roteiro marca como específico do recurso.
4. Verifique cada área alterada:

   ```bash
   cd scripts/dev/backup && uv run pytest -q
   cd infrastructure/dev/identity/conformance && uv run pytest -q
   cd schemas && uv run pytest -q
   ```

   Rode também a suíte de qualquer outro projeto cujo arquivo você tenha alterado.

---

## 5. Resultado

Devolva a lista de arquivos compartilhados tocados, o resultado de cada verificação e o que **não** foi verificado: rotas do gateway, telemetria e identidade só se provam com a stack de dev no ar. Declare a diferença como lacuna de dev em `docs/IMPLEMENTATION-STATUS.md` (§2.5).

Se o roteiro não listar um registro que a feature exigiu, acrescente-o a `docs/FEATURE-BOOTSTRAP.md` (a fonte da verdade) e a esta tabela.
