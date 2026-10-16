"""O que é dado de teste, os tipos de recurso e as portas da limpeza (trocáveis nos testes)."""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

# Organizations de teste: o nome começa por um destes prefixos e o ID é um UUID (o `resourceId`).
TEST_ORGANIZATION_NAME = re.compile(r"^(conf|acme|loop|dup|chaos|e2e|probe|ver|cons)-")
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# Usuários de teste: o e-mail é de `example.com` e começa por um destes rótulos.
TEST_USER_EMAIL = re.compile(r"^(e2e|loop|conf|chaos|cons|sa\.test)[.-][^@]*@example\.com$")
MAIL_QUERIES = ("to:e2e-", "to:loop.", "to:conf.", "to:chaos.", "to:cons.", "to:sa.test.")

# Streams e prefixos de Subject por mensagem (`docs/NATS.md`); o `ACTION` é particionado pelo
# servidor e não dá para filtrar por recurso, então não é limpo aqui.
STREAM_SUBJECTS = (
    ("REQUESTED", "receiver.requested"),
    ("DESIRED", "manager.desired"),
    ("OBSERVED", "observer.observed"),
    ("RESULT", "executor.*"),
    ("UPDATED", "manager.updated"),
)


@dataclass(frozen=True, slots=True)
class Kind:
    """Um tipo de recurso: onde mora no SSOT e como aparece na mensageria."""

    module: str
    resource_type: str
    table: str
    support_tables: tuple[str, ...]
    manager_role: str
    maintenance_role: str
    label_field: str
    """Campo de `desired` que identifica a linha como de teste (e-mail, nome ou dono)."""


USERS = Kind(
    "core",
    "user",
    "core.user",
    ("core.user_outbox", "core.user_operation", "core.user_action_result"),
    "core_user_manager_login",
    "core_maintenance_login",
    "email",
)
SERVICES = Kind(
    "sum",
    "service",
    "sum.service",
    ("sum.service_outbox", "sum.service_operation", "sum.service_action_result"),
    "sum_service_manager_login",
    "sum_service_maintenance_login",
    "ownerUserId",
)
ORGANIZATIONS = Kind(
    "ipm",
    "organization",
    "ipm.organization",
    (
        "ipm.organization_outbox",
        "ipm.organization_operation",
        "ipm.organization_action_result",
    ),
    "ipm_organization_manager_login",
    "ipm_maintenance_login",
    "name",
)


@dataclass(frozen=True, slots=True)
class Row:
    """Uma linha do SSOT: o `resourceId` e o que a identifica como de teste (ou órfã)."""

    resource_id: str
    label: str


@dataclass(slots=True)
class Findings:
    """Tudo o que é resíduo de teste, por lugar."""

    zitadel_users: dict[str, str] = field(default_factory=lambda: {})
    zitadel_organizations: dict[str, str] = field(default_factory=lambda: {})
    user_rows: list[Row] = field(default_factory=lambda: [])
    service_rows: list[Row] = field(default_factory=lambda: [])
    organization_rows: list[Row] = field(default_factory=lambda: [])
    mails: int = 0

    def is_clean(self) -> bool:
        return not (
            self.zitadel_users
            or self.zitadel_organizations
            or self.user_rows
            or self.service_rows
            or self.organization_rows
            or self.mails
        )

    def lines(self) -> list[str]:
        found = [
            *(f"Zitadel usuário {rid}  {label}" for rid, label in self.zitadel_users.items()),
            *(
                f"Zitadel organização {rid}  {label}"
                for rid, label in self.zitadel_organizations.items()
            ),
            *(f"SSOT core.user {row.resource_id}  {row.label}" for row in self.user_rows),
            *(f"SSOT sum.service {row.resource_id}  {row.label}" for row in self.service_rows),
            *(
                f"SSOT ipm.organization {row.resource_id}  {row.label}"
                for row in self.organization_rows
            ),
        ]
        if self.mails:
            found.append(f"Mailpit {self.mails} mensagem(ns) de teste")
        return found

    def resource_ids(self) -> dict[Kind, set[str]]:
        """Os `resourceId` afetados, por tipo (para a mensageria)."""
        return {
            USERS: set(self.zitadel_users) | {row.resource_id for row in self.user_rows},
            SERVICES: {row.resource_id for row in self.service_rows},
            ORGANIZATIONS: set(self.zitadel_organizations)
            | {row.resource_id for row in self.organization_rows},
        }


# ---------------------------------------------------------------- portas (trocáveis nos testes)


class Identity(Protocol):
    def organizations(self) -> dict[str, str]:
        """ID → nome de todas as organizações do Zitadel."""
        ...

    def register_users(self) -> dict[str, str]:
        """ID → e-mail de todos os usuários da organização `register`."""
        ...

    def delete_organization(self, organization_id: str) -> None: ...

    def delete_user(self, user_id: str) -> None: ...


class Ssot(Protocol):
    def rows(self, kind: Kind) -> list[Row]:
        """Todas as linhas do tipo, com o rótulo que a identifica (e-mail, nome ou dono)."""
        ...

    def delete(self, kind: Kind, resource_ids: set[str]) -> None:
        """Apaga as linhas e o apoio (outbox, Operations e resultados) dos recursos."""
        ...


class Bus(Protocol):
    async def last_version(self, kind: Kind, resource_id: str) -> tuple[str, str] | None:
        """`(fase, resourceVersion)` da última mensagem `updated`, ou `None`."""
        ...

    async def request_deletion(self, kind: Kind, resource_id: str, version: str) -> None: ...

    async def removed(self, kind: Kind, resource_id: str) -> bool: ...

    async def purge(self, kind: Kind, resource_ids: set[str]) -> None: ...


class Mail(Protocol):
    def count(self) -> int: ...

    def delete(self) -> None: ...


@dataclass(frozen=True, slots=True)
class Ports:
    identity: Identity
    ssot: Ssot
    bus: Bus
    mail: Mail
    sleep: Callable[[float], Awaitable[None]] = asyncio.sleep
    clock: Callable[[], float] = time.monotonic


REMOVAL_WAIT_SECONDS = 45.0
POLL_SECONDS = 0.5
