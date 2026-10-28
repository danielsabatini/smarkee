"""Backup, verificação, restauração e reset: a ordem, as travas e a prova de que restaura."""

import hashlib
import json
import os
from collections.abc import Callable
from pathlib import Path
from typing import Any, cast

from smarkee_dev_backup.model import (
    ALLOWED_DATABASES,
    CHECKSUMS,
    DATABASES,
    ENV_FILES,
    FORMAT_VERSION,
    MANIFEST,
    VOLUMES,
    BackupError,
    Ports,
)

Say = Callable[[str], None]

# Linhas que mudam a cada dump sem mudar o conteúdo (data e token de proteção do `pg_dump`).
_VOLATILE_PREFIXES = ("-- Dumped", "-- Started", "-- Completed", "\\restrict ", "\\unrestrict ")


def normalize(lines: list[str]) -> list[str]:
    """Remove o que varia a cada dump e ordena: a posição física das linhas não é conteúdo."""
    return sorted(line for line in lines if not line.startswith(_VOLATILE_PREFIXES))


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _files(directory: Path) -> list[Path]:
    return sorted(
        path for path in directory.rglob("*") if path.is_file() and path.name != CHECKSUMS
    )


def _restrict(directory: Path) -> None:
    """O backup guarda hashes, chaves e a masterkey: só o dono lê."""
    for path in [directory, *directory.rglob("*")]:
        path.chmod(0o700 if path.is_dir() else 0o600)


def list_backups(root: Path) -> list[Path]:
    if not root.is_dir():
        return []
    return sorted(path for path in root.iterdir() if (path / MANIFEST).is_file())


def resolve(root: Path, name: str | None) -> Path:
    backups = list_backups(root)
    if name is None:
        if not backups:
            raise BackupError(f"nenhum backup em {root}")
        return backups[-1]
    path = root / name
    if path.name != name or path not in backups:
        raise BackupError(f"backup não encontrado: {name} (veja `list`)")
    return path


def _valid_items(items: object, allowed: tuple[str, ...]) -> bool:
    if not isinstance(items, list):
        return False
    typed = cast("list[object]", items)
    return all(isinstance(item, str) and item in allowed for item in typed)


def read_manifest(path: Path) -> dict[str, Any]:
    manifest = cast("dict[str, Any]", json.loads((path / MANIFEST).read_text(encoding="utf-8")))
    if manifest.get("formatVersion") != FORMAT_VERSION:
        raise BackupError(f"formato de backup não suportado em {path.name}")
    if not _valid_items(manifest.get("databases"), ALLOWED_DATABASES):
        raise BackupError(f"bancos inválidos no manifesto de {path.name}")
    if not _valid_items(manifest.get("volumes"), VOLUMES):
        raise BackupError(f"volumes inválidos no manifesto de {path.name}")
    if not _valid_items(manifest.get("envFiles"), ENV_FILES):
        raise BackupError(f"arquivos .env inválidos no manifesto de {path.name}")
    return manifest


def _write_private_copy(source: Path, destination: Path) -> None:
    """Copia `source` criando `destination` já com permissão `0600` desde o primeiro byte."""
    destination.parent.mkdir(parents=True, exist_ok=True)
    data = source.read_bytes()
    fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, data)
    finally:
        os.close(fd)


def create_backup(ports: Ports, say: Say = print) -> Path:
    ports.root.mkdir(parents=True, exist_ok=True)
    ports.root.chmod(0o700)
    target = ports.root / ports.now().strftime("%Y%m%dT%H%M%SZ")
    if target.exists():
        raise BackupError(f"já existe um backup com este nome: {target.name}")
    target.mkdir(mode=0o700)
    target.chmod(0o700)
    (target / "db").mkdir(mode=0o700)
    (target / "volumes").mkdir(mode=0o700)
    for database in DATABASES:
        say(f"  banco {database}")
        ports.stack.dump_database(database, target / "db" / f"{database}.dump")
    say("  papéis do PostgreSQL")
    ports.stack.dump_globals(target / "db" / "globals.sql")
    for volume in VOLUMES:
        say(f"  volume {volume}")
        ports.stack.archive_volume(volume, target / "volumes" / f"{volume}.tar.gz")
    env_files: list[str] = []
    for relative in ENV_FILES:
        source = ports.repository / relative
        if source.is_file():
            _write_private_copy(source, target / "env" / relative)
            env_files.append(relative)
    manifest = {
        "formatVersion": FORMAT_VERSION,
        "createdAt": ports.now().isoformat(),
        "gitCommit": ports.git_commit(),
        "postgresVersion": ports.stack.postgres_version(),
        "databases": list(DATABASES),
        "volumes": list(VOLUMES),
        "envFiles": env_files,
    }
    (target / MANIFEST).write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    sums = [f"{_sha256(path)}  {path.relative_to(target).as_posix()}" for path in _files(target)]
    (target / CHECKSUMS).write_text("\n".join(sums) + "\n", encoding="utf-8")
    _restrict(target)
    return target


