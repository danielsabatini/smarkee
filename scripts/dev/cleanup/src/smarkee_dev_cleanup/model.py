"""O que é dado de teste, os tipos de recurso e as portas da limpeza (trocáveis nos testes)."""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

# Organizations de teste: o nome começa por um destes prefixos, ou é `org-` ou `renamed-` mais 10
# hexadecimais (os nomes dos testes de integração do Manager da Organization: o padrão e o do teste
# de renomear), e o ID é um UUID (o `resourceId`). Esses dois prefixos sem os 10 hexadecimais não
# são de teste.
TEST_ORGANIZATION_NAME = re.compile(
    r"^(?:(?:conf|acme|loop|dup|chaos|e2e|probe|ver|cons)-|(?:org|renamed)-[0-9a-f]{10}$)"
)
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
# Usuários de teste: o e-mail é de `example.com` e começa por um destes rótulos, ou é `ana.` ou
# `dup.` mais 10 hexadecimais (os e-mails dos testes de integração do Manager da Account). `ana@` e
# `ana.<nome>@` sem os 10 hexadecimais não são de teste.
TEST_USER_EMAIL = re.compile(
    r"^(?:(?:e2e|loop|conf|chaos|cons|sa\.test)[.-][^@]*|(?:ana|dup)\.[0-9a-f]{10})@example\.com$"
)
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
    deletion_protected: bool = False
    """O tipo pode estar protegido contra exclusão (decisão 0043): a limpeza desprotege antes."""


ACCOUNTS = Kind(
    "core",
    "account",
    "core.account",
    ("core.account_outbox", "core.account_operation", "core.account_action_result"),
    "core_account_manager_login",
    "core_maintenance_login",
    "email",
    deletion_protected=True,
)
SERVICES = Kind(
    "sum",
    "service",
    "sum.service",
    ("sum.service_outbox", "sum.service_operation", "sum.service_action_result"),
    "sum_service_manager_login",
    "sum_service_maintenance_login",
    "ownerAccountId",
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
    deletion_protected=True,
)

