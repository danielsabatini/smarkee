"""Decisão pura de reconciliação da ligação de serviço (decisões 0033 e 0096): ação ou nenhuma."""

from typing import Any

from sum_service.controller.domain.decision import DesiredState, ObservedState, decide

WANTED = frozenset({"ipm.organization.get", "ipm.organization.create"})
MANAGED = WANTED | {"ipm.organization.delete"}


def desired(**changes: Any) -> DesiredState:
    base: dict[str, Any] = {
        "lifecycle": "present",
        "service_permissions": WANTED,
        "managed_permissions": MANAGED,
    }
    return DesiredState(**{**base, **changes})


def observed(**changes: Any) -> ObservedState:
    base: dict[str, Any] = {"presence": "present", "service_permissions": WANTED}
    return ObservedState(**{**base, **changes})


def test_a_converged_link_needs_no_action() -> None:
    assert decide(desired(), observed()) is None


def test_missing_permissions_are_enabled() -> None:
    decision = decide(desired(), observed(service_permissions=frozenset({"ipm.organization.get"})))
    assert decision is not None
    assert (decision.operation, decision.reason) == ("enable", "drift")
    assert decision.fields == ("servicePermissions",)


def test_a_managed_permission_that_is_no_longer_wanted_is_revoked_by_enable() -> None:
    decision = decide(desired(), observed(service_permissions=WANTED | {"ipm.organization.delete"}))
    assert decision is not None
    assert (decision.operation, decision.fields) == ("enable", ("managedPermissions",))


def test_permissions_outside_the_managed_ones_are_never_touched() -> None:
    assert decide(desired(), observed(service_permissions=WANTED | {"bsm.account.get"})) is None


def test_an_enabled_link_of_a_missing_user_is_enabled_again() -> None:
    decision = decide(desired(), observed(presence="absent", service_permissions=frozenset()))
    assert decision is not None
    assert (decision.operation, decision.reason) == ("enable", "resource_absent")


def test_a_disabled_link_revokes_what_the_user_still_has() -> None:
    decision = decide(
        desired(lifecycle="absent", service_permissions=frozenset()),
        observed(service_permissions=WANTED),
    )
    assert decision is not None
    assert (decision.operation, decision.reason) == ("disable", "lifecycle_absent")


def test_a_disabled_link_with_nothing_left_needs_no_action() -> None:
    absent = desired(lifecycle="absent", service_permissions=frozenset())
    assert decide(absent, observed(service_permissions=frozenset())) is None
    assert decide(absent, observed(presence="absent", service_permissions=frozenset())) is None


def test_an_inconclusive_observation_never_authorizes_an_action() -> None:
    assert decide(desired(), observed(presence="unknown", service_permissions=frozenset())) is None
    absent = desired(lifecycle="absent", service_permissions=frozenset())
    assert decide(absent, observed(presence="unknown")) is None


def test_an_unknown_lifecycle_does_nothing() -> None:
    assert decide(desired(lifecycle="outro"), observed(service_permissions=frozenset())) is None
