"""Gera `docs/CONFIGURATION.md` de uma feature a partir dos `settings.py` dos seus papéis.

Decisão 0064 (template) e 0067 (configuração). O guia lista a ordem de precedência, os campos de
cada papel (variável, flag, tipo, default, obrigatória) e um exemplo de execução por papel. Os
campos vêm dos próprios `Settings` (tipos, defaults, docstrings e `missing_required`), então o
guia não é escrito à mão (AGENTS §22).

Precisa do ambiente da feature (importa o pacote e o `pydantic`), então roda com `uv` dentro dela:

    cd features/<módulo>/<tipo>
    uv run python ../../../templates/feature/configuration_guide.py          # grava o guia
    uv run python ../../../templates/feature/configuration_guide.py --check  # falha se divergir

Papéis que ainda não existem na feature são ignorados, para o guia poder nascer junto com ela.
"""

import ast
import importlib
import inspect
import os
import sys
import textwrap
import tomllib
from collections.abc import Iterator
from contextlib import contextmanager
from itertools import pairwise
from pathlib import Path
from typing import Any

from pydantic_core import PydanticUndefined

ROLES = ("api", "receiver", "manager", "publisher", "reconciler", "observer", "executor")
GUIDE = Path("docs") / "CONFIGURATION.md"
HEADER = (
    "<!-- Gerado por templates/feature/configuration_guide.py a partir dos settings.py dos papéis. "
    "Não edite: altere o código e regenere. -->"
)

# Porta de saúde de cada papel no exemplo do host (o Receiver e a API usam a porta HTTP).
HOST_PORTS = {
    "manager": 8002,
    "publisher": 8003,
    "reconciler": 8004,
    "observer": 8005,
    "executor": 8006,
}
# Um campo de ajuste por papel no exemplo: o primeiro que o papel tiver.
TUNING_FLAGS = (
    ("loop", "failure_limit", "3"),
    ("loop", "reevaluation_interval_seconds", "10"),
    ("loop", "observation_interval_seconds", "60"),
    ("partition", "count", "4"),
)


@contextmanager
def clean_environment(prefix: str) -> Iterator[None]:
    """Remove do ambiente o que altera a configuração (variáveis da feature e `SMARKEE_*`).

    Assim a lista de obrigatórias não depende do `.env` nem do shell de quem gera o guia.
    """
    saved = {k: v for k, v in os.environ.items() if k.startswith((prefix, "SMARKEE_"))}
    for key in saved:
        del os.environ[key]
    os.environ["SMARKEE_CONFIG_PATH"] = "/nonexistent/config.toml"
    os.environ["SMARKEE_SECRETS_DIR"] = "/nonexistent/secrets"
    try:
        yield
    finally:
        os.environ.pop("SMARKEE_CONFIG_PATH", None)
        os.environ.pop("SMARKEE_SECRETS_DIR", None)
        os.environ.update(saved)


def field_docs(section: type) -> dict[str, str]:
    """Docstring de cada campo (a string logo abaixo da anotação), percorrendo as classes-base."""
    docs: dict[str, str] = {}
    for klass in section.__mro__:
        if klass.__module__.startswith("pydantic") or klass is object:
            continue
        try:
            tree = ast.parse(textwrap.dedent(inspect.getsource(klass)))
        except (OSError, TypeError):
            continue
        body = getattr(tree.body[0], "body", [])
        for current, following in pairwise(body):
            if (
                isinstance(current, ast.AnnAssign)
                and isinstance(current.target, ast.Name)
                and isinstance(following, ast.Expr)
                and isinstance(following.value, ast.Constant)
                and isinstance(following.value.value, str)
            ):
                docs.setdefault(current.target.id, " ".join(following.value.value.split()))
    return docs


def type_name(annotation: Any) -> str:
    text = str(annotation).replace("typing.", "").replace("pydantic.types.", "")
    return text.replace("<class '", "").replace("'>", "").replace("|", "\\|")


