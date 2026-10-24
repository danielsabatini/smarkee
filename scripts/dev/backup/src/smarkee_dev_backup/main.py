"""Backup, verificação, restauração e reset seguro do ambiente de desenvolvimento.

Guarda o que não se reconstrói só com o repositório: os bancos do Zitadel e do SSOT, os
volumes de estado (`identity-bootstrap` e `bsm-account-state`) e os `.env` (com a masterkey
do Zitadel e os IDs da CLI `sk`). É uma **ferramenta de operação**, e não um componente da
plataforma.

Comandos (o padrão é `backup`):
  backup            grava um backup novo e o verifica
  list              lista os backups
  verify [NOME]     prova que o backup restaura: usa um PostgreSQL descartável e compara
  restore [NOME]    mostra o plano para restaurar no ambiente de dev; --apply restaura
  reset             mostra o plano; --apply faz o backup, o verifica e SÓ ENTÃO zera o ambiente

Segurança:
- só atua no ambiente de dev local (contêineres e volumes com nomes fixos; recusa BACKUP_*);
- `restore` e `reset` não alteram nada sem `--apply`; `reset` não remove nada se o backup não
  for confirmado; `restore` não sobrescreve um `.env` diferente do backup;
- o backup fica em ~/.smarkee/backups (fora do repositório e do Docker), com permissão só do dono:
  tem hashes de senha, chaves e a masterkey; nunca é impresso;
- o estado do NATS (JetStream) e o Mailpit não fazem parte do backup.
"""

import argparse
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from smarkee_dev_backup.adapters import DockerStack, database_image, open_scratch
from smarkee_dev_backup.engine import (
    check_integrity,
    create_backup,
    list_backups,
    reset,
    resolve,
    restore,
    verify,
)
from smarkee_dev_backup.model import BackupError, Ports

REPOSITORY = Path(__file__).resolve().parents[5]
BACKUP_ROOT = Path.home() / ".smarkee" / "backups"
COMMANDS = ("backup", "list", "verify", "restore", "reset")


def refuse_outside_development() -> None:
    """Só o ambiente de dev local vale; qualquer outro destino, pedido por variável, é recusado."""
    for name in os.environ:
        if name.startswith("BACKUP_"):
            raise SystemExit(f"{name} não é aceita: este script só roda no ambiente de dev local")


def git_commit() -> str:
    done = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=REPOSITORY, capture_output=True, text=True, check=False
    )
    return done.stdout.strip() or "desconhecido"


def build_ports() -> Ports:
    image = database_image()
    return Ports(
        stack=DockerStack(REPOSITORY),
        open_scratch=lambda: open_scratch(image),
        repository=REPOSITORY,
        root=BACKUP_ROOT,
        now=lambda: datetime.now(UTC),
        git_commit=git_commit,
    )


def run(command: str, name: str | None, *, apply_changes: bool) -> int:
    refuse_outside_development()
    if command == "list":
        for path in list_backups(BACKUP_ROOT):
            size = sum(file.stat().st_size for file in path.rglob("*") if file.is_file())
            print(f"{path.name}  {size / 1024:.0f} KiB")
        return 0
    ports = build_ports()
    if command == "backup":
        path = create_backup(ports)
        problems = verify(ports, path)
        for problem in problems:
            print(f"PROBLEMA: {problem}")
        print(f"backup {'CONFIRMADO' if not problems else 'COM PROBLEMAS'}: {path}")
        return 1 if problems else 0
    if command == "reset":
        return reset(ports, apply_changes=apply_changes)
    path = resolve(BACKUP_ROOT, name)
    if command == "verify":
        problems = verify(ports, path)
        for problem in problems:
            print(f"PROBLEMA: {problem}")
        integrity = "íntegro" if not check_integrity(path) else "COM PROBLEMAS"
        print(
            f"{path.name}: {integrity}; "
            f"restaura igual ao original: {'sim' if not problems else 'NÃO'}"
        )
        return 1 if problems else 0
    return restore(ports, path, apply_changes=apply_changes)


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", nargs="?", default="backup", choices=COMMANDS)
    parser.add_argument("name", nargs="?", help="nome do backup (padrão: o mais recente)")
    parser.add_argument("--apply", action="store_true", help="executa restore ou reset")
    arguments = parser.parse_args()
    try:
        sys.exit(run(arguments.command, arguments.name, apply_changes=arguments.apply))
    except BackupError as error:
        print(f"erro: {error}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    main()
