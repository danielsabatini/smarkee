"""Testes unitários da decisão do Reconciler de `ipm.role`."""

from datetime import UTC, datetime

from ipm_role.reconciler.domain.decision import (
    DesiredState,
    ObservedState,
    ResourceState,
    decide,
)
from ipm_role.reconciler.settings import LoopSettings

NOW = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)


def _desired(
    *,
    lifecycle: str = "present",
    permissions: tuple[str, ...] = ("ipm.user.bind", "ipm.user.get"),
) -> DesiredState:
    return DesiredState(
        message_id="msg-desired-1",
        generation=1,
        lifecycle=lifecycle,
        reconciliation="active",
        name="ipm.userAdmin",
        description="Administração de usuários.",
        permissions=permissions,
        requested_by="operator-1",
        correlation_id="corr-1",
        deletion_protection=True,
    )


def _observed(
    *,
    presence: str = "present",
    permissions: tuple[str, ...] | None = ("ipm.user.bind", "ipm.user.get"),
) -> ObservedState:
    return ObservedState(
        message_id="msg-observed-1",
        presence=presence,
        observed_at=NOW,
        causation_id=None,
        name="ipm.userAdmin" if presence == "present" else None,
        description="Administração de usuários." if presence == "present" else None,
        permissions=permissions if presence == "present" else None,
        deletion_protection=True if presence == "present" else None,
    )


def test_decide_create_update_delete_and_converged() -> None:
    params = LoopSettings()

    converged = ResourceState(desired=_desired(), observed=_observed())
    assert decide(converged, NOW, params) is None

    missing = ResourceState(desired=_desired(), observed=_observed(presence="absent"))
    create_decision = decide(missing, NOW, params)
    assert create_decision is not None
    assert create_decision.operation == "create"

    drifted = ResourceState(
        desired=_desired(permissions=("ipm.user.bind", "ipm.user.get", "ipm.user.list")),
        observed=_observed(permissions=("ipm.user.bind", "ipm.user.get")),
    )
    update_decision = decide(drifted, NOW, params)
    assert update_decision is not None
    assert update_decision.operation == "update"
    assert update_decision.fields == ("permissions",)

    deleting = ResourceState(
        desired=_desired(lifecycle="absent"),
        observed=_observed(presence="present"),
    )
    delete_decision = decide(deleting, NOW, params)
    assert delete_decision is not None
    assert delete_decision.operation == "delete"