def default_text(info: Any, secret: bool) -> str:
    if secret or (info.default is PydanticUndefined and info.default_factory is None):
        return "—"
    value = info.get_default(call_default_factory=True)
    return "—" if value is None else f"`{value!r}`".replace("|", "\\|")


def role_settings_class(module: Any, base: type) -> type:
    return next(
        value
        for value in vars(module).values()
        if isinstance(value, type) and issubclass(value, base) and value is not base
    )


def render_role(
    names: dict[str, str],
    number: int,
    role: str,
    settings_class: type,
    module: Any,
    toml_table: dict[str, Any],
) -> list[str]:
    kebab = names["kebab"]
    prefix = str(settings_class.model_config["env_prefix"])  # type: ignore[attr-defined]
    missing = module.missing_required(settings_class())
    main_source = Path(module.__file__).with_name("main.py").read_text(encoding="utf-8")
    summary = " ".join((ast.get_docstring(ast.parse(main_source)) or "").split("\n\n")[0].split())
    sections: dict[str, Any] = {
        name: field.annotation
        for name, field in settings_class.model_fields.items()  # type: ignore[attr-defined]
    }
    out = [f"## {number}. `{kebab}-{role}`\n", f"{summary}\n"]
    out += [
        f"- **Prefixo das variáveis:** `{prefix}`",
        f"- **Tabela do `config.toml`:** `[tool.{names['module']}.{names['type']}.{role}.<seção>]`",
        f"- **Comando:** `{kebab}-{role}` (entrypoint `{names['package']}.{role}.main:main`)\n",
        "**Obrigatórias** (sem default; o serviço não sobe sem elas):\n",
    ]
    out += [f"- `{name}`" for name in missing] + [""]
    out += [
        "| Campo | Variável | Flag | Tipo | Default | Descrição |",
        "|---|---|---|---|---|---|",
    ]
    for section_name, section in sections.items():
        docs = field_docs(section)
        for field_name, info in section.model_fields.items():
            secret = "SecretStr" in str(info.annotation)
            variable = f"{prefix}{section_name}_{field_name}".upper()
            description = docs.get(field_name, "")
            if secret:
                description = f"{description} Só por ambiente ou arquivo de segredo.".strip()
            if variable in missing:
                description = f"Obrigatória. {description}".strip()
            flag = "_recusada_" if secret else f"`--{section_name}.{field_name}`"
            out.append(
                f"| `{section_name}.{field_name}` | `{variable}` | {flag} | "
                f"`{type_name(info.annotation)}` | {default_text(info, secret)} | {description} |"
            )
    out.append("")
    if toml_table:
        out += ["**Definido no `config.toml` de dev:**\n", "```toml"]
        blocks: list[str] = []
        for section_name, values in toml_table.items():
            lines = [f"[tool.{names['module']}.{names['type']}.{role}.{section_name}]"]
            lines += [f"{key} = {value!r}".replace("'", '"') for key, value in values.items()]
            blocks.append("\n".join(lines))
        out += ["\n\n".join(blocks), "```\n"]
    out += [f"**Executar** (de `features/{names['module']}/{names['type']}`):\n", "```bash"]
    out += [
        "# Contêiner (dev): sobe só este papel; usa config.toml, .env e /run/secrets",
        f"docker compose up -d {kebab}-{role}",
        f"docker compose logs -f {kebab}-{role}",
        "",
        "# Host, com o ambiente do .env; as flags sobrescrevem tudo (menos segredo)",
        f"uv run --env-file .env {kebab}-{role} \\",
    ]
    flags = [
        "--api.port 8001" if "api" in sections else f"--health.port {HOST_PORTS[role]}",
        *(["--database.host localhost"] if "database" in sections else []),
        "--messaging.url nats://localhost:4222",
        *(["--identity.base_url http://localhost:8080"] if "identity" in sections else []),
    ]
    for section_name, field_name, value in TUNING_FLAGS:
        if section_name in sections and field_name in sections[section_name].model_fields:
            flags.append(f"--{section_name}.{field_name} {value}")
            break
    out += [f"    {flag}" + (" \\" if i < len(flags) - 1 else "") for i, flag in enumerate(flags)]
    out += [
        "",
        "# Lista todas as flags aceitas pelo papel",
        f"uv run {kebab}-{role} --help",
        "```\n",
    ]
    return out


