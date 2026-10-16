"""O `domain/` é puro: não importa adaptador, banco, rede nem a orquestração (decisão 0017)."""

import ast
from pathlib import Path

import ipm_organization_receiver.domain as domain_package

FORBIDDEN_ROOTS = {
    "psycopg",
    "psycopg_pool",
    "nats",
    "asyncio",
    "socket",
    "httpx",
    "pydantic_settings",
}
FORBIDDEN_LAYERS = {"http", "auth", "store", "transport", "main", "settings"}


def _imports_of(path: Path) -> set[str]:
    imports: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            imports.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            imports.add(node.module)
    return imports


def test_domain_does_not_import_adapters_or_orchestration() -> None:
    directories = list(domain_package.__path__)
    assert directories
    violations: list[str] = []
    for directory in directories:
        for path in Path(directory).rglob("*.py"):
            for module in _imports_of(path):
                parts = module.split(".")
                layer = (
                    parts[1] if parts[0] == "ipm_organization_receiver" and len(parts) > 1 else None
                )
                if parts[0] in FORBIDDEN_ROOTS or layer in FORBIDDEN_LAYERS:
                    violations.append(f"{path.name} importa {module}")
    assert violations == []
