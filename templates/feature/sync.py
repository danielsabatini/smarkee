"""Sincroniza o template das features a partir da fonte única `templates/feature/files/`.

Decisão 0064.

Cada arquivo de `files/` é o modelo de um arquivo idêntico em todas as features, e cada arquivo de
`optional/<perfil>/`, de um arquivo idêntico nas features que declaram o perfil em `PROFILES`. Os
marcadores ocupam o lugar dos nomes da feature:

- `@@PACKAGE@@` pacote Python (`core_account`); no caminho, o diretório `PACKAGE`;
- `@@KEBAB@@` nome do projeto e dos contêineres (`core-account`);
- `@@UPPER@@` prefixo das variáveis de ambiente (`CORE_ACCOUNT`);
- `@@DOTTED@@` módulo e tipo do recurso (`core.account`);
- `@@MODULE@@` módulo (`core`) e `@@TYPE@@` tipo do recurso (`account`);
- `@@CLASS@@` prefixo de classe (`CoreAccount`), `@@TYPE_CLASS@@` prefixo de classe do tipo
  (`Account`, como em `AccountObserverSettings`) e `@@SPACED@@` nome em texto (`core account`).

Sem argumentos ou com `--check`, verifica se alguma feature divergiu da fonte (modo somente leitura).
Com `--write`, grava as cópias em cada `features/<módulo>/<tipo>/`. Com `--new <módulo> <tipo>`, cria a
pasta da feature com os arquivos da semente (`seed/`, gravada uma única vez porque cada feature o
ajusta) e grava as cópias. Usa apenas a biblioteca padrão. Alterar o template: editar o modelo, rodar
`sync.py --write` e rodar a suíte de cada feature (AGENTS §22).
"""

import re
import sys
from pathlib import Path

FEATURES = Path(__file__).resolve().parents[2] / "features"
SOURCE = Path(__file__).resolve().parent / "files"
OPTIONAL = Path(__file__).resolve().parent / "optional"
SEED = Path(__file__).resolve().parent / "seed"

# Nome de módulo e de tipo: uma palavra em minúsculas, porque entra no pacote Python, no nome do
# projeto, no prefixo das variáveis de ambiente e no subject (`<módulo>_<tipo>`, `<módulo>-<tipo>`).
NAME = re.compile(r"[a-z][a-z0-9]*")

# Perfis opcionais: arquivos idênticos só nas features que os declaram aqui (`<módulo>/<tipo>`).
# Uma feature entra num perfil quando o seu código já é igual ao do modelo; as demais seguem com
# os seus.
PROFILES: dict[str, tuple[str, ...]] = {
    # Publicação do `requested`, probes e os tipos do domínio do Receiver (erros, linhas das views
    # e pedidos), sem regra do tipo.
    "receiver-http": (
        "bsm/account",
        "core/account",
    ),
    # Contexto de trace e OpenAPI do Receiver: todas as features com Receiver (a `ipm/serviceaccount`
    # tem `api`, decisão 0098).
    "receiver-base": (
        "bsm/account",
        "core/account",
        "sum/service",
    ),
    # Processo `api` (decisão 0098): probes, OpenAPI e contexto de trace; as demais peças são do tipo.
    "api-http": (
        "ipm/group",
        "ipm/organization",
        "ipm/permission",
        "ipm/role",
        "ipm/serviceaccount",
        "ipm/user",
    ),
    # Projeção local das Organizations (dono e ciclo de vida) a partir do `DESIRED`: substitui a
    # consulta HTTP à API da Organization (decisão 0100).
    "organization-projection": (
        "ipm/group",
        "ipm/role",
        "ipm/serviceaccount",
        "ipm/user",
    ),
    # Projeção local do pertencimento (Organization de cada usuário e service account) a partir do
    # `DESIRED`: substitui a consulta HTTP às APIs de User e ServiceAccount (decisão 0100).
    "member-projection": (
        "ipm/group",
        "ipm/organization",
        "ipm/role",
        "ipm/serviceaccount",
        "ipm/user",
    ),
    # Envelope, publicação e persistência de `observed` e do resultado, com a convergência e os
    # erros do Manager, sem regra do tipo. O `sum/service` usa só este perfil (decisão 0080).
    "manager-handlers": (
        "bsm/account",
        "core/account",
        "sum/service",
    ),
    # Observação e resultado no Manager (`observed`, `result`, convergência e prazo de observação): só
    # nas features com o loop de sete papéis; o Controller (decisão 0096) faz isso no próprio ciclo.
    "manager-observation": (
        "bsm/account",
        "core/account",
        "sum/service",
    ),
    # Fontes de estado do Reconciler (`DESIRED`, `OBSERVED` e `RESULT`): só as features com o loop
    # de sete papéis (decisão 0096 aposenta o Reconciler nas demais).
    "reconciler-streams": (
        "bsm/account",
        "core/account",
        "sum/service",
    ),
    # Driver de metadado do provedor de identidade, escrita (Executor) e leitura (Observer).
    "identity-metadata": ("core/account",),
    # Motores sem regra do tipo: Observer e Executor (com a revalidação), com o teste do motor do
    # Observer (decisão 0075).
    "loop-engines": (
        "bsm/account",
        "core/account",
    ),
}