# Usuários da Organization (decisão 0077): nascem desprotegidos, mas podem ter sido protegidos.
ORGANIZATION_USERS = Kind(
    "ipm",
    "user",
    "ipm.user",
    ("ipm.user_outbox", "ipm.user_operation", "ipm.user_action_result"),
    "ipm_user_manager_login",
    "ipm_maintenance_login",
    "email",
    deletion_protected=True,
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
    account_rows: list[Row] = field(default_factory=lambda: [])
    service_rows: list[Row] = field(default_factory=lambda: [])
    organization_rows: list[Row] = field(default_factory=lambda: [])
    organization_user_rows: list[Row] = field(default_factory=lambda: [])
    history: dict[Kind, list[Row]] = field(default_factory=lambda: {})
    """Histórico (outbox, Operations e resultados) de recursos de teste já removidos."""
    kept_history: dict[Kind, int] = field(default_factory=lambda: {})
    """Recursos removidos cujo histórico NÃO é reconhecido como de teste: ficam como estão."""
    message_orphans: dict[Kind, set[str]] = field(default_factory=lambda: {})
    """Só no modo `--orphans`: recursos com mensagens nos Streams e sem linha principal."""
    mails: int = 0

    def is_clean(self) -> bool:
        return not (
            self.zitadel_users
            or self.zitadel_organizations
            or self.account_rows
            or self.service_rows
            or self.organization_rows
            or self.organization_user_rows
            or any(self.history.values())
            or any(self.message_orphans.values())
            or self.mails
        )

    def kept_history_note(self) -> str | None:
        """Aviso do histórico mantido (não é resíduo de teste identificável), ou `None`."""
        kept = {kind: count for kind, count in self.kept_history.items() if count}
        if not kept:
            return None
        parts = ", ".join(
            f"{count} de {kind.module}.{kind.resource_type}" for kind, count in kept.items()
        )
        return f"Histórico mantido (removidos que não são de teste): {parts}."

    def lines(self) -> list[str]:
        found = [
            *(f"Zitadel usuário {rid}  {label}" for rid, label in self.zitadel_users.items()),
            *(
                f"Zitadel organização {rid}  {label}"
                for rid, label in self.zitadel_organizations.items()
            ),
            *(f"SSOT core.account {row.resource_id}  {row.label}" for row in self.account_rows),
            *(f"SSOT sum.service {row.resource_id}  {row.label}" for row in self.service_rows),
            *(
                f"SSOT ipm.organization {row.resource_id}  {row.label}"
                for row in self.organization_rows
            ),
            *(
                f"SSOT ipm.user {row.resource_id}  {row.label}"
                for row in self.organization_user_rows
            ),
        ]
        found.extend(
            f"SSOT histórico de {len(rows)} recurso(s) de teste removido(s) de "
            f"{kind.module}.{kind.resource_type} (outbox, Operations e resultados)"
            for kind, rows in self.history.items()
            if rows
        )
        found.extend(
            f"NATS mensagens de {len(ids)} recurso(s) sem linha principal de "
            f"{kind.module}.{kind.resource_type}"
            for kind, ids in self.message_orphans.items()
            if ids
        )
        if self.mails:
            found.append(f"Mailpit {self.mails} mensagem(ns) de teste")
        return found

    def resource_ids(self) -> dict[Kind, set[str]]:
        """Os `resourceId` afetados, por tipo (para a mensageria)."""
        return {
            ACCOUNTS: set(self.zitadel_users)
            | {row.resource_id for row in self.account_rows}
            | self._history_ids(ACCOUNTS)
            | self.message_orphans.get(ACCOUNTS, set()),
            SERVICES: {row.resource_id for row in self.service_rows}
            | self._history_ids(SERVICES)
            | self.message_orphans.get(SERVICES, set()),
            ORGANIZATIONS: set(self.zitadel_organizations)
            | {row.resource_id for row in self.organization_rows}
            | self._history_ids(ORGANIZATIONS)
            | self.message_orphans.get(ORGANIZATIONS, set()),
            ORGANIZATION_USERS: {row.resource_id for row in self.organization_user_rows}
            | self._history_ids(ORGANIZATION_USERS)
            | self.message_orphans.get(ORGANIZATION_USERS, set()),
        }

    def _history_ids(self, kind: Kind) -> set[str]:
        return {row.resource_id for row in self.history.get(kind, [])}


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

    def unprotected_version(self, kind: Kind, resource_id: str) -> str | None:
        """`resourceVersion` da linha desprotegida e com a geração confirmada pelo loop, ou `None`.

        A proteção percorre o loop como qualquer alteração (decisão 0072): só conclui quando a
        observação confirma a nova geração (`observed_generation = desired_generation`).
        """
        ...

    def history(self, kind: Kind) -> list[Row]:
        """Recursos com outbox, Operation ou resultado, com o rótulo do outbox (`''` se não há).

        Inclui os que ainda têm linha principal; quem decide o que é órfão é o chamador.
        """
        ...

    def delete(self, kind: Kind, resource_ids: set[str]) -> None:
        """Apaga as linhas e o apoio (outbox, Operations e resultados) dos recursos."""
        ...


class Bus(Protocol):
    async def last_version(self, kind: Kind, resource_id: str) -> tuple[str, str] | None:
        """`(fase, resourceVersion)` da última mensagem `updated`, ou `None`."""
        ...

    async def request_unprotection(self, kind: Kind, resource_id: str, version: str) -> None: ...

    async def request_deletion(self, kind: Kind, resource_id: str, version: str) -> None: ...

    async def removed(self, kind: Kind, resource_id: str) -> bool: ...

    async def purge(self, kind: Kind, resource_ids: set[str]) -> None: ...

    async def orphan_messages(self, live: dict[Kind, set[str]]) -> dict[Kind, set[str]]:
        """`resourceId` com mensagens nos Streams que não estão em `live` (sem linha principal)."""
        ...


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
UNPROTECTION_WAIT_SECONDS = 20.0
POLL_SECONDS = 0.5
