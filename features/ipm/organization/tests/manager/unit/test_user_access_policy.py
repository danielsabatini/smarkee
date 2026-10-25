"""O Manager grava o `userAccess` no `desired` e o mantém atual pelo rollout (decisão 0081)."""

import json
from datetime import UTC, datetime
from typing import Any, cast

from ipm_organization.common.user_access import desired_user_access, grant_catalog
from ipm_organization.manager.domain.kind import organization_kind
from ipm_organization.manager.domain.organization import OrganizationPolicy
from ipm_organization.manager.domain.policy import Request
from ipm_organization.manager.handlers import user_access_rollout

USER_ACCESS = desired_user_access(
    user_executor_account_id="executor", user_observer_account_id="observer"
)
POLICY = OrganizationPolicy(USER_ACCESS)
CURRENT: dict[str, Any] = {
    "lifecycle": "present",
    "name": "acme",
    "platformAccess": "granted",
    "deletionProtection": True,
    "ownerAccountId": "owner-1",
}
OBSERVED_READY: dict[str, Any] = {
    "name": "acme",
    "platformAccess": "granted",
    "deletionProtection": True,
    "userAccess": {
        "grantPermissions": grant_catalog(),
        "administrators": [
            {"accountId": "executor", "permissions": ["ORG_USER_CREATOR", "PROJECT_GRANT_OWNER"]},
            {"accountId": "observer", "permissions": ["ORG_OWNER_VIEWER"]},
        ],
    },
}


def test_a_new_organization_is_born_ready_for_users() -> None:
    request = Request(
        "create", "op-1", "d" * 64, specification={"name": "acme", "platformAccess": "granted"}
    )
    desired = POLICY.desired_for_create(request, "owner-1")
    assert desired["userAccess"] == USER_ACCESS
    assert (
        POLICY.message_data(desired, "active")["userAccess"]["grantPermissions"] == grant_catalog()
    )


def test_the_rollout_adds_or_refreshes_the_user_access_only_when_it_changes() -> None:
    rolled = POLICY.rolled_out(CURRENT)  # Organization anterior à decisão 0081
    assert rolled == {**CURRENT, "userAccess": USER_ACCESS}
    assert rolled is not None
    assert POLICY.rolled_out(rolled) is None  # repetir não muda nada
    stale = {**CURRENT, "userAccess": {**USER_ACCESS, "grantPermissions": ["ipm.user.get"]}}
    assert POLICY.rolled_out(stale) == rolled
    assert POLICY.rolled_out({**CURRENT, "lifecycle": "absent"}) is None


def test_without_configured_accounts_nothing_is_rolled_out() -> None:
    assert OrganizationPolicy().rolled_out(CURRENT) is None


def test_convergence_requires_the_prepared_organization() -> None:
    desired = {**CURRENT, "userAccess": USER_ACCESS}
    assert POLICY.is_converged(desired, "present", OBSERVED_READY)
    unprepared = {key: value for key, value in OBSERVED_READY.items() if key != "userAccess"}
    assert not POLICY.is_converged(desired, "present", unprepared)
    revoked = {**desired, "platformAccess": "revoked"}
    assert POLICY.is_converged(revoked, "present", {**unprepared, "platformAccess": "revoked"})


def test_parse_and_desired_preserve_billing_account_id_on_create_and_update() -> None:
    created = POLICY.parse(
        "create",
        {
            "operationId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4f",
            "requestDigest": "d" * 64,
            "specification": {
                "name": "acme",
                "platformAccess": "granted",
                "billingAccountId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d99",
            },
        },
    )
    desired = POLICY.desired_for_create(created, "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d01")
    assert desired["billingAccountId"] == "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d99"

    updated = POLICY.parse(
        "update",
        {
            "operationId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d50",
            "requestDigest": "e" * 64,
            "resourceVersion": "2",
            "specification": {"billingAccountId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d88"},
        },
    )
    next_desired = POLICY.desired_for_update(desired, updated)
    assert next_desired["billingAccountId"] == "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d88"


async def test_permission_catalog_watcher_triggers_rollout_when_grantable_changes(
    monkeypatch: Any,
) -> None:
    rollouts: list[list[str]] = []
    kind = organization_kind(USER_ACCESS)
    policy = cast(OrganizationPolicy, kind.policy)

    async def fake_rollout(pool: Any, kind_arg: Any, **_: Any) -> int:
        rollouts.append(list(policy.grant_permissions))
        return 1

    monkeypatch.setattr(user_access_rollout, "roll_out_user_access", fake_rollout)
    watcher = user_access_rollout.PermissionCatalogWatcher(cast(Any, object()), kind)
    now = datetime(2026, 4, 21, 12, 0, tzinfo=UTC).isoformat()

    # Nova permissão grantable do módulo ipm dispara rollout com o catálogo expandido.
    data_add: dict[str, Any] = {
        "lifecycle": "present",
        "reconciliation": "active",
        "name": "ipm.team.create",
        "description": "Criar times",
        "grantable": True,
        "deletionProtection": False,
    }
    msg_add: dict[str, Any] = {
        "messageId": "01950000-0000-7000-8000-000000000001",
        "schemaVersion": "1.0",
        "messageType": "desired",
        "emitter": "manager",
        "module": "ipm",
        "resourceType": "permission",
        "resourceId": "perm-ipm-team-create",
        "operation": "changed",
        "desiredGeneration": 1,
        "requestedBy": "system",
        "correlationId": "01950000-0000-7000-8000-000000000002",
        "causationId": "01950000-0000-7000-8000-000000000003",
        "occurredAt": now,
        "publishedAt": now,
        "data": data_add,
    }
    assert await watcher.on_message(json.dumps(msg_add).encode()) == 1
    assert "ipm.team.create" in policy.grant_permissions
    assert len(rollouts) == 1

    # Repetir o mesmo desired não dispara novo rollout.
    assert await watcher.on_message(json.dumps(msg_add).encode()) == 0
    assert len(rollouts) == 1

    # Remover (lifecycle = absent) tira a permissão do catálogo e dispara rollout.
    msg_remove: dict[str, Any] = {
        **msg_add,
        "messageId": "01950000-0000-7000-8000-000000000004",
        "desiredGeneration": 2,
        "data": {**data_add, "lifecycle": "absent"},
    }
    assert await watcher.on_message(json.dumps(msg_remove).encode()) == 1
    assert "ipm.team.create" not in policy.grant_permissions
    assert len(rollouts) == 2
