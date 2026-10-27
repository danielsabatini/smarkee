"""Os papéis são processos separados (decisão 0063): nenhum importa outro, só o código comum."""

import ast
from pathlib import Path

import pytest

SOURCE_ROOT = Path(__file__).resolve().parents[3] / "src" / "ipm_user"
# Os papéis da feature são os diretórios do pacote (com exceção do código comum): cada feature tem
# o conjunto do seu loop (por exemplo, `api`, `publisher` e `controller`).
ROLES = tuple(
    sorted(path.name for path in SOURCE_ROOT.iterdir() if path.is_dir() and path.name != "common")
    if SOURCE_ROOT.is_dir()
    else ()
)


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_every_role_has_its_own_directory() -> None:
    assert ROLES
    assert "common" in {path.name for path in SOURCE_ROOT.iterdir() if path.is_dir()}


@pytest.mark.parametrize("role", ROLES)
def test_role_does_not_import_another_role(role: str) -> None:
    others = {f"ipm_user.{other}" for other in ROLES if other != role}
    violations = [
        f"{path.relative_to(SOURCE_ROOT)} importa {module}"
        for path in (SOURCE_ROOT / role).rglob("*.py")
        for module in _imported_modules(path)
        if any(module == other or module.startswith(f"{other}.") for other in others)
    ]
    assert violations == []


def test_common_does_not_import_any_role() -> None:
    roles = {f"ipm_user.{role}" for role in ROLES}
    violations = [
        f"{path.relative_to(SOURCE_ROOT)} importa {module}"
        for path in (SOURCE_ROOT / "common").rglob("*.py")
        for module in _imported_modules(path)
        if any(module == role or module.startswith(f"{role}.") for role in roles)
    ]
    assert violations == []
