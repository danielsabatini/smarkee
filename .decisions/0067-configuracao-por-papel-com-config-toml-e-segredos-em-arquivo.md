# 0067 — Configuração por papel: CLI, ambiente, `config.toml`, segredos em arquivo e default

- **Data:** 2026-10-20
- **Status:** Aceita e implementada. Estende a 0063 (classe `BaseSettings` por papel) e a 0065 (nomes `<MÓDULO>_<TIPO>_<PAPEL>_`). Não contradiz o §2 do `AGENTS.md`.

## Contexto

Cada um dos 18 papéis (3 features × 6) já tinha uma `BaseSettings` com prefixo único, mas só lia ambiente e default. Os defaults carregavam hosts da rede interna do compose (`*.smarkee.internal`) e o domínio de dev (`ipm-dev.smarkee.com.br`), o que misturava o código com o ambiente. Não havia arquivo de configuração nem leitura de segredos montados, e a linha de comando não existia.

## Decisão

Precedência, da maior para a menor: **CLI → ambiente → `config.toml` → arquivos de segredo → default do código**. A ordem de `.env` ficou de fora (decisão do projeto: o ambiente do contêiner é a fonte).

- **Classe base `RoleSettings`** (`common/settings.py`, do template): define `settings_customise_sources`. Cada papel apenas herda dela; a tabela do `config.toml` e o prefixo vêm do `role_config("<papel>")`.
- **`config.toml`**: tabelas `[tool.<módulo>.<tipo>.<papel>.<seção>]`, uma por papel, no caminho de `SMARKEE_CONFIG_PATH` (padrão `config.toml`). Arquivo ou tabela ausente equivale a vazio. Campo desconhecido continua rejeitado (`extra="forbid"`). Nunca tem segredo.
- **Segredos em arquivo**: diretório `SMARKEE_SECRETS_DIR` (padrão `/run/secrets`), um arquivo por variável completa (por exemplo `CORE_ACCOUNT_EXECUTOR_MESSAGING_PASSWORD`). O `SecretsSettingsSource` da biblioteca não resolve seções aninhadas com `env_nested_max_split`, por isso há a fonte `SecretFilesSource`. Diretório ausente equivale a nenhum segredo (em dev eles vêm do ambiente). O ambiente vence o arquivo.
- **CLI só no entrypoint**: `start_role(..., cli_args=sys.argv[1:])` chama `load_settings`, que usa `CliApp.run`. Nunca `cli_parse_args` na classe (quebraria o pytest: `unrecognized arguments`). Sem argumentos, a linha de comando não é lida. **Segredo na linha de comando é recusado** (aparece em `ps`): `load_settings` sai com erro se um argumento citar `password`.
- **Defaults no código**: `localhost`, portas e timeouts padrão. **Conexão e credencial nunca têm default no código**: `database.host`, `.port`, `.name`, `.user`, `.password` e `messaging.url`, `.user`, `.password` valem `None` e são obrigatórios em `missing_required`; `messaging.connect` recusa `url` ausente com erro explícito, em vez de adivinhar um endereço. O banco e o broker podem ser outros em cada ambiente (ou em cada papel), então o endereço é configuração. Para rodar com `uv run` no host, contra as portas publicadas pelo Docker, não há segundo arquivo: o `.env` é carregado por `uv run --env-file .env ...` (ou as variáveis são exportadas ou passadas na linha), e o ambiente vence o `config.toml`. Exemplo: `CORE_ACCOUNT_RECEIVER_DATABASE_HOST=localhost`, `..._DATABASE_PORT=5432`, `..._MESSAGING_URL=nats://localhost:4222`.

O usuário e a senha seguem a mesma regra: `database.user`, `database.password`, `messaging.user` e `messaging.password` valem `None` e são obrigatórios em `missing_required`. O usuário não é segredo e fica no `config.toml` da feature, por papel (por exemplo `user = "core_account_receiver_login"` em `[tool.core.account.receiver.database]`); o ambiente continua podendo sobrescrevê-lo. A senha vem do ambiente ou de arquivo. Os valores do ambiente de dev (hosts internos, domínio do provedor de identidade) ficam no `config.toml` de cada feature, montado em `/etc/smarkee/config.toml` nos contêineres (`SMARKEE_CONFIG_PATH`).
- **Testes**: `tests/conftest.py` do template aponta `SMARKEE_CONFIG_PATH` e `SMARKEE_SECRETS_DIR` para um local inexistente, para a suíte não depender do `config.toml` nem dos segredos da máquina.

## Verificação

A configuração efetiva dos 18 papéis (dump do modelo, com valores fictícios nos obrigatórios) foi fotografada antes e depois: idêntica quando o `config.toml` da feature é aplicado.

## Fora desta decisão (pendências declaradas)

- As variáveis `CORE_IDENTITY_*` do compose não seguem `<MÓDULO>_<TIPO>_<PAPEL>_`; renomear é quebra de contrato (§10) e exige migração.
- Não há K8s nem Helm no repositório; o `config.toml` e os segredos montados já são o formato esperado para um ConfigMap e um Secret. Lacuna de dev, fecha antes do stg.
- Ainda não se monta `/run/secrets` com um arquivo por senha no compose de dev (as senhas seguem por variável); a leitura está pronta e testada.

## Consequências

O código fica sem ambiente embutido; o ambiente é configuração. Um papel novo herda `RoleSettings` e ganha as cinco fontes. O `sync.py` propaga o modelo; `config.toml` é semente (cada feature o ajusta).
