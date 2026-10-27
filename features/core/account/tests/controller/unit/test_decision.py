"""Decisão pura de reconciliação da Account (decisão 0096): ação a executar, ou nenhuma."""

from typing import Any

import pytest

from core_account.controller.domain.convergence import check_is_converged
from core_account.controller.domain.decision import DesiredState, ObservedState, decide

PERMISSIONS = frozenset({"core.account.get", "core.account.delete"})


def desired(**changes: Any) -> DesiredState:
    base: dict[str, Any] = {
        "lifecycle": "present",
        "platform_access": "granted",
        "platform_permissions": PERMISSIONS,
        "deletion_protection": True,
    }
    return DesiredState(**{**base, **changes})


def observed(**changes: Any) -> ObservedState:
    base: dict[str, Any] = {
        "presence": "present",
        "platform_access": "granted",
        "platform_permissions": PERMISSIONS,
        "deletion_protection": True,
    }
    return ObservedState(**{**base, **changes})


def test_missing_account_is_created() -> None:
    decision = decide(desired(), ObservedState(presence="absent"))
    assert decision is not None
    assert (decision.operation, decision.reason) == ("create", "resource_absent")


def test_converged_account_requires_no_action() -> None:
    assert decide(desired(), observed()) is None


def test_extra_observed_permissions_are_not_drift() -> None:
    extra = observed(platform_permissions=PERMISSIONS | {"core.account.admin"})
    assert decide(desired(), extra) is None


@pytest.mark.parametrize(
    ("changes", "field"),
    [
        ({"platform_access": "revoked"}, "platformAccess"),
        ({"platform_permissions": frozenset({"core.account.get"})}, "platformPermissions"),
        ({"deletion_protection": False}, "deletionProtection"),
        ({"deletion_protection": None}, "deletionProtection"),
    ],
)
def test_each_managed_field_drift_triggers_update(changes: dict[str, Any], field: str) -> None:
    decision = decide(desired(), observed(**changes))
    assert decision is not None
    assert (decision.operation, decision.fields) == ("update", (field,))


def test_absent_lifecycle_deletes_only_what_exists() -> None:
    decision = decide(desired(lifecycle="absent"), observed())
    assert decision is not None and decision.operation == "delete"
    assert decide(desired(lifecycle="absent"), ObservedState(presence="absent")) is None


def test_unknown_observation_never_authorizes_an_action() -> None:
    assert decide(desired(), ObservedState(presence="unknown")) is None
    assert decide(desired(lifecycle="absent"), ObservedState(presence="unknown")) is None


def test_decision_and_convergence_agree() -> None:
    wanted = {
        "lifecycle": "present",
        "platformAccess": "granted",
        "platformPermissions": sorted(PERMISSIONS),
        "deletionProtection": True,
    }
    seen = {
        "platformAccess": "granted",
        "platformPermissions": sorted(PERMISSIONS),
        "deletionProtection": True,
    }
    assert check_is_converged(wanted, "present", seen)
    assert decide(desired(), observed()) is None
    seen["deletionProtection"] = False
    assert not check_is_converged(wanted, "present", seen)
    assert decide(desired(), observed(deletion_protection=False)) is not None
