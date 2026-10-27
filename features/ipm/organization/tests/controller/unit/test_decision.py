"""Testes unitários da decisão pura de reconciliação no Controller (decisão 0096)."""

from ipm_organization.controller.domain.decision import DesiredState, ObservedState, decide


def test_missing_organization_is_created() -> None:
    desired = DesiredState(lifecycle="present", name="acme", platform_access="granted")
    observed = ObservedState(presence="absent")
    decision = decide(desired, observed)
    assert decision is not None
    assert decision.operation == "create"
    assert decision.reason == "resource_absent"
    assert decision.fields == ("lifecycle",)


def test_converged_organization_requires_no_action() -> None:
    desired = DesiredState(
        lifecycle="present", name="acme", platform_access="granted", deletion_protection=True
    )
    observed = ObservedState(
        presence="present", name="acme", platform_access="granted", deletion_protection=True
    )
    assert decide(desired, observed) is None


def test_name_drift_triggers_update() -> None:
    desired = DesiredState(
        lifecycle="present", name="new-name", platform_access="granted", deletion_protection=True
    )
    observed = ObservedState(
        presence="present", name="old-name", platform_access="granted", deletion_protection=True
    )
    decision = decide(desired, observed)
    assert decision is not None
    assert decision.operation == "update"
    assert "name" in decision.fields


def test_platform_access_drift_triggers_update() -> None:
    desired = DesiredState(
        lifecycle="present", name="acme", platform_access="revoked", deletion_protection=True
    )
    observed = ObservedState(
        presence="present", name="acme", platform_access="granted", deletion_protection=True
    )
    decision = decide(desired, observed)
    assert decision is not None
    assert decision.operation == "update"
    assert "platformAccess" in decision.fields


def test_lifecycle_absent_triggers_delete() -> None:
    desired = DesiredState(lifecycle="absent", name="acme", platform_access="granted")
    observed = ObservedState(presence="present", name="acme", platform_access="granted")
    decision = decide(desired, observed)
    assert decision is not None
    assert decision.operation == "delete"
    assert decision.reason == "lifecycle_absent"


def test_already_absent_requires_no_action() -> None:
    desired = DesiredState(lifecycle="absent", name="acme", platform_access="granted")
    observed = ObservedState(presence="absent")
    assert decide(desired, observed) is None


def test_unknown_presence_defers_decision() -> None:
    desired = DesiredState(lifecycle="present", name="acme", platform_access="granted")
    observed = ObservedState(presence="unknown")
    assert decide(desired, observed) is None
