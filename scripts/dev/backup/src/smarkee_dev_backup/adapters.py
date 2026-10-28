"""Adaptadores do `docker`: o ambiente de dev real e o PostgreSQL descartável da verificação."""

import json
import secrets
import subprocess
import time
from contextlib import AbstractContextManager
from pathlib import Path
from types import TracebackType
from typing import IO, Self

from smarkee_dev_backup.model import (
    DATABASE_NAME,
    FEATURE_DIRECTORIES,
    INFRASTRUCTURE_DEPENDENTS,
    INFRASTRUCTURE_DIRECTORY,
    VOLUME_NAME,
    BackupError,
)

DATABASE_CONTAINER = "database.smarkee.internal"
DEFAULT_POSTGRES_IMAGE = "postgres:18.6-alpine"


def _run(arguments: list[str], *, cwd: Path | None = None) -> str:
    done = subprocess.run(arguments, capture_output=True, text=True, check=False, cwd=cwd)
    if done.returncode != 0:
        # O erro do docker não carrega segredo: são nomes de contêiner, banco e volume.
        raise BackupError(f"falhou: {' '.join(arguments[:4])}: {done.stderr.strip()[:300]}")
    return done.stdout


def _pipe(arguments: list[str], *, source: IO[bytes] | None, sink: IO[bytes] | None) -> None:
    done = subprocess.run(arguments, stdin=source, stdout=sink, stderr=subprocess.PIPE, check=False)
    if done.returncode != 0:
        raise BackupError(f"falhou: {' '.join(arguments[:4])}: {done.stderr.decode()[:300]}")


def _database(name: str) -> str:
    if not DATABASE_NAME.match(name):
        raise BackupError(f"nome de banco inválido: {name!r}")
    return name


def _volume(name: str) -> str:
    if not VOLUME_NAME.match(name):
        raise BackupError(f"nome de volume inválido: {name!r}")
    return name


class DockerStack:
    """O ambiente de dev: o banco `database.smarkee.internal` e os projetos Compose."""

    def __init__(self, repository: Path, database_container: str = DATABASE_CONTAINER) -> None:
        self._repository = repository
        self._container = database_container

    def _image(self) -> str:
        """Mesma imagem do banco (tem `tar` e `pg_*`), sem puxar outra."""
        return database_image(self._container)

    def _psql(self, database: str, sql: str) -> str:
        return _run(
            [
                "docker",
                "exec",
                self._container,
                "psql",
                "-U",
                "postgres",
                "-d",
                database,
                "-Atc",
                sql,
            ]
        )

    def postgres_version(self) -> str:
        return _run(["docker", "exec", self._container, "postgres", "--version"]).strip()

    def dump_database(self, database: str, destination: Path) -> None:
        with destination.open("wb") as sink:
            _pipe(
                [
                    "docker",
                    "exec",
                    self._container,
                    "pg_dump",
                    "-U",
                    "postgres",
                    "-Fc",
                    _database(database),
                ],
                source=None,
                sink=sink,
            )

    def dump_globals(self, destination: Path) -> None:
        with destination.open("wb") as sink:
            _pipe(
                [
                    "docker",
                    "exec",
                    self._container,
                    "pg_dumpall",
                    "-U",
                    "postgres",
                    "--globals-only",
                ],
                source=None,
                sink=sink,
            )

    def archive_volume(self, volume: str, destination: Path) -> None:
        name = _volume(volume)
        with destination.open("wb") as sink:
            _pipe(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-v",
                    f"{name}:/data:ro",
                    self._image(),
                    "tar",
                    "-C",
                    "/data",
                    "-czf",
                    "-",
                    ".",
                ],
                source=None,
                sink=sink,
            )

    def _compose(self, directory: str, *arguments: str) -> None:
        _run(["docker", "compose", *arguments], cwd=self._repository / directory)

    def stop_components(self) -> None:
        for directory in FEATURE_DIRECTORIES:
            self._compose(directory, "stop")
        self._compose(INFRASTRUCTURE_DIRECTORY, "stop", *INFRASTRUCTURE_DEPENDENTS)
        if self._container not in running_containers():
            self._compose(INFRASTRUCTURE_DIRECTORY, "up", "-d", "--wait", "database")
            self._compose(INFRASTRUCTURE_DIRECTORY, "up", "--no-start", "identity")
            self._compose("features/bsm/account", "up", "--no-start", "bsm-account-api")

    def start_components(self) -> None:
        self._compose(INFRASTRUCTURE_DIRECTORY, "up", "-d", "--no-recreate")
        for directory in FEATURE_DIRECTORIES:
            self._compose(directory, "up", "-d", "--no-recreate")

    def restore_globals(self, source: Path) -> None:
        # Os papéis já existem (bootstrap): os erros "already exists" são esperados e o psql segue.
        with source.open("rb") as stream:
            _pipe(
                ["docker", "exec", "-i", self._container, "psql", "-U", "postgres", "-q"],
                source=stream,
                sink=subprocess.DEVNULL,  # pyright: ignore[reportArgumentType]
            )

    def restore_database(self, database: str, source: Path) -> None:
        name = _database(database)
        self._psql(
            "postgres",
            "select pg_terminate_backend(pid) from pg_stat_activity "  # noqa: S608
            f"where datname = '{name}' and pid <> pg_backend_pid()",  # nome validado por _database
        )
        self._psql("postgres", f'drop database if exists "{name}" with (force)')
        with source.open("rb") as stream:
            _pipe(
                [
                    "docker",
                    "exec",
                    "-i",
                    self._container,
                    "pg_restore",
                    "-U",
                    "postgres",
                    "--create",
                    "-d",
                    "postgres",
                ],
                source=stream,
                sink=None,
            )

    def restore_volume(self, volume: str, source: Path) -> None:
        name = _volume(volume)
        with source.open("rb") as stream:
            _pipe(
                [
                    "docker",
                    "run",
                    "--rm",
                    "-i",
                    "-v",
                    f"{name}:/data",
                    self._image(),
                    "sh",
                    "-c",
                    "find /data -mindepth 1 -delete && tar -C /data -xzf -",
                ],
                source=stream,
                sink=None,
            )

    def remove_everything(self) -> None:
        for directory in FEATURE_DIRECTORIES:
            self._compose(directory, "down", "-v")
        self._compose(INFRASTRUCTURE_DIRECTORY, "down", "-v")


