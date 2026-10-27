"""Testes unitários da decisão pura de reconciliação do usuário (decisão 0096)."""

from typing import Any

from ipm_user.controller.domain.convergence import check_is_converged
from ipm_user.controller.domain.decision import DesiredState, ObservedState, decide

PERMISSIONS = frozenset({"ipm.user.get"})


def desired(**changes: Any) -> DesiredState:
    base: dict[str, Any] = {
        "lifecycle": "present",
        "permissions": PERMISSIONS,
        "deletion_protection": False,
    }
    return DesiredState(**{**base, **changes})


def observed(**changes: Any) -> ObservedState:
    base: dict[str, Any] = {
        "presence": "present",
        "permissions": PERMISSIONS,
        "deletion_protection": False,
    }
    return ObservedState(**{**base, **changes})


def test_missing_user_is_created() -> None:
    decision = decide(desired(), ObservedState(presence="absent"))
    assert decision is not None
    assert (decision.operation, decision.reason) == ("create", "resource_absent")


def test_converged_user_requires_no_action() -> None:
    assert decide(desired(), observed()) is None


def test_each_managed_field_drift_triggers_update() -> None:
    cases = {
        "permissions": observed(permissions=frozenset()),
        "deletionProtection": observed(deletion_protection=True),
    }
    for field, state in cases.items():
        decision = decide(desired(), state)
        assert decision is not None
        assert decision.operation == "update"
        assert decision.fields == (field,)


def test_missing_protection_metadata_is_a_drift() -> None:
    decision = decide(desired(), observed(deletion_protection=None))
    assert decision is not None
    assert decision.fields == ("deletionProtection",)


def test_lifecycle_absent_deletes_only_what_exists() -> None:
    decision = decide(desired(lifecycle="absent"), observed())
    assert decision is not None
    assert decision.operation == "delete"
    assert decide(desired(lifecycle="absent"), ObservedState(presence="absent")) is None


def test_unknown_presence_defers_decision() -> None:
    assert decide(desired(), ObservedState(presence="unknown")) is None


def test_check_is_converged_matches_the_decision() -> None:
    desired_doc = {
        "lifecycle": "present",
        "permissions": ["ipm.user.get"],
        "deletionProtection": False,
    }
    observed_doc = {"permissions": ["ipm.user.get"], "deletionProtection": False}
    assert check_is_converged(desired_doc, "present", observed_doc) is True
    assert check_is_converged(desired_doc, "present", {**observed_doc, "permissions": []}) is False
    assert check_is_converged(desired_doc, "present", {"permissions": ["ipm.user.get"]}) is False
    assert check_is_converged({"lifecycle": "absent"}, "absent", None) is True
    assert check_is_converged(desired_doc, "unknown", None) is False
