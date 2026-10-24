"""O Manager grava o `userAccess` no `desired` e o mantém atual pelo rollout (decisão 0081)."""

from typing import Any

from ipm_organization.common.user_access import desired_user_access, grant_catalog
from ipm_organization.manager.domain.organization import OrganizationPolicy
from ipm_organization.manager.domain.policy import Request

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
