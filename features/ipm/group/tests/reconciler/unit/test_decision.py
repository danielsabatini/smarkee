"""Testes unitários da decisão do Reconciler de `ipm.group`."""

from datetime import UTC, datetime

from ipm_group.reconciler.domain.decision import (
    DesiredState,
    ObservedState,
    ResourceState,
    decide,
)
from ipm_group.reconciler.settings import LoopSettings

NOW = datetime(2026, 4, 21, 12, 0, tzinfo=UTC)
ROLES = ("core.accountViewer", "ipm.userViewer")


def _desired(*, lifecycle: str = "present", roles: tuple[str, ...] = ROLES) -> DesiredState:
    return DesiredState(
        message_id="msg-desired-1",
        generation=1,
        lifecycle=lifecycle,
        reconciliation="active",
        organization_id="org-1",
        name="auditors",
        description="Auditores da Organization.",
        roles=roles,
        requested_by="operator-1",
        correlation_id="corr-1",
    )


def _observed(*, presence: str = "present", roles: tuple[str, ...] | None = ROLES) -> ObservedState:
    present = presence == "present"
    return ObservedState(
        message_id="msg-observed-1",
        presence=presence,
        observed_at=NOW,
        causation_id=None,
        name="auditors" if present else None,
        description="Auditores da Organization." if present else None,
        roles=roles if present else None,
        deletion_protection=False if present else None,
    )


def test_decide_create_update_delete_and_converged() -> None:
    params = LoopSettings()

    assert decide(ResourceState(desired=_desired(), observed=_observed()), NOW, params) is None

    missing = decide(
        ResourceState(desired=_desired(), observed=_observed(presence="absent")), NOW, params
    )
    assert missing is not None
    assert (missing.operation, missing.reason) == ("create", "Missing")

    drifted = decide(
        ResourceState(
            desired=_desired(roles=(*ROLES, "ipm.groupViewer")), observed=_observed(roles=ROLES)
        ),
        NOW,
        params,
    )
    assert drifted is not None
    assert (drifted.operation, drifted.fields) == ("update", ("roles",))

    deleting = decide(
        ResourceState(desired=_desired(lifecycle="absent"), observed=_observed()), NOW, params
    )
    assert deleting is not None
    assert deleting.operation == "delete"


def test_decide_never_acts_on_an_unknown_or_suspended_state() -> None:
    params = LoopSettings()
    unknown = ResourceState(desired=_desired(), observed=_observed(presence="unknown"))
    assert decide(unknown, NOW, params) is None
    assert decide(ResourceState(desired=_desired()), NOW, params) is None
