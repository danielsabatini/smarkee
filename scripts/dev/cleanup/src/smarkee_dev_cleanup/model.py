"""O que é dado de teste, os tipos de recurso e as portas da limpeza (trocáveis nos testes)."""

import asyncio
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Protocol

# Billing Accounts de teste (`bsm.account`): o `displayName` começa por um dos prefixos dos testes
# de conformidade, loop ou integração, ou é `Account ` ou `Renamed ` seguido de 10 hexadecimais,
# ou a conta inicial `Free Tier` gerada para contas de teste.
TEST_BILLING_ACCOUNT_NAME = re.compile(
    r"^(?:(?:Test|Conf|Acme|Loop|Dup|Chaos|E2E|Probe|Ver|cons)[ -]|"
    r"test-|"
    r"(?:Account|Renamed) [0-9a-f]{10}$|Free Tier$)"
)
# Organizations de teste: o nome começa por um destes prefixos, ou é `org-` ou `renamed-` mais 10
# hexadecimais (os nomes dos testes de integração do Manager da Organization: o padrão e o do teste
# de renomear), e o ID é um UUID (o `resourceId`) ou ID com prefixo de teste (`ctl-`, `test-`).
TEST_ORGANIZATION_NAME = re.compile(
    r"^(?:(?:conf|acme|loop|dup|chaos|e2e|probe|ver|cons|test|ctl)-|"
    r"(?:org|renamed|race-name)-[0-9a-f]{10}$)"
)
# Roles de teste (`ipm.role`): nomes dos testes e2e da feature (`test.role` ou `test.chaos` mais 6
# hexadecimais, `bsm.e2eRole` ou `acme.`). As Roles predefinidas da plataforma nunca casam.
TEST_ROLE_NAME = re.compile(
    r"^(?:test\.(?:role|chaos)[0-9a-f]{6}|bsm\.e2eRole[0-9a-f]{6}|acme\..+)$"
)
# Grupos de teste (`ipm.group`): nomes dos testes e2e da feature (`test-group-`, `test-loop-` ou
# `test-chaos-` seguido de 6 a 8 hexadecimais).
TEST_GROUP_NAME = re.compile(r"^test-(?:group|loop|chaos)-[0-9a-f]{6,8}$")
# Service accounts de teste (`ipm.serviceaccount`, decisão 0094): nomes dos testes da feature
# (`sa`, `loop`, `conf`, `chaos`, `cons` ou `test` mais `-` e 6 a 10 hexadecimais,
# ou `ci-live-test`). Nomes reais (`ci-deploy`) nunca casam.
TEST_SERVICEACCOUNT_NAME = re.compile(
    r"^(?:(?:sa|loop|conf|chaos|cons|test)-[0-9a-f]{6,10}|ci-live-test)$"
)
# Permissions de teste (`ipm.permission`): nomes dos testes e2e da feature (`bsm.e2e.p` mais 7
# hexadecimais, `bsm.chaos.c` mais 5, o antigo `e2e.test.p` mais 6 ou 7, ou `test.perm.`).
# As permissions reais da plataforma (`ipm.user.get`...) nunca casam.
TEST_PERMISSION_NAME = re.compile(
    r"^(?:bsm\.e2e\.p[0-9a-f]{7}|bsm\.chaos\.c[0-9a-f]{5}|e2e\.test\.p[0-9a-f]{6,7}|"
    r"test\.perm\.[a-z0-9]+)$"
)
UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
TEST_ID_PREFIX = re.compile(r"^(?:ctl|test|loop|conf|chaos|cons)-[0-9a-f]{6,10}$")
SYSTEM_ORGANIZATION_NAMES = frozenset({"smarkee", "core", "register", "operator"})
# Usuários de teste: o e-mail é de `example.com` e começa por um destes rótulos, ou é `ana.` ou
# `dup.` mais 10 hexadecimais (os e-mails dos testes de integração do Manager da Account). `ana@` e
# `ana.<nome>@` sem os 10 hexadecimais não são de teste.
TEST_USER_EMAIL = re.compile(
    r"^(?:(?:test|account|e2e|loop|conf|chaos|cons|sa\.test|repo|dup|u|race|ctl|shared)[.-][^@]*|"
    r"(?:ana|dup)\.[0-9a-f]{10})@example\.com$"
)
MAIL_QUERIES = (
    "to:test-",
    "to:account-",
    "to:e2e-",
    "to:loop.",
    "to:conf.",
    "to:chaos.",
    "to:cons.",
    "to:sa.test.",
    "to:repo-",
    "to:dup-",
    "to:u-",
    "to:race-",
    "to:ctl-",
    "to:shared-",
)

