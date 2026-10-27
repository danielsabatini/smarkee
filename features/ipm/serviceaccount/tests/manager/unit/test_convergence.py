"""Decisões puras sobre `observed` e resultados de ação, sem banco."""

import asyncio
import json
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from ipm_serviceaccount.manager.domain.convergence import decide_observed, decide_result
from ipm_serviceaccount.manager.domain.kind import SERVICEACCOUNT, serviceaccount_kind
from ipm_serviceaccount.manager.domain.serviceaccount import ServiceAccountPolicy
from ipm_serviceaccount.manager.handlers import role_rollout

PUBLIC_KEY = "-----BEGIN PUBLIC KEY-----\nMIIBIjANBgkqhkiG9w0BAQEFAAOCAQ8AMIIBCgKCAQEAu1SU1LfVLPHCozMxH2Mo\n4lgOEePzNm0tRgeLezV6ffAt0gunVTLw7onLRnrq0/IzW7yWR7QkrmBL7jTKEn5u\n+qKhbwKfBstIs+bMY2Zkp18gnTxKLxoS2tFczGkPLPgizskuemMghRniWaoLcyeh\nkd3qqGElvW/VDL5AaWTg0nLVkjRo9z+40RQzuVaE8AkAFmxZzow3x+VJYKdjykkJ\n0iT9wCS0DRTXu269V264Vf/3jvredZiKRkgwlL9xNAwxXFMdc6U6mS0Dmj4ZW+EY\ntDV0FNsMzP5nkQa3iX7D4hFxNl9lXoB0iJhpgJmfrVfJLFSEfMyw72yW6Uq3Ohjf\nbwIDAQAB\n-----END PUBLIC KEY-----\n"  # noqa: E501
NOW = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
DESIRED_PRESENT: dict[str, Any] = {
    "lifecycle": "present",
    "organizationId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
    "name": "deploy-bot",
    "permissions": ["ipm.serviceaccount.get"],
    "deletionProtection": False,
    "keys": [{"publicKey": "PEM", "expiresAt": "2027-01-01T00:00:00Z", "fingerprint": "a" * 64}],
}


def observe(
    presence: str,
    *,
    desired: dict[str, Any],
    lifecycle: str,
    phase: str = "Pending",
    observation_generation: int | None = 1,
):
    return decide_observed(
        SERVICEACCOUNT.policy,
        desired=desired,
        lifecycle=lifecycle,
        generation=1,
        observation_generation=observation_generation,
        presence=presence,
        observed={
            "userState": "active",
            "permissions": ["ipm.serviceaccount.get"],
            "deletionProtection": False,
            "keys": [{"fingerprint": "a" * 64, "keyId": "k1", "status": "active"}],
        },
        previous_phase=phase,
        previous_conditions=[],
        now=NOW,
    )


def test_present_and_matching_converges_to_ready() -> None:
    decision = observe("present", desired=DESIRED_PRESENT, lifecycle="present")
    assert decision.converged and decision.phase == "Ready" and not decision.remove
    assert decision.conditions[0]["status"] == "True"


def test_present_but_different_keeps_reconciling() -> None:
    desired = {
        **DESIRED_PRESENT,
        "permissions": ["ipm.serviceaccount.get", "ipm.serviceaccount.list"],
    }
    decision = observe("present", desired=desired, lifecycle="present")
    assert not decision.converged and decision.phase == "Reconciling"


def test_failed_phase_is_kept_while_not_converged() -> None:
    desired = {
        **DESIRED_PRESENT,
        "permissions": ["ipm.serviceaccount.get", "ipm.serviceaccount.list"],
    }
    decision = observe("present", desired=desired, lifecycle="present", phase="Failed")
    assert decision.phase == "Failed" and decision.conditions[0]["reason"] == "Failed"


def test_absent_when_removal_is_wanted_removes_the_record() -> None:
    desired = {**DESIRED_PRESENT, "lifecycle": "absent"}
    decision = observe("absent", desired=desired, lifecycle="absent")
    assert decision.remove and decision.converged


def test_unknown_observation_does_not_decide_convergence() -> None:
    decision = observe("unknown", desired=DESIRED_PRESENT, lifecycle="present", phase="Reconciling")
    assert not decision.converged and decision.phase == "Reconciling"
    assert decision.conditions[0]["status"] == "Unknown"


def result(*, failed: bool, count: int, limit: int = 3, reconciliation: str = "active"):
    return decide_result(
        failed=failed,
        failure_reason="Rejected",
        failure_limit=limit,
        generation=1,
        failure_count=count,
        phase="Pending",
        reconciliation=reconciliation,
        previous_conditions=[],
        now=NOW,
    )


