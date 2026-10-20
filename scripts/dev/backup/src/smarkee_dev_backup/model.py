"""O que entra no backup do ambiente de dev e as portas do motor (trocáveis nos testes)."""

import re
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

# Bancos do PostgreSQL de dev: Zitadel e o SSOT (o gateway usa o etcd, e não o PostgreSQL).
# Lista fixa; o nome entra em comandos SQL, então só passa o que casa com `DATABASE_NAME`.
DATABASES = ("identity", "smarkee")
DATABASE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
# Volume com as chaves das service accounts e o PAT do login (gerados na primeira subida).
VOLUMES = ("identity-bootstrap",)
# Arquivos `.env` (fora do git). O `IDENTITY_MASTERKEY` deles é o que decifra o banco do Zitadel.
ENV_FILES = (
    "infrastructure/dev/messaging/.env",
    "infrastructure/dev/database/.env",
    "infrastructure/dev/gateway/.env",
    "infrastructure/dev/identity/.env",
    "features/core/account/.env",
    "features/ipm/organization/.env",
    "features/sum/service/.env",
)
FEATURE_DIRECTORIES = (
    "features/core/account",
    "features/ipm/organization",
    "features/sum/service",
)
INFRASTRUCTURE_DIRECTORY = "infrastructure/dev"
# Serviços da plataforma que mantêm conexão com os bancos restaurados.
INFRASTRUCTURE_DEPENDENTS = ("identity", "identity-login")

MANIFEST = "manifest.json"
CHECKSUMS = "SHA256SUMS"
FORMAT_VERSION = 1


class BackupError(Exception):
    """Falha esperada de uso ou de integridade, com mensagem para o operador."""


class Stack(Protocol):
    """O ambiente de dev em execução (banco, volumes e contêineres)."""

    def postgres_version(self) -> str: ...

    def dump_database(self, database: str, destination: Path) -> None: ...

    def dump_globals(self, destination: Path) -> None: ...

    def archive_volume(self, volume: str, destination: Path) -> None: ...

    def stop_components(self) -> None: ...

    def start_components(self) -> None: ...

    def restore_globals(self, source: Path) -> None: ...

    def restore_database(self, database: str, source: Path) -> None: ...

    def restore_volume(self, volume: str, source: Path) -> None: ...

    def remove_everything(self) -> None: ...


class Scratch(Protocol):
    """Um PostgreSQL descartável, usado só para provar que o backup restaura."""

    def restore_globals(self, source: Path) -> None: ...

    def restore_database(self, database: str, source: Path) -> None: ...

    def lines_of_file(self, source: Path) -> list[str]:
        """Conteúdo lógico (esquema e dados, em SQL) de um dump em arquivo."""
        ...

    def lines_of_database(self, database: str) -> list[str]:
        """Conteúdo lógico do banco restaurado, no mesmo formato de `lines_of_file`."""
        ...


@dataclass(frozen=True, slots=True)
class Ports:
    stack: Stack
    open_scratch: Callable[[], AbstractContextManager[Scratch]]
    repository: Path
    root: Path
    now: Callable[[], datetime]
    git_commit: Callable[[], str]
