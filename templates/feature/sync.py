"""Sincroniza o template das features a partir da fonte única `templates/feature/files/` (decisão 0064).

Cada arquivo de `files/` é o modelo de um arquivo idêntico em todas as features, com marcadores no
lugar dos nomes da feature:

- `@@PACKAGE@@` pacote Python (`core_account`); no caminho, o diretório `PACKAGE`;
- `@@KEBAB@@` nome do projeto e dos contêineres (`core-account`);
- `@@UPPER@@` prefixo das variáveis de ambiente (`CORE_ACCOUNT`);
- `@@DOTTED@@` módulo e tipo do recurso (`core.account`);
- `@@MODULE@@` módulo (`core`).

Sem argumentos, grava as cópias em cada `features/<módulo>/<tipo>/`; com `--check`, falha se alguma
divergir da fonte. Usa apenas a biblioteca padrão. Alterar o template: editar o modelo, rodar este
script e rodar a suíte de cada feature (AGENTS §22).
"""

import sys
from pathlib import Path

FEATURES = Path(__file__).resolve().parents[2] / "features"
SOURCE = Path(__file__).resolve().parent / "files"


def features() -> list[tuple[Path, dict[str, str]]]:
    """Diretório de cada feature (com `pyproject.toml`) e os valores dos marcadores."""
    found: list[tuple[Path, dict[str, str]]] = []
    for pyproject in sorted(FEATURES.glob("*/*/pyproject.toml")):
        module, resource_type = pyproject.parent.parent.name, pyproject.parent.name
        found.append(
            (
                pyproject.parent,
                {
                    "@@PACKAGE@@": f"{module}_{resource_type}",
                    "@@KEBAB@@": f"{module}-{resource_type}",
                    "@@UPPER@@": f"{module}_{resource_type}".upper(),
                    "@@DOTTED@@": f"{module}.{resource_type}",
                    "@@MODULE@@": module,
                },
            )
        )
    return found


def render(template: str, values: dict[str, str]) -> str:
    for marker, value in values.items():
        template = template.replace(marker, value)
    return template


def expected_files() -> dict[Path, str]:
    """Caminho de cada cópia e o conteúdo esperado."""
    expected: dict[Path, str] = {}
    for project, values in features():
        for source in sorted(path for path in SOURCE.rglob("*") if path.is_file()):
            relative = source.relative_to(SOURCE)
            parts = (values["@@PACKAGE@@"] if part == "PACKAGE" else part for part in relative.parts)
            target = project / Path(*parts)
            expected[target] = render(source.read_text(encoding="utf-8"), values)
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
            print(f"divergente: {path.relative_to(FEATURES)}")
        return 1 if divergent else 0
    expected = expected_files()
    for path, content in expected.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    print(f"{len(expected)} arquivos gravados")
    return 0


if __name__ == "__main__":
    sys.exit(main())