def test_failure_below_the_limit_counts_and_keeps_reconciling() -> None:
    decision = result(failed=True, count=0)
    assert decision.failure_count == 1 and decision.phase == "Reconciling"
    assert not decision.suspend


def test_failure_at_the_limit_suspends_the_reconciliation() -> None:
    decision = result(failed=True, count=2)
    assert decision.suspend and decision.phase == "Failed"
    assert decision.reconciliation == "suspended"
    assert decision.conditions[0]["reason"] == "FailureLimitReached"


def test_success_does_not_count_a_failure() -> None:
    decision = result(failed=False, count=2)
    assert decision.failure_count == 2 and not decision.suspend


def test_already_suspended_does_not_suspend_again() -> None:
    assert not result(failed=True, count=9, reconciliation="suspended").suspend


def test_missing_permissions_keep_reconciling() -> None:
    desired: dict[str, Any] = {**DESIRED_PRESENT, "permissions": []}
    decision = observe("present", desired=desired, lifecycle="present")
    assert not decision.converged and decision.phase == "Reconciling"


def test_the_name_is_not_a_managed_field() -> None:
    desired = {**DESIRED_PRESENT, "name": "outro"}
    decision = observe("present", desired=desired, lifecycle="present")
    assert decision.converged  # imutável e definido na criação: não gera divergência


def test_a_key_not_yet_registered_keeps_reconciling() -> None:
    other = {"publicKey": "PEM-2", "expiresAt": "2027-01-01T00:00:00Z", "fingerprint": "b" * 64}
    desired = {**DESIRED_PRESENT, "keys": [*DESIRED_PRESENT["keys"], other]}
    decision = observe("present", desired=desired, lifecycle="present")
    assert not decision.converged and decision.phase == "Reconciling"


def test_an_expired_key_still_counts_as_converged() -> None:
    """A chave vencida continua no `desired` e aparece como `expired` no `observed`."""
    policy = SERVICEACCOUNT.policy
    observed = {
        "permissions": ["ipm.serviceaccount.get"],
        "deletionProtection": False,
        "keys": [{"fingerprint": "a" * 64, "keyId": "k1", "status": "expired"}],
    }
    assert policy.is_converged(DESIRED_PRESENT, "present", observed)


def test_a_different_description_keeps_reconciling() -> None:
    desired = {**DESIRED_PRESENT, "description": "CI deploy"}
    decision = observe("present", desired=desired, lifecycle="present")
    assert not decision.converged


def test_observation_older_than_the_generation_does_not_converge() -> None:
    """Conteúdo igual não basta: a observação precisa ser posterior à geração (decisão 0072)."""
    for observation_generation in (None,):
        decision = observe(
            "present",
            desired=DESIRED_PRESENT,
            lifecycle="present",
            phase="Reconciling",
            observation_generation=observation_generation,
        )
        assert not decision.converged and decision.phase == "Reconciling"


def test_removal_needs_an_observation_of_the_removal_generation() -> None:
    desired = {**DESIRED_PRESENT, "lifecycle": "absent"}
    decision = observe(
        "absent", desired=desired, lifecycle="absent", phase="Deleting", observation_generation=None
    )
    assert not decision.converged and not decision.remove


def test_a_different_deletion_protection_keeps_reconciling() -> None:
    """A proteção é campo gerenciado: o metadado do provedor precisa bater (decisão 0074)."""
    protected = {**DESIRED_PRESENT, "deletionProtection": True}
    decision = observe("present", desired=protected, lifecycle="present", phase="Reconciling")
    assert not decision.converged and decision.phase == "Reconciling"


def absent_while_present(*, at: datetime, conditions: list[dict[str, Any]], generation: int = 1):
    """Uma observação que nunca converge: o recurso deveria existir e não existe."""
    return decide_observed(
        SERVICEACCOUNT.policy,
        desired=DESIRED_PRESENT,
        lifecycle="present",
        generation=generation,
        observation_generation=generation,
        presence="absent",
        observed={},
        previous_phase="Reconciling",
        previous_conditions=conditions,
        now=at,
        progress_deadline_seconds=300,
    )


def progressing(conditions: list[dict[str, Any]]) -> dict[str, Any]:
    return next(c for c in conditions if c["type"] == "Progressing")