# Streams e prefixos de Subject por mensagem (`docs/messaging/NATS.md`, decisão 0101).
STREAM_SUBJECTS = (
    ("DESIRED", "desired"),
    ("UPDATED", "updated"),
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
    delete_role: str | None = None
    """Papel de login que apaga a linha, quando não é o do Manager (o Controller, decisão 0096)."""
    removable_through_requested: bool = True
    """Tem Receiver e Manager: a remoção pode ser pedida por `requested`. A API síncrona (decisão
    0098) não tem esse caminho: a limpeza apaga direto, e o Zitadel sai com a Organization."""


ACCOUNTS = Kind(
    "core",
    "account",
    "core.account",
    ("core.account_outbox", "core.account_idempotency"),
    "core_account_api_login",
    "core_maintenance_login",
    "email",
    deletion_protected=True,
    delete_role="core_account_controller_login",
    removable_through_requested=False,
)
SERVICES = Kind(
    "sum",
    "service",
    "sum.service",
    ("sum.service_outbox", "sum.service_idempotency"),
    "sum_service_api_login",
    "sum_service_maintenance_login",
    "ownerAccountId",
    delete_role="sum_service_controller_login",
    removable_through_requested=False,
)
ORGANIZATIONS = Kind(
    "ipm",
    "organization",
    "ipm.organization",
    ("ipm.organization_outbox", "ipm.organization_idempotency"),
    "ipm_organization_api_login",
    "ipm_maintenance_login",
    "name",
    deletion_protected=True,
    delete_role="ipm_organization_controller_login",
    removable_through_requested=False,
)

# Usuários da Organization (decisão 0077): nascem desprotegidos, mas podem ter sido protegidos.
ORGANIZATION_USERS = Kind(
    "ipm",
    "user",
    "ipm.user",
    ("ipm.user_outbox", "ipm.user_idempotency"),
    "ipm_user_api_login",
    "ipm_maintenance_login",
    "email",
    deletion_protected=True,
    delete_role="ipm_user_controller_login",
    removable_through_requested=False,
)
BILLING_ACCOUNTS = Kind(
    "bsm",
    "account",
    "bsm.account",
    ("bsm.account_outbox", "bsm.account_idempotency"),
    "bsm_account_api_login",
    "bsm_maintenance_login",
    "displayName",
    deletion_protected=True,
    removable_through_requested=False,
)
# Permissions atômicas (decisões 0084 e 0098): existem só no SSOT, como role de projeto no Zitadel;
# não têm plano de dados. A API síncrona não tem `requested`: a limpeza apaga a linha direto com o
# papel do Controller, e a role de projeto sai pela remoção pela API (e2e). Nascem protegidas.
PERMISSIONS = Kind(
    "ipm",
    "permission",
    "ipm.permission",
    ("ipm.permission_outbox", "ipm.permission_idempotency"),
    "ipm_permission_api_login",
    "ipm_maintenance_login",
    "name",
    deletion_protected=True,
    delete_role="ipm_permission_controller_login",
    removable_through_requested=False,
)
# Roles compostas (decisões 0083 e 0098): só no SSOT. A API síncrona apaga a linha (tem DELETE) e
# publica o tombstone; não há `requested`. Nascem protegidas contra exclusão.
ROLES = Kind(
    "ipm",
    "role",
    "ipm.role",
    ("ipm.role_outbox", "ipm.role_idempotency"),
    "ipm_role_api_login",
    "ipm_maintenance_login",
    "name",
    deletion_protected=True,
    removable_through_requested=False,
)
# Grupos da Organization (decisões 0088 e 0098): só no SSOT. A API síncrona apaga a linha e publica
# o tombstone; não há `requested`.
GROUPS = Kind(
    "ipm",
    "group",
    "ipm.group",
    ("ipm.group_outbox", "ipm.group_idempotency"),
    "ipm_group_api_login",
    "ipm_maintenance_login",
    "name",
    deletion_protected=True,
    removable_through_requested=False,
)
# Identidades de máquina da Organization (decisão 0094): só no SSOT; a chave pública mora no Zitadel
# e sai com o usuário (o Executor remove o machine user). Nascem protegidas contra exclusão.
SERVICEACCOUNTS = Kind(
    "ipm",
    "serviceaccount",
    "ipm.serviceaccount",
    ("ipm.serviceaccount_outbox", "ipm.serviceaccount_idempotency"),
    "ipm_serviceaccount_api_login",
    "ipm_maintenance_login",
    "name",
    deletion_protected=True,
    delete_role="ipm_serviceaccount_controller_login",
    removable_through_requested=False,
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
    billing_account_rows: list[Row] = field(default_factory=lambda: [])
    service_rows: list[Row] = field(default_factory=lambda: [])
    organization_rows: list[Row] = field(default_factory=lambda: [])
    organization_user_rows: list[Row] = field(default_factory=lambda: [])
    role_rows: list[Row] = field(default_factory=lambda: [])
    permission_rows: list[Row] = field(default_factory=lambda: [])
    group_rows: list[Row] = field(default_factory=lambda: [])
    serviceaccount_rows: list[Row] = field(default_factory=lambda: [])
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
            or self.billing_account_rows
            or self.service_rows
            or self.organization_rows
            or self.organization_user_rows
            or self.role_rows
            or self.permission_rows
            or self.group_rows
            or self.serviceaccount_rows
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
            *(
                f"SSOT bsm.account {row.resource_id}  {row.label}"
                for row in self.billing_account_rows
            ),
            *(f"SSOT sum.service {row.resource_id}  {row.label}" for row in self.service_rows),
            *(
                f"SSOT ipm.organization {row.resource_id}  {row.label}"
                for row in self.organization_rows
            ),
            *(
                f"SSOT ipm.user {row.resource_id}  {row.label}"
                for row in self.organization_user_rows
            ),
            *(f"SSOT ipm.role {row.resource_id}  {row.label}" for row in self.role_rows),
            *(
                f"SSOT ipm.permission {row.resource_id}  {row.label}"
                for row in self.permission_rows
            ),
            *(f"SSOT ipm.group {row.resource_id}  {row.label}" for row in self.group_rows),
            *(
                f"SSOT ipm.serviceaccount {row.resource_id}  {row.label}"
                for row in self.serviceaccount_rows
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
            BILLING_ACCOUNTS: {row.resource_id for row in self.billing_account_rows}
            | self._history_ids(BILLING_ACCOUNTS)
            | self.message_orphans.get(BILLING_ACCOUNTS, set()),
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
            ROLES: {row.resource_id for row in self.role_rows}
            | self._history_ids(ROLES)
            | self.message_orphans.get(ROLES, set()),
            PERMISSIONS: {row.resource_id for row in self.permission_rows}
            | self._history_ids(PERMISSIONS)
            | self.message_orphans.get(PERMISSIONS, set()),
            GROUPS: {row.resource_id for row in self.group_rows}
            | self._history_ids(GROUPS)
            | self.message_orphans.get(GROUPS, set()),
            SERVICEACCOUNTS: {row.resource_id for row in self.serviceaccount_rows}
            | self._history_ids(SERVICEACCOUNTS)
            | self.message_orphans.get(SERVICEACCOUNTS, set()),
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
