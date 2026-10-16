"""Backup de dev: o que é gravado, a integridade, a prova de restauração e as travas."""

import json
import os
import stat
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pytest

from smarkee_dev_backup.adapters import DockerStack
from smarkee_dev_backup.engine import (
    check_integrity,
    create_backup,
    list_backups,
    normalize,
    reset,
    resolve,
    restore,
    verify,
)
from smarkee_dev_backup.main import refuse_outside_development
from smarkee_dev_backup.model import DATABASES, ENV_FILES, VOLUMES, BackupError, Ports, Scratch

MASTERKEY_ENV = "ZITADEL_MASTERKEY=0123456789abcdef0123456789abcdef\n"


@dataclass
class FakeStack:
    calls: list[str] = field(default_factory=lambda: [])

    def postgres_version(self) -> str:
        return "postgres (PostgreSQL) 18.6"

    def dump_database(self, database: str, destination: Path) -> None:
        destination.write_bytes(f"dump:{database}".encode())

    def dump_globals(self, destination: Path) -> None:
        destination.write_text("create role x;", encoding="utf-8")

    def archive_volume(self, volume: str, destination: Path) -> None:
        destination.write_bytes(f"volume:{volume}".encode())

    def stop_components(self) -> None:
        self.calls.append("stop")

    def start_components(self) -> None:
        self.calls.append("start")

    def restore_globals(self, source: Path) -> None:
        self.calls.append("globals")

    def restore_database(self, database: str, source: Path) -> None:
        self.calls.append(f"database:{database}")

    def restore_volume(self, volume: str, source: Path) -> None:
        self.calls.append(f"volume:{volume}")

    def remove_everything(self) -> None:
        self.calls.append("remove")


@dataclass
class FakeScratch:
    """Devolve o mesmo conteúdo do dump, ou um diferente para o banco `broken`."""

    broken: str | None = None

    def restore_globals(self, source: Path) -> None:
        return None

    def restore_database(self, database: str, source: Path) -> None:
        return None

    def lines_of_file(self, source: Path) -> list[str]:
        return ["-- Dumped by x", "\\restrict AAA", "insert 1", "insert 2"]

    def lines_of_database(self, database: str) -> list[str]:
        if database == self.broken:
            return ["\\restrict BBB", "insert 2"]
        return ["insert 2", "\\restrict BBB", "-- Dumped by y", "insert 1"]


def make_ports(tmp_path: Path, *, broken: str | None = None) -> tuple[Ports, FakeStack]:
    repository = tmp_path / "repository"
    for relative in ENV_FILES:
        (repository / relative).parent.mkdir(parents=True, exist_ok=True)
        (repository / relative).write_text(MASTERKEY_ENV, encoding="utf-8")
    stack = FakeStack()

    @contextmanager
    def open_scratch() -> Generator[Scratch]:
        yield FakeScratch(broken)

    ports = Ports(
        stack=stack,
        open_scratch=open_scratch,
        repository=repository,
        root=tmp_path / "backups",
        now=lambda: datetime(2026, 10, 16, 19, 30, 0, tzinfo=UTC),
        git_commit=lambda: "abcdef0123456789",
    )
    return ports, stack


def silent(_: str) -> None:
    return None