def test_progress_starts_at_the_first_divergent_observation_and_keeps_its_start() -> None:
    first = absent_while_present(at=NOW, conditions=[])
    later = absent_while_present(at=NOW + timedelta(seconds=200), conditions=first.conditions)
    condition = progressing(later.conditions)
    assert (condition["status"], condition["reason"]) == ("True", "Reconciling")
    assert datetime.fromisoformat(condition["lastTransitionAt"]) == NOW
    assert later.phase == "Reconciling" and not later.progress_deadline_exceeded
    assert {c["type"] for c in later.conditions} == {"Ready", "Progressing"}


def test_past_the_deadline_the_resource_fails_once_and_stays_failed() -> None:
    first = absent_while_present(at=NOW, conditions=[])
    late = absent_while_present(at=NOW + timedelta(seconds=301), conditions=first.conditions)
    condition = progressing(late.conditions)
    assert (condition["status"], condition["reason"]) == ("False", "ProgressDeadlineExceeded")
    assert late.phase == "Failed" and late.progress_deadline_exceeded
    again = absent_while_present(at=NOW + timedelta(seconds=400), conditions=late.conditions)
    assert again.phase == "Failed" and not again.progress_deadline_exceeded  # avisa uma vez só


def test_a_new_generation_restarts_the_progress_clock() -> None:
    first = absent_while_present(at=NOW, conditions=[])
    late = absent_while_present(at=NOW + timedelta(seconds=301), conditions=first.conditions)
    newer = absent_while_present(
        at=NOW + timedelta(seconds=302), conditions=late.conditions, generation=2
    )
    condition = progressing(newer.conditions)
    assert (condition["status"], condition["reason"]) == ("True", "Reconciling")
    assert datetime.fromisoformat(condition["lastTransitionAt"]) == NOW + timedelta(seconds=302)


def test_a_failure_result_keeps_the_progress_condition() -> None:
    first = absent_while_present(at=NOW, conditions=[])
    decision = decide_result(
        failed=True,
        failure_reason="Rejected",
        failure_limit=5,
        generation=1,
        failure_count=0,
        phase="Reconciling",
        reconciliation="active",
        previous_conditions=first.conditions,
        now=NOW,
    )
    assert {c["type"] for c in decision.conditions} == {"Ready", "Progressing"}


async def test_serviceaccount_policy_expands_roles_and_rolls_out_on_role_change(
    monkeypatch: Any,
) -> None:
    kind = serviceaccount_kind()
    policy = cast(ServiceAccountPolicy, kind.policy)
    req = policy.parse(
        "create",
        {
            "operationId": "01950000-0000-7000-8000-000000000001",
            "requestDigest": "a" * 64,
            "specification": {
                "organizationId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
                "name": "deploy-bot",
                "keys": [
                    {
                        "publicKey": PUBLIC_KEY,
                        "expiresAt": "2027-01-24T14:00:00Z",
                        "fingerprint": "9" * 64,
                    }
                ],
                "roles": ["ipm.serviceaccountViewer"],
            },
        },
    )
    desired = policy.desired_for_create(req, "owner-1")
    assert desired["roles"] == ["ipm.serviceaccountViewer"]
    assert desired["permissions"] == [
        "ipm.serviceaccount.get",
        "ipm.serviceaccount.list",
    ]
    msg = policy.message_data(desired, "active")
    assert msg["roles"] == ["ipm.serviceaccountViewer"]
    assert msg["permissions"] == [
        "ipm.serviceaccount.get",
        "ipm.serviceaccount.list",
    ]

    rollouts: list[int] = []

    async def fake_rollout(pool: Any, kind_arg: Any, **_: Any) -> int:
        rollouts.append(1)
        return 1

    monkeypatch.setattr(role_rollout, "roll_out_serviceaccount_roles", fake_rollout)
    watcher = role_rollout.RoleCatalogWatcher(cast(Any, object()), kind)
    now_iso = NOW.isoformat()
    role_data: dict[str, Any] = {
        "lifecycle": "present",
        "reconciliation": "active",
        "name": "ipm.serviceaccountViewer",
        "description": "Visualizador atualizado",
        "permissions": [
            "ipm.serviceaccount.get",
            "ipm.serviceaccount.list",
            "ipm.serviceaccount.update",
        ],
        "deletionProtection": True,
    }
    role_msg: dict[str, Any] = {
        "messageId": "01950000-0000-7000-8000-000000000010",
        "schemaVersion": "1.0",
        "messageType": "desired",
        "emitter": "manager",
        "module": "ipm",
        "resourceType": "role",
        "resourceId": "role-ipm-serviceaccount-viewer",
        "operation": "changed",
        "desiredGeneration": 2,
        "requestedBy": "system",
        "correlationId": "01950000-0000-7000-8000-000000000011",
        "causationId": "01950000-0000-7000-8000-000000000012",
        "occurredAt": now_iso,
        "publishedAt": now_iso,
        "data": role_data,
    }
    assert await watcher.on_message(json.dumps(role_msg).encode()) == 1
    assert len(rollouts) == 1
    rolled = policy.rolled_out(desired)
    assert rolled is not None
    assert rolled["permissions"] == [
        "ipm.serviceaccount.get",
        "ipm.serviceaccount.list",
        "ipm.serviceaccount.update",
    ]
    assert policy.rolled_out(rolled) is None