def render_guide(feature_dir: Path) -> str:
    """Texto do guia da feature em `feature_dir` (`features/<módulo>/<tipo>`)."""
    module_name, type_name_ = feature_dir.parent.name, feature_dir.name
    names = {
        "module": module_name,
        "type": type_name_,
        "package": f"{module_name}_{type_name_}",
        "kebab": f"{module_name}-{type_name_}",
        "upper": f"{module_name}_{type_name_}".upper(),
        "dotted": f"{module_name}.{type_name_}",
    }
    package, kebab, upper, dotted = (names[k] for k in ("package", "kebab", "upper", "dotted"))
    config_file = feature_dir / "config.toml"
    toml_all = (
        tomllib.loads(config_file.read_text(encoding="utf-8")) if config_file.exists() else {}
    )
    toml_tables: dict[str, Any] = toml_all.get("tool", {}).get(module_name, {}).get(type_name_, {})
    common = importlib.import_module(f"{package}.common.settings")

    body: list[str] = []
    numbered: list[str] = []
    with clean_environment(f"{upper}_"):
        for role in ROLES:
            try:
                module = importlib.import_module(f"{package}.{role}.settings")
            except ModuleNotFoundError as error:
                if error.name != f"{package}.{role}" and error.name != f"{package}.{role}.settings":
                    raise
                continue
            settings_class = role_settings_class(module, common.RoleSettings)
            body += render_role(
                names, 3 + len(numbered), role, settings_class, module, toml_tables.get(role, {})
            )
            numbered.append(role)
    if not body:
        raise SystemExit(f"nenhum papel encontrado em {package}")

    adr = "../../../../.decisions"
    head = [
        HEADER,
        f"# Configuração de {dotted}: guia de parâmetros\n",
        f"Referência de **todas** as configurações dos papéis de `{dotted}` (`{kebab}-<papel>`), "
        "na ordem de precedência, e de como executar cada um. Decisões: "
        f"[`0067`]({adr}/0067-configuracao-por-papel-com-config-toml-e-segredos-em-arquivo.md) "
        f"(configuração), [`0069`]({adr}/0069-prefixo-smarkee-nas-variaveis-de-infraestrutura.md) "
        f"(prefixo) e [`0070`]({adr}/0070-senhas-dos-servicos-como-arquivos-montados.md) "
        "(senhas como arquivos).\n",
        f"> Gerado dos `settings.py` de `src/{package}/<papel>/` e de `common/settings.py`. Para "
        f"atualizar: `cd features/{module_name}/{type_name_} && uv run python "
        "../../../templates/feature/configuration_guide.py`.\n",
        "## 1. Precedência\n",
        "Cada campo é resolvido pela **primeira** fonte que o informa, da maior para a menor "
        "prioridade:\n",
        "| # | Fonte | Como informar | Observações |",
        "|---|---|---|---|",
        "| 1 | **Linha de comando** | `--<seção>.<campo> <valor>` | Só no entrypoint do papel. "
        "**Segredo é recusado** (aparece em `ps`): qualquer argumento que cite `password` "
        "encerra o serviço. |",
        f"| 2 | **Variável de ambiente** | `{upper}_<PAPEL>_<SEÇÃO>_<CAMPO>` | "
        "Em dev vem do `.env` (`docker compose` ou `uv run --env-file .env`). |",
        f"| 3 | **`config.toml`** | tabela `[tool.{module_name}.{type_name_}.<papel>.<seção>]` | "
        "Caminho em `SMARKEE_CONFIG_PATH` (padrão `config.toml`). Arquivo ou tabela ausente "
        "equivale a vazio. **Nunca tem segredo.** |",
        "| 4 | **Arquivo de segredo** | `/run/secrets/<NOME-DA-VARIÁVEL>` | Diretório em "
        "`SMARKEE_SECRETS_DIR` (padrão `/run/secrets`). O nome do arquivo é o da variável "
        "completa. Em dev o compose monta as senhas aqui a partir do `.env`. |",
        "| 5 | **Default do código** | — | Só para o que não é credencial nem endereço de "
        "conexão. |\n",
        "Pontos que costumam surpreender:\n",
        "- O **ambiente vence o arquivo de segredo**. Uma variável `*_PASSWORD` definida no "
        "ambiente anula o segredo montado: os manifestos não devem defini-las.",
        "- **Sem default no código**: `database.host|port|name|user|password` e "
        "`messaging.url|user|password`, além do que cada papel marca como obrigatório. Faltando "
        "algum, o serviço sai com `missing required configuration` e lista as variáveis.",
        '- **Campo desconhecido** é rejeitado (`extra="forbid"`): variável, chave do '
        "`config.toml` ou flag com nome errado falha, em vez de ser ignorada.",
        "- O nome da variável separa só a **seção** do **campo**: `MESSAGING_URL` é "
        "`messaging.url`; `LOOP_REEVALUATION_INTERVAL_SECONDS` é "
        "`loop.reevaluation_interval_seconds`.",
        "- Valores compostos (listas e dicionários) vão como **JSON** na variável e na flag.\n",
        "### Variáveis de execução (não são de um papel)\n",
        "| Variável | Padrão | Para quê |",
        "|---|---|---|",
        "| `SMARKEE_CONFIG_PATH` | `config.toml` | Caminho do arquivo de configuração. |",
        "| `SMARKEE_SECRETS_DIR` | `/run/secrets` | Diretório dos arquivos de segredo. |",
        "| `SMARKEE_ENVIRONMENT` | `dev` | Ambiente informado à telemetria (`dev`, `stg`, "
        "`prd`). |\n",
        "## 2. Como o dev entrega cada fonte\n",
        "| Fonte | No `compose.yaml` |",
        "|---|---|",
        f"| Linha de comando | O `command` é só o nome do papel (`[{kebab}-receiver]`), sem "
        "argumentos. |",
        "| Ambiente | `environment:` repassa do `.env` só o que não é senha (por exemplo, "
        "audiência e IDs do Zitadel). |",
        "| `config.toml` | Montado em `/etc/smarkee/config.toml` (`SMARKEE_CONFIG_PATH`). "
        "Endereços usam os nomes da rede Docker (`database.smarkee.internal`, "
        "`messaging.smarkee.internal`). |",
        "| Arquivo de segredo | Bloco `secrets:` com `environment: <VARIÁVEL>`: cada papel monta "
        "só as suas senhas. |\n",
        "Fora do Docker, os nomes `*.smarkee.internal` não resolvem: use as portas publicadas em "
        "`127.0.0.1` (Postgres `5432`, NATS `4222`) por flag ou variável.\n",
    ]
    return "\n".join([*head, *body]).rstrip("\n") + "\n"


def main() -> int:
    feature_dir = Path.cwd()
    if not (feature_dir / "pyproject.toml").exists():
        print("erro: rode dentro de features/<módulo>/<tipo>", file=sys.stderr)
        return 2
    sys.path.insert(0, str(feature_dir / "src"))
    expected = render_guide(feature_dir)
    target = feature_dir / GUIDE
    if "--check" in sys.argv[1:]:
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current != expected:
            print(f"divergente: {GUIDE} (regenere o guia)", file=sys.stderr)
            return 1
        return 0
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(expected, encoding="utf-8")
    print(f"gravado: {GUIDE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