def test_backup_writes_databases_volumes_env_files_manifest_and_checksums(tmp_path: Path) -> None:
    ports, _ = make_ports(tmp_path)
    path = create_backup(ports, silent)
    assert path.name == "20261016T193000Z"
    for database in DATABASES:
        assert (path / "db" / f"{database}.dump").read_bytes() == f"dump:{database}".encode()
    assert (path / "db" / "globals.sql").is_file()
    for volume in VOLUMES:
        assert (path / "volumes" / f"{volume}.tar.gz").is_file()
    for relative in ENV_FILES:
        assert (path / "env" / relative).read_text(encoding="utf-8") == MASTERKEY_ENV
    manifest = json.loads((path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["gitCommit"] == "abcdef0123456789"
    assert manifest["databases"] == list(DATABASES)
    assert manifest["envFiles"] == list(ENV_FILES)
    assert check_integrity(path) == []


def test_backup_is_readable_only_by_the_owner(tmp_path: Path) -> None:
    ports, _ = make_ports(tmp_path)
    path = create_backup(ports, silent)
    for item in [path, *path.rglob("*")]:
        mode = stat.S_IMODE(item.stat().st_mode)
        assert mode & 0o077 == 0, f"{item} é acessível a outros usuários"
    assert stat.S_IMODE(ports.root.stat().st_mode) == 0o700


def test_missing_env_files_are_skipped(tmp_path: Path) -> None:
    ports, _ = make_ports(tmp_path)
    (ports.repository / ENV_FILES[0]).unlink()
    path = create_backup(ports, silent)
    assert json.loads((path / "manifest.json").read_text(encoding="utf-8"))["envFiles"] == list(
        ENV_FILES[1:]
    )


def test_backup_never_overwrites_an_existing_one(tmp_path: Path) -> None:
    ports, _ = make_ports(tmp_path)
    create_backup(ports, silent)
    with pytest.raises(BackupError):
        create_backup(ports, silent)


def test_integrity_detects_altered_missing_and_extra_files(tmp_path: Path) -> None:
    ports, _ = make_ports(tmp_path)
    path = create_backup(ports, silent)
    (path / "db" / "identity.dump").write_bytes(b"adulterado")
    (path / "db" / "gateway.dump").unlink()
    (path / "db" / "extra.dump").write_bytes(b"x")
    problems = check_integrity(path)
    assert "arquivo alterado: db/identity.dump" in problems
    assert "arquivo ausente: db/gateway.dump" in problems
    assert "arquivo fora da lista de somas: db/extra.dump" in problems


def test_normalize_drops_volatile_lines_and_ignores_row_order() -> None:
    first = normalize(["-- Dumped from x", "\\restrict A", "b", "a", "\\unrestrict A"])
    second = normalize(["a", "\\restrict Z", "b", "\\unrestrict Z"])
    assert first == second == ["a", "b"]


def test_verify_passes_when_every_restored_database_matches(tmp_path: Path) -> None:
    ports, _ = make_ports(tmp_path)
    path = create_backup(ports, silent)
    assert verify(ports, path, silent) == []


def test_verify_reports_the_database_that_does_not_restore_equal(tmp_path: Path) -> None:
    ports, _ = make_ports(tmp_path, broken="gateway")
    path = create_backup(ports, silent)
    problems = verify(ports, path, silent)
    assert len(problems) == 1
    assert problems[0].startswith("banco gateway:")


def test_verify_stops_at_an_integrity_problem(tmp_path: Path) -> None:
    ports, _ = make_ports(tmp_path)
    path = create_backup(ports, silent)
    (path / "db" / "smarkee.dump").write_bytes(b"adulterado")
    assert verify(ports, path, silent) == ["arquivo alterado: db/smarkee.dump"]


def test_resolve_picks_the_latest_or_the_named_backup(tmp_path: Path) -> None:
    ports, _ = make_ports(tmp_path)
    first = create_backup(ports, silent)
    second_ports = Ports(
        stack=ports.stack,
        open_scratch=ports.open_scratch,
        repository=ports.repository,
        root=ports.root,
        now=lambda: datetime(2026, 10, 17, 8, 0, 0, tzinfo=UTC),
        git_commit=ports.git_commit,
    )
    second = create_backup(second_ports, silent)
    assert list_backups(ports.root) == [first, second]
    assert resolve(ports.root, None) == second
    assert resolve(ports.root, first.name) == first
    for invalid in ("nao-existe", "../backups"):
        with pytest.raises(BackupError):
            resolve(ports.root, invalid)


def test_restore_without_apply_changes_nothing(tmp_path: Path) -> None:
    ports, stack = make_ports(tmp_path)
    path = create_backup(ports, silent)
    assert restore(ports, path, apply_changes=False, say=silent) == 0
    assert stack.calls == []


def test_restore_applies_in_order_and_copies_only_missing_env_files(tmp_path: Path) -> None:
    ports, stack = make_ports(tmp_path)
    path = create_backup(ports, silent)
    missing = ports.repository / ENV_FILES[0]
    missing.unlink()
    assert restore(ports, path, apply_changes=True, say=silent) == 0
    assert stack.calls == [
        "stop",
        "globals",
        *[f"database:{database}" for database in DATABASES],
        *[f"volume:{volume}" for volume in VOLUMES],
        "start",
    ]
    assert missing.read_text(encoding="utf-8") == MASTERKEY_ENV
    assert stat.S_IMODE(missing.stat().st_mode) == 0o600


def test_restore_refuses_an_env_file_that_differs_from_the_backup(tmp_path: Path) -> None:
    ports, stack = make_ports(tmp_path)
    path = create_backup(ports, silent)
    (ports.repository / "infrastructure/dev/identity/.env").write_text(
        "ZITADEL_MASTERKEY=outra\n", encoding="utf-8"
    )
    assert restore(ports, path, apply_changes=True, say=silent) == 1
    assert stack.calls == []


def test_restore_refuses_a_backup_that_does_not_verify(tmp_path: Path) -> None:
    ports, stack = make_ports(tmp_path, broken="identity")
    path = create_backup(ports, silent)
    assert restore(ports, path, apply_changes=True, say=silent) == 1
    assert stack.calls == []


def test_reset_without_apply_removes_nothing_and_writes_no_backup(tmp_path: Path) -> None:
    ports, stack = make_ports(tmp_path)
    assert reset(ports, apply_changes=False, say=silent) == 0
    assert stack.calls == []
    assert list_backups(ports.root) == []


def test_reset_removes_the_environment_only_after_a_verified_backup(tmp_path: Path) -> None:
    ports, stack = make_ports(tmp_path)
    assert reset(ports, apply_changes=True, say=silent) == 0
    assert stack.calls == ["remove"]
    assert len(list_backups(ports.root)) == 1


def test_reset_keeps_the_environment_when_the_backup_is_not_confirmed(tmp_path: Path) -> None:
    ports, stack = make_ports(tmp_path, broken="smarkee")
    assert reset(ports, apply_changes=True, say=silent) == 1
    assert stack.calls == []


def test_other_environments_are_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in [key for key in os.environ if key.startswith("BACKUP_")]:
        monkeypatch.delenv(name)
    refuse_outside_development()
    monkeypatch.setenv("BACKUP_DATABASE_CONTAINER", "database.prd")
    with pytest.raises(SystemExit):
        refuse_outside_development()


def test_database_names_are_validated_before_reaching_sql(tmp_path: Path) -> None:
    stack = DockerStack(tmp_path)
    with pytest.raises(BackupError):
        stack.dump_database("x; drop database smarkee", tmp_path / "out")
    with pytest.raises(BackupError):
        stack.restore_database('x"; drop database smarkee; --', tmp_path / "in")