def features() -> list[tuple[Path, dict[str, str]]]:
    """Diretório de cada feature (com `pyproject.toml`) e os valores dos marcadores."""
    found: list[tuple[Path, dict[str, str]]] = []
    for pyproject in sorted(FEATURES.glob("*/*/pyproject.toml")):
        module, resource_type = pyproject.parent.parent.name, pyproject.parent.name
        found.append((pyproject.parent, marker_values(module, resource_type)))
    return found


def marker_values(module: str, resource_type: str) -> dict[str, str]:
    """Valor de cada marcador para a feature `<módulo>/<tipo>`."""
    return {
        "@@PACKAGE@@": f"{module}_{resource_type}",
        "@@KEBAB@@": f"{module}-{resource_type}",
        "@@UPPER@@": f"{module}_{resource_type}".upper(),
        "@@DOTTED@@": f"{module}.{resource_type}",
        "@@MODULE@@": module,
        "@@TYPE@@": resource_type,
        "@@CLASS@@": f"{module.title()}{resource_type.title()}",
        "@@TYPE_CLASS@@": resource_type.title(),
        "@@SPACED@@": f"{module} {resource_type}",
    }


def render(template: str, values: dict[str, str]) -> str:
    for marker, value in values.items():
        template = template.replace(marker, value)
    return template


def sources(project: Path) -> list[Path]:
    """Raízes dos modelos que valem para a feature: o template geral e os perfis que ela declara."""
    name = f"{project.parent.name}/{project.name}"
    return [SOURCE, *(OPTIONAL / profile for profile, names in PROFILES.items() if name in names)]


def expected_files() -> dict[Path, str]:
    """Caminho de cada cópia e o conteúdo esperado."""
    expected: dict[Path, str] = {}
    for project, values in features():
        for root in sources(project):
            for source in sorted(path for path in root.rglob("*") if path.is_file()):
                parts = (
                    values["@@PACKAGE@@"] if part == "PACKAGE" else part
                    for part in source.relative_to(root).parts
                )
                expected[project / Path(*parts)] = render(
                    source.read_text(encoding="utf-8"), values
                )
    return expected


def divergent_files() -> list[Path]:
    return [
        path
        for path, content in expected_files().items()
        if not path.exists() or path.read_text(encoding="utf-8") != content
    ]


def new_feature(module: str, resource_type: str) -> Path:
    """Cria a pasta da feature com os arquivos da semente; recusa uma feature que já existe."""
    for label, value in (("módulo", module), ("tipo", resource_type)):
        if not NAME.fullmatch(value):
            raise ValueError(f"{label} inválido: {value!r} (uma palavra em minúsculas e dígitos)")
    project = FEATURES / module / resource_type
    if project.exists():
        raise FileExistsError(f"a feature já existe: {project}")
    values = marker_values(module, resource_type)
    for source in sorted(path for path in SEED.rglob("*") if path.is_file()):
        target = project / render(str(source.relative_to(SEED)), values)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(render(source.read_text(encoding="utf-8"), values), encoding="utf-8")
    return project


def main() -> int:
    arguments = sys.argv[1:]
    if arguments[:1] == ["--new"]:
        if len(arguments) != 3:
            print("uso: sync.py --new <módulo> <tipo>", file=sys.stderr)
            return 2
        try:
            project = new_feature(arguments[1], arguments[2])
        except (ValueError, FileExistsError) as error:
            print(f"erro: {error}", file=sys.stderr)
            return 2
        print(f"criada: {project.relative_to(FEATURES)}")
        return 0
    if "--write" in arguments:
        expected = expected_files()
        for path, content in expected.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content, encoding="utf-8")
        print(f"{len(expected)} arquivos gravados")
        return 0

    # Modo padrão: somente leitura (--check explícito ou padrão sem argumentos)
    divergent = divergent_files()
    for path in divergent:
        print(f"divergente: {path.relative_to(FEATURES)}")
    return 1 if divergent else 0


if __name__ == "__main__":
    sys.exit(main())
