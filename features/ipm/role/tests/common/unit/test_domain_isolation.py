"""O `domain/` de cada papel é puro: não importa adaptador, banco, rede nem a orquestração (0017).

Também não importa os módulos comuns que fazem I/O ou sobem processo; os puros (`contracts`,
`ids`, `logging_config`, `ports`, `resource`) são permitidos.
"""

import ast
import importlib
from pathlib import Path

import pytest

FORBIDDEN_ROOTS = {
    "psycopg",
    "psycopg_pool",
    "nats",
    "asyncio",
    "socket",
    "httpx",
    "pydantic_settings",
}
FORBIDDEN_COMMON = {
    "database",
    "http",
    "lifecycle",
    "messaging",
    "runtime",
    "settings",
    "identity",
}
FORBIDDEN_LAYERS = {
    "api": {"http", "auth", "store", "transport", "main", "settings"},
    "receiver": {"http", "auth", "store", "transport", "main", "settings"},
    "manager": {"handlers", "store", "outbox", "transport", "http", "main", "settings"},
    "publisher": {"outbox", "transport", "http", "main", "settings"},
    "controller": {"engine", "drivers", "store", "http", "main", "settings"},
    "observer": {"engine", "provider", "transport", "http", "main", "settings"},
    "reconciler": {"engine", "transport", "http", "main", "settings"},
    "executor": {"engine", "actions", "provider", "transport", "http", "main", "settings"},
}
# `http` é um pacote da stdlib (`HTTPStatus`) que o domínio do Receiver usa; nos demais papéis é a
# camada de saúde e é proibida.
STDLIB_HTTP_ALLOWED = {"api", "receiver"}


def _imports_of(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports


def _violation(role: str, module: str) -> bool:
    parts = module.split(".")
    forbidden_roots = set(FORBIDDEN_ROOTS)
    if role not in STDLIB_HTTP_ALLOWED:
        forbidden_roots.add("http")
    if parts[0] in forbidden_roots:
        return True
    if len(parts) < 3 or parts[0] != "ipm_role":
        return False
    if parts[1] == role:
        return parts[2] in FORBIDDEN_LAYERS[role]
    return parts[1] == "common" and parts[2] in FORBIDDEN_COMMON


@pytest.mark.parametrize(
    ("role", "module", "forbidden"),
    [
        ("manager", "nats.aio.client", True),
        ("manager", "ipm_role.manager.store.ssot", True),
        ("manager", "ipm_role.common.messaging", True),
        ("manager", "ipm_role.common.settings", True),
        ("manager", "ipm_role.common.ports", False),
        ("manager", "ipm_role.common.contracts.base", False),
        ("manager", "ipm_role.manager.domain.policy", False),
        ("receiver", "http", False),
        ("api", "http", False),
        ("executor", "http", True),
        ("controller", "http", True),
    ],
)
def test_the_rule_flags_what_the_domain_must_not_import(
    role: str, module: str, forbidden: bool
) -> None:
    assert _violation(role, module) is forbidden


SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "ipm_role"
PRESENT_ROLES = sorted(
    role for role in FORBIDDEN_LAYERS if (SOURCE_ROOT / role / "domain").is_dir()
)
"""Papéis que a feature tem (cada uma tem o conjunto do seu loop) e que possuem `domain/`."""


@pytest.mark.parametrize("role", PRESENT_ROLES)
def test_domain_does_not_import_adapters_or_orchestration(role: str) -> None:
    domain_package = importlib.import_module(f"ipm_role.{role}.domain")
    directories = list(domain_package.__path__)
    assert directories
    violations = [
        f"{path.name} importa {module}"
        for directory in directories
        for path in Path(directory).rglob("*.py")
        for module in _imports_of(path)
        if _violation(role, module)
    ]
    assert violations == []