class ScratchPostgres:
    """PostgreSQL descartável (rede padrão, sem porta publicada, senha aleatória)."""

    def __init__(self, image: str) -> None:
        self._image = image
        self._name = f"smarkee-backup-verify-{secrets.token_hex(4)}"

    def __enter__(self) -> Self:
        _run(
            [
                "docker",
                "run",
                "-d",
                "--name",
                self._name,
                "-e",
                f"POSTGRES_PASSWORD={secrets.token_hex(16)}",
                self._image,
            ]
        )
        for _ in range(60):
            ready = subprocess.run(
                ["docker", "exec", self._name, "pg_isready", "-U", "postgres"],
                capture_output=True,
                check=False,
            )
            if ready.returncode == 0:
                return self
            time.sleep(1)
        raise BackupError("o PostgreSQL descartável não ficou pronto")

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        subprocess.run(["docker", "rm", "-f", "-v", self._name], capture_output=True, check=False)

    def restore_globals(self, source: Path) -> None:
        with source.open("rb") as stream:
            _pipe(
                ["docker", "exec", "-i", self._name, "psql", "-U", "postgres", "-q"],
                source=stream,
                sink=subprocess.DEVNULL,  # pyright: ignore[reportArgumentType]
            )

    def restore_database(self, database: str, source: Path) -> None:
        _database(database)
        with source.open("rb") as stream:
            _pipe(
                [
                    "docker",
                    "exec",
                    "-i",
                    self._name,
                    "pg_restore",
                    "-U",
                    "postgres",
                    "--create",
                    "-d",
                    "postgres",
                ],
                source=stream,
                sink=None,
            )

    def lines_of_file(self, source: Path) -> list[str]:
        with source.open("rb") as stream:
            done = subprocess.run(
                ["docker", "exec", "-i", self._name, "pg_restore", "-f", "-"],
                stdin=stream,
                capture_output=True,
                check=False,
            )
        if done.returncode != 0:
            raise BackupError(f"pg_restore falhou: {done.stderr.decode()[:300]}")
        return done.stdout.decode().splitlines()

    def lines_of_database(self, database: str) -> list[str]:
        dump = subprocess.run(
            ["docker", "exec", self._name, "pg_dump", "-U", "postgres", "-Fc", _database(database)],
            capture_output=True,
            check=False,
        )
        if dump.returncode != 0:
            raise BackupError(f"pg_dump falhou: {dump.stderr.decode()[:300]}")
        done = subprocess.run(
            ["docker", "exec", "-i", self._name, "pg_restore", "-f", "-"],
            input=dump.stdout,
            capture_output=True,
            check=False,
        )
        return done.stdout.decode().splitlines()


def open_scratch(image: str) -> AbstractContextManager[ScratchPostgres]:
    return ScratchPostgres(image)


def database_image(container: str = DATABASE_CONTAINER) -> str:
    done = subprocess.run(
        ["docker", "inspect", container, "--format", "{{.Config.Image}}"],
        capture_output=True,
        text=True,
        check=False,
    )
    return done.stdout.strip() if done.returncode == 0 else DEFAULT_POSTGRES_IMAGE


def running_containers() -> list[str]:
    out = _run(["docker", "ps", "--format", "{{json .Names}}"])
    return [json.loads(line) for line in out.splitlines() if line]
