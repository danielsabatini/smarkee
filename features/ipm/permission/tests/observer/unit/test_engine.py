"""Testes unitários do Observer de `ipm.permission` (decisão 0083)."""

import json
from datetime import UTC, datetime

from ipm_permission.observer.domain.identity import IdentityProjectRole, ProviderError
from ipm_permission.observer.domain.observation import Drivers, observe
from ipm_permission.observer.engine.observer import Observer
from ipm_permission.observer.settings import PermissionObserverSettings

FIXED_NOW = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)


class FakeProjectRoles:
    def __init__(self, roles: dict[tuple[str, str], IdentityProjectRole] | None = None) -> None:
        self.roles = roles or {}
        self.fail = False

    async def get(self, permission_name: str) -> IdentityProjectRole | None:
        if self.fail:
            raise ProviderError("HTTP 503")
        module = permission_name.split(".", 1)[0]
        return self.roles.get((module, permission_name))


class FakePublisher:
    def __init__(self) -> None:
        self.published: list[tuple[str, bytes, str | None]] = []

    async def publish(self, subject: str, payload: bytes, *, message_id: str | None = None) -> None:
        self.published.append((subject, payload, message_id))


async def test_observe_returns_present_absent_and_unknown() -> None:
    fake = FakeProjectRoles(
        {
            ("ipm", "ipm.user.bind"): IdentityProjectRole(
                key="ipm.user.bind",
                display_name="Atribuir e alterar permissões.",
                group="ipm",
            )
        }
    )
    drivers = Drivers(project_roles=fake)

    present_obs = await observe(drivers, "ipm.user.bind")
    assert present_obs.presence == "present"
    assert present_obs.observed == {
        "name": "ipm.user.bind",
        "description": "Atribuir e alterar permissões.",
        "group": "ipm",
    }

    absent_obs = await observe(drivers, "ipm.user.export")
    assert absent_obs.presence == "absent"
    assert absent_obs.observed == {}

    fake.fail = True
    unknown_obs = await observe(drivers, "ipm.user.bind")
    assert unknown_obs.presence == "unknown"


async def test_observer_engine_publishes_observed_on_desired() -> None:
    fake = FakeProjectRoles(
        {
            ("ipm", "ipm.user.bind"): IdentityProjectRole(
                key="ipm.user.bind",
                display_name="Atribuir e alterar permissões.",
                group="ipm",
            )
        }
    )
    pub = FakePublisher()
    observer = Observer(
        Drivers(project_roles=fake),
        pub,
        PermissionObserverSettings(),
        clock=lambda: FIXED_NOW,
        identifiers=lambda: "01950000-0000-7000-8000-000000000001",
    )
    desired_msg = json.dumps(
        {
            "messageId": "01950000-0000-7000-8000-000000000010",
            "schemaVersion": "1.0",
            "messageType": "desired",
            "emitter": "manager",
            "module": "ipm",
            "resourceType": "permission",
            "resourceId": "perm-ipm-user-bind",
            "operation": "changed",
            "desiredGeneration": 1,
            "correlationId": "01950000-0000-7000-8000-000000000011",
            "causationId": "01950000-0000-7000-8000-000000000012",
            "occurredAt": FIXED_NOW.isoformat(),
            "publishedAt": FIXED_NOW.isoformat(),
            "data": {
                "lifecycle": "present",
                "reconciliation": "active",
                "name": "ipm.user.bind",
                "description": "Atribuir e alterar permissões.",
                "grantable": True,
                "deletionProtection": True,
            },
        }
    ).encode()
    await observer.on_message(desired_msg)
    assert len(pub.published) == 1
    subject, payload, _ = pub.published[0]
    assert subject == "observer.observed.ipm.permission.perm-ipm-user-bind.changed"
    decoded = json.loads(payload)
    assert decoded["presence"] == "present"
    assert decoded["data"]["name"] == "ipm.user.bind"