def check_integrity(path: Path) -> list[str]:
    """Problemas de integridade: arquivo alterado, faltando ou que não está na lista de somas."""
    sums_file = path / CHECKSUMS
    if not sums_file.is_file():
        return [f"{CHECKSUMS} ausente"]
    expected: dict[str, str] = {}
    for line in sums_file.read_text(encoding="utf-8").splitlines():
        digest, _, relative = line.partition("  ")
        expected[relative] = digest
    problems: list[str] = []
    for relative, digest in expected.items():
        file = path / relative
        if not file.is_file():
            problems.append(f"arquivo ausente: {relative}")
        elif _sha256(file) != digest:
            problems.append(f"arquivo alterado: {relative}")
    present = {file.relative_to(path).as_posix() for file in _files(path)}
    problems.extend(
        f"arquivo fora da lista de somas: {name}" for name in sorted(present - expected.keys())
    )
    return problems


def verify(ports: Ports, path: Path, say: Say = print) -> list[str]:
    """Integridade e prova de restauração: restaura num PostgreSQL descartável e compara."""
    problems = check_integrity(path)
    if problems:
        return problems
    manifest = read_manifest(path)
    with ports.open_scratch() as scratch:
        scratch.restore_globals(path / "db" / "globals.sql")
        for database in cast("list[str]", manifest["databases"]):
            say(f"  restaurando {database} num banco descartável")
            dump = path / "db" / f"{database}.dump"
            scratch.restore_database(database, dump)
            original = normalize(scratch.lines_of_file(dump))
            restored = normalize(scratch.lines_of_database(database))
            if original != restored:
                differing = len(set(original) ^ set(restored))
                problems.append(
                    f"banco {database}: o restaurado difere do backup ({differing} linhas)"
                )
    return problems


def _env_differences(ports: Ports, path: Path, manifest: dict[str, Any]) -> list[str]:
    differences: list[str] = []
    for relative in cast("list[str]", manifest["envFiles"]):
        live = ports.repository / relative
        if live.is_file() and live.read_bytes() != (path / "env" / relative).read_bytes():
            differences.append(
                f"{relative} difere do backup; resolva à mão "
                "(a masterkey do Zitadel precisa ser a do backup)"
            )
    return differences


def restore(ports: Ports, path: Path, *, apply_changes: bool, say: Say = print) -> int:
    """Restaura o backup no ambiente de dev. Sem `apply_changes`, só mostra o plano."""
    manifest = read_manifest(path)
    say(
        f"backup {path.name} (criado em {manifest['createdAt']}, "
        f"commit {manifest['gitCommit'][:8]})"
    )
    say("verificando o backup antes de qualquer alteração")
    problems = verify(ports, path, say) + (
        _env_differences(ports, path, manifest) if not check_integrity(path) else []
    )
    if problems:
        for problem in problems:
            say(f"  PROBLEMA: {problem}")
        say("nada foi alterado")
        return 1
    say("plano:")
    say("  1. copiar os .env que faltam (os existentes e iguais não mudam)")
    say("  2. parar os componentes das features e a plataforma que usa os bancos")
    say("  3. recriar os papéis do PostgreSQL e substituir os bancos " + ", ".join(DATABASES))
    say("  4. substituir o conteúdo dos volumes " + ", ".join(VOLUMES))
    say("  5. subir de novo os serviços parados")
    say("  não restaura o estado do NATS (JetStream) nem o Mailpit: não fazem parte do backup")
    if not apply_changes:
        say("nada foi alterado; use --apply para restaurar")
        return 0
    for relative in cast("list[str]", manifest["envFiles"]):
        live = ports.repository / relative
        if not live.exists():
            _write_private_copy(path / "env" / relative, live)
            say(f"  .env copiado: {relative}")
    ports.stack.stop_components()
    ports.stack.restore_globals(path / "db" / "globals.sql")
    for database in cast("list[str]", manifest["databases"]):
        say(f"  restaurando o banco {database}")
        ports.stack.restore_database(database, path / "db" / f"{database}.dump")
    for volume in cast("list[str]", manifest["volumes"]):
        say(f"  restaurando o volume {volume}")
        ports.stack.restore_volume(volume, path / "volumes" / f"{volume}.tar.gz")
    ports.stack.start_components()
    say("restauração concluída")
    return 0


def reset(ports: Ports, *, apply_changes: bool, say: Say = print) -> int:
    """Zera o ambiente de dev **depois** de um backup verificado."""
    say("o reset: 1) faz o backup, 2) prova que ele restaura, 3) remove contêineres e volumes")
    say("o estado do NATS (JetStream) e o Mailpit também serão perdidos: não fazem parte do backup")
    if not apply_changes:
        say("nada foi alterado; use --apply")
        return 0
    say("backup:")
    path = create_backup(ports, say)
    say(f"  gravado em {path}")
    problems = verify(ports, path, say)
    if problems:
        for problem in problems:
            say(f"  PROBLEMA: {problem}")
        say("o backup NÃO foi confirmado; o ambiente não foi removido")
        return 1
    say("backup verificado; removendo o ambiente")
    ports.stack.remove_everything()
    say("ambiente removido. Para recriar: rode `restore --apply`")
    return 0
