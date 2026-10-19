"""Apaga os sinais de telemetria gravados em disco pelos telemeters de dev.

Os telemeters (`platform-telemeter` e o de cada feature) gravam logs, métricas e traces em arquivos
`*.jsonl` (decisões 0053 e 0062) só para gerar dados de análise. Este comando zera essas pastas
para uma nova rodada de testes começar sem o histórico anterior.

Sem `--apply`, só lista. Com `--apply`, remove os arquivos rotacionados e **trunca** o arquivo
ativo de cada pasta: o coletor mantém o arquivo aberto, e apagá-lo faria os próximos sinais irem
para um arquivo que já não existe no disco. Nada fora dessas pastas é tocado, e só `*.jsonl`.
"""

import argparse
import sys
from dataclasses import dataclass
from pathlib import Path

PLATFORM_TELEMETER = Path("infrastructure/dev/platform-telemeter")
SIGNAL_FOLDERS = (
    "logs/app",
    "logs/infra",
    "metrics/app",
    "metrics/infra",
    "traces",
)
"""Pastas do `platform-telemeter` (logs/{app,infra}, metrics/{app,infra} e traces)."""
FEATURE_TELEMETER_FOLDERS = ("logs", "traces")
"""Pastas do telemeter de cada feature (`features/<módulo>/<tipo>/telemeter`)."""
ACTIVE_FILE_NAMES = frozenset({"logs.jsonl", "metrics.jsonl", "traces.jsonl"})
"""Nome do arquivo que o coletor mantém aberto; os demais são rotacionados (`*-size.jsonl`)."""


@dataclass(frozen=True, slots=True)
class SignalFile:
    path: Path
    size_bytes: int
    active: bool
    """O coletor mantém este arquivo aberto: é truncado, e não removido."""


def repository_root() -> Path:
    """Raiz do repositório, a partir deste arquivo (`scripts/dev/<projeto>/src/<pacote>/`)."""
    return Path(__file__).resolve().parents[5]


def signal_folders(root: Path) -> list[Path]:
    folders = [root / PLATFORM_TELEMETER / folder for folder in SIGNAL_FOLDERS]
    for telemeter in sorted(root.glob("features/*/*/telemeter")):
        folders.extend(telemeter / folder for folder in FEATURE_TELEMETER_FOLDERS)
    return folders


def find_signal_files(root: Path) -> list[SignalFile]:
    """Arquivos `*.jsonl` não vazios das pastas de sinais. Links simbólicos são ignorados."""
    found: list[SignalFile] = []
    for folder in signal_folders(root):
        if not folder.is_dir():
            continue
        for path in sorted(folder.glob("*.jsonl")):
            if path.is_symlink() or not path.is_file():
                continue
            size_bytes = path.stat().st_size
            if size_bytes > 0:  # arquivo vazio já está limpo
                found.append(SignalFile(path, size_bytes, path.name in ACTIVE_FILE_NAMES))
    return found


def clear(signal: SignalFile) -> None:
    """Zera o arquivo: trunca o ativo (o coletor segue gravando nele) e remove o rotacionado."""
    if signal.active:
        with signal.path.open("r+b") as file:
            file.truncate(0)
    else:
        signal.path.unlink()


def remaining_bytes(root: Path) -> int:
    return sum(signal.size_bytes for signal in find_signal_files(root))


def _megabytes(size_bytes: int) -> str:
    return f"{size_bytes / 1_000_000:.1f} MB"


def run(root: Path, *, apply: bool) -> int:
    """Lista e, com `apply`, zera os sinais. Devolve 1 se ainda houver sinal no fim, senão 0."""
    if not (root / PLATFORM_TELEMETER).is_dir():
        print(
            f"error: {root / PLATFORM_TELEMETER} not found; is this the repository?",
            file=sys.stderr,
        )
        return 2
    signals = find_signal_files(root)
    if not signals:
        print("No telemetry signals on disk.")
        return 0
    for signal in signals:
        print(f"{_megabytes(signal.size_bytes):>10}  {signal.path.relative_to(root)}")
    total = sum(signal.size_bytes for signal in signals)
    print(f"{len(signals)} files, {_megabytes(total)}.")
    if not apply:
        print("Nothing changed. Repeat with --apply to clear them.")
        return 1
    for signal in signals:
        clear(signal)
    left = remaining_bytes(root)
    print(f"Cleared. {_megabytes(left)} left on disk.")
    return 0 if left == 0 else 1


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="smarkee-dev-telemetry-reset",
        description="Clear the telemetry signals the dev telemeters wrote to disk.",
    )
    parser.add_argument("--apply", action="store_true", help="clear the files (default: only list)")
    arguments = parser.parse_args()
    sys.exit(run(repository_root(), apply=arguments.apply))
