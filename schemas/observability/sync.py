"""Sincroniza o formatter e o teste de log canônicos para os componentes (decisão 0046).

A fonte está em `schemas/observability/python/`. Cada componente mantém a sua cópia (decisão 0015),
gerada daqui: `logging_config.py` idêntico e `tests/unit/test_logging.py` com `PKG` trocado pelo
nome do pacote (`<módulo>_<tipo>_<papel>`). Sem argumentos, grava as cópias; com `--check`, falha se
alguma divergir. Usa apenas a biblioteca padrão.
"""

import sys
from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
SOURCE = Path(__file__).resolve().parent / "python"
ROLES = ("receiver", "manager", "publisher", "observer", "reconciler", "executor")


def components() -> list[tuple[Path, str]]:
    """Pares (diretório do projeto, nome do pacote) de todos os componentes."""
    found: list[tuple[Path, str]] = []
    for pyproject in sorted((REPOSITORY_ROOT / "features").glob("*/*/*/pyproject.toml")):
        project = pyproject.parent
        if project.name in ROLES:
            module, resource_type = project.parents[1].name, project.parents[0].name
            found.append((project, f"{module}_{resource_type}_{project.name}"))
    return found


def expected_files() -> dict[Path, str]:
    """Caminho de cada cópia e o conteúdo esperado."""
    logging_source = (SOURCE / "logging_config.py").read_text(encoding="utf-8")
    test_source = (SOURCE / "test_logging.py").read_text(encoding="utf-8")
    expected: dict[Path, str] = {}
    for project, package in components():
        expected[project / "src" / package / "logging_config.py"] = logging_source
        expected[project / "tests" / "unit" / "test_logging.py"] = test_source.replace(
            "PKG", package
        )
    return expected


def divergent_files() -> list[Path]:
    return [
        path
        for path, content in expected_files().items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    ]


def main() -> int:
    if "--check" in sys.argv[1:]:
        divergent = divergent_files()
        for path in divergent:
            print(f"divergente: {path.relative_to(REPOSITORY_ROOT)}")
        return 1 if divergent else 0
    for path, content in expected_files().items():
        path.write_text(content, encoding="utf-8")
    print(f"{len(expected_files())} arquivos gravados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