async def test_role_catalog_watcher_defers_and_debounces(
    monkeypatch: Any,
) -> None:
    kind = serviceaccount_kind()
    rollouts: list[int] = []

    async def fake_rollout(pool: Any, kind_arg: Any, **_: Any) -> int:
        rollouts.append(1)
        return 1

    monkeypatch.setattr(role_rollout, "roll_out_serviceaccount_roles", fake_rollout)

    synced = False
    watcher = role_rollout.RoleCatalogWatcher(
        cast(Any, object()),
        kind,
        is_synced=lambda: synced,
        debounce_seconds=0.02,
    )
    now_iso = NOW.isoformat()
    msg_bytes = json.dumps(
        {
            "messageId": "01950000-0000-7000-8000-000000000010",
            "schemaVersion": "1.0",
            "messageType": "desired",
            "emitter": "manager",
            "module": "ipm",
            "resourceType": "role",
            "resourceId": "role-ipm-sa-viewer",
            "operation": "changed",
            "desiredGeneration": 2,
            "requestedBy": "system",
            "correlationId": "01950000-0000-7000-8000-000000000011",
            "causationId": "01950000-0000-7000-8000-000000000012",
            "occurredAt": now_iso,
            "publishedAt": now_iso,
            "data": {
                "lifecycle": "present",
                "name": "ipm.serviceaccountViewer",
                "permissions": [
                    "ipm.serviceaccount.get",
                    "ipm.serviceaccount.list",
                    "ipm.serviceaccount.update",
                ],
            },
        }
    ).encode()

    # 1. Enquanto synced=False, on_message não executa rollout imediatamente
    assert await watcher.on_message(msg_bytes) == 0
    assert len(rollouts) == 0

    # 2. Quando sincroniza, o worker ou flush executa o rollout pendente
    synced = True
    assert await watcher.flush_pending_rollout() == 1
    assert len(rollouts) == 1

    # 3. Debounce: várias rajadas de mudanças com debounce_seconds disparam apenas um rollout
    msg_r1 = json.dumps(
        {
            "messageId": "01950000-0000-7000-8000-000000000020",
            "schemaVersion": "1.0",
            "messageType": "desired",
            "emitter": "manager",
            "module": "ipm",
            "resourceType": "role",
            "resourceId": "role-ipm-admin-1",
            "operation": "changed",
            "desiredGeneration": 1,
            "requestedBy": "system",
            "correlationId": "01950000-0000-7000-8000-000000000021",
            "causationId": "01950000-0000-7000-8000-000000000022",
            "occurredAt": now_iso,
            "publishedAt": now_iso,
            "data": {
                "lifecycle": "present",
                "name": "ipm.customAdmin1",
                "permissions": ["ipm.serviceaccount.get"],
            },
        }
    ).encode()
    msg_r2 = json.dumps(
        {
            "messageId": "01950000-0000-7000-8000-000000000030",
            "schemaVersion": "1.0",
            "messageType": "desired",
            "emitter": "manager",
            "module": "ipm",
            "resourceType": "role",
            "resourceId": "role-ipm-admin-2",
            "operation": "changed",
            "desiredGeneration": 1,
            "requestedBy": "system",
            "correlationId": "01950000-0000-7000-8000-000000000031",
            "causationId": "01950000-0000-7000-8000-000000000032",
            "occurredAt": now_iso,
            "publishedAt": now_iso,
            "data": {
                "lifecycle": "present",
                "name": "ipm.customAdmin2",
                "permissions": ["ipm.serviceaccount.list"],
            },
        }
    ).encode()
    await watcher.on_message(msg_r1)
    await watcher.on_message(msg_r2)
    await asyncio.sleep(0.05)
    assert len(rollouts) == 2
