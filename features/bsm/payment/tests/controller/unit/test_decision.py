"""Testes unitários da decisão pura e convergência de `bsm.payment` (decisão 0096)."""

from datetime import UTC, datetime, timedelta

from bsm_payment.controller.domain import convergence
from bsm_payment.controller.domain.decision import DesiredState, ObservedState, decide

NOW = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def test_decide_create_update_delete_and_noop() -> None:
    desired = DesiredState(
        lifecycle="present",
        display_name="Visa Final 4242",
        provider="mercadopago",
        method_type="credit_card",
        deletion_protection=True,
    )
    assert decide(desired, ObservedState(presence="unknown")) is None

    create_dec = decide(desired, ObservedState(presence="absent"))
    assert create_dec is not None and create_dec.operation == "create"

    observed = ObservedState(
        presence="present",
        display_name="Visa Final 4242",
        provider="mercadopago",
        method_type="credit_card",
        status="active",
        deletion_protection=True,
    )
    assert decide(desired, observed) is None

    drifted = ObservedState(
        presence="present",
        display_name="Nome Antigo",
        provider="mercadopago",
        method_type="credit_card",
        status="active",
        deletion_protection=False,
    )
    update_dec = decide(desired, drifted)
    assert update_dec is not None
    assert update_dec.operation == "update"
    assert update_dec.fields == ("displayName", "deletionProtection")

    absent_desired = DesiredState(
        lifecycle="absent",
        display_name="Visa Final 4242",
        provider="mercadopago",
        method_type="credit_card",
        deletion_protection=False,
    )
    delete_dec = decide(absent_desired, observed)
    assert delete_dec is not None and delete_dec.operation == "delete"
    assert decide(absent_desired, ObservedState(presence="absent")) is None


def test_convergence_ready_and_failure_limit() -> None:
    desired = {
        "lifecycle": "present",
        "displayName": "Visa Final 4242",
        "provider": "mercadopago",
        "methodType": "credit_card",
        "deletionProtection": True,
    }
    observed = {
        "displayName": "Visa Final 4242",
        "provider": "mercadopago",
        "methodType": "credit_card",
        "status": "active",
        "providerCustomerId": "mp-cust-1",
        "providerPaymentMethodId": "mp-pm-1",
        "deletionProtection": True,
    }
    obs_dec = convergence.decide_observed(
        convergence.check_is_converged,
        desired=desired,
        lifecycle="present",
        generation=1,
        observation_generation=1,
        presence="present",
        observed=observed,
        previous_phase="Pending",
        previous_conditions=[],
        now=NOW,
        progress_deadline_seconds=300,
    )
    assert obs_dec.phase == "Ready"
    assert obs_dec.converged is True
    assert obs_dec.remove is False

    res = convergence.decide_result(
        failed=True,
        failure_reason="InvalidPaymentToken",
        failure_limit=1,
        generation=1,
        failure_count=0,
        phase="Pending",
        reconciliation="active",
        previous_conditions=[],
        now=NOW + timedelta(seconds=1),
    )
    assert res.suspend is True
    assert res.phase == "Failed"
    assert res.reconciliation == "suspended"
