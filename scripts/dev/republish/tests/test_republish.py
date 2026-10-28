"""Testes unitários da ferramenta smarkee-dev-republish."""

from unittest.mock import AsyncMock, MagicMock

from smarkee_dev_republish.engine import build_plan, execute_plan, select_kinds
from smarkee_dev_republish.main import parse_args
from smarkee_dev_republish.model import (
    ALL_KINDS,
    ORGANIZATIONS,
    ROLES,
    USERS,
    DesiredRecord,
    deterministic_message_id,
)


def test_deterministic_message_id_is_stable_and_unique() -> None:
    id1 = deterministic_message_id("ipm", "user", "usr-1", 1)
    id2 = deterministic_message_id("ipm", "user", "usr-1", 1)
    id3 = deterministic_message_id("ipm", "user", "usr-1", 2)
    id4 = deterministic_message_id("ipm", "role", "usr-1", 1)

    assert id1 == id2
    assert id1 != id3
    assert id1 != id4
    assert len(id1) == 36


def test_select_kinds_filters() -> None:
    all_selected = select_kinds()
    assert len(all_selected) == len(ALL_KINDS)

    ipm_only = select_kinds(module="ipm")
    assert all(k.module == "ipm" for k in ipm_only)
    assert len(ipm_only) > 0

    user_only = select_kinds(module="ipm", resource_type="user")
    assert len(user_only) == 1
    assert user_only[0] == USERS

    unknown = select_kinds(module="nonexistent")
    assert unknown == []


def test_build_plan_with_fake_ssot() -> None:
    fake_ssot = MagicMock()
    record = DesiredRecord(
        module="ipm",
        resource_type="user",
        resource_id="usr-123",
        desired_generation=1,
        lifecycle="present",
        reconciliation="active",
        desired={"email": "test@example.com"},
        message_id="msg-1",
        subject="desired.ipm.user.usr-123",
        envelope={"messageId": "msg-1"},
    )
    fake_ssot.fetch_records.side_effect = lambda kind, resource_id=None: (  # pyright: ignore[reportUnknownLambdaType]
        [record] if kind == USERS else []
    )

    plan = build_plan(fake_ssot, [USERS, ORGANIZATIONS])
    assert USERS in plan
    assert ORGANIZATIONS not in plan
    assert plan[USERS] == [record]


async def test_execute_plan_outbox() -> None:
    fake_ssot = MagicMock()
    fake_ssot.enqueue_outbox.return_value = 2

    record = DesiredRecord(
        module="ipm",
        resource_type="role",
        resource_id="role-1",
        desired_generation=1,
        lifecycle="present",
        reconciliation="active",
        desired={"name": "customRole"},
        message_id="msg-2",
        subject="desired.ipm.role.role-1",
        envelope={"messageId": "msg-2"},
    )
    plan = {ROLES: [record, record]}
    results = await execute_plan(plan, target="outbox", ssot=fake_ssot)
    assert results == {"ipm.role": 2}
    fake_ssot.enqueue_outbox.assert_called_once_with(ROLES, [record, record])


async def test_execute_plan_nats() -> None:
    fake_ssot = MagicMock()
    fake_nats = MagicMock()
    fake_nats.publish_record = AsyncMock(return_value=True)

    record = DesiredRecord(
        module="ipm",
        resource_type="role",
        resource_id="role-1",
        desired_generation=1,
        lifecycle="present",
        reconciliation="active",
        desired={"name": "customRole"},
        message_id="msg-2",
        subject="desired.ipm.role.role-1",
        envelope={"messageId": "msg-2"},
    )
    plan = {ROLES: [record]}
    results = await execute_plan(plan, target="nats", ssot=fake_ssot, nats_bus=fake_nats)
    assert results == {"ipm.role": 1}
    fake_nats.publish_record.assert_awaited_once_with(record)


def test_cli_parsing() -> None:
    args = parse_args([])
    assert args.apply is False
    assert args.target == "outbox"
    assert args.module is None

    args2 = parse_args(["--apply", "--target", "nats", "--module", "ipm", "--type", "user"])
    assert args2.apply is True
    assert args2.target == "nats"
    assert args2.module == "ipm"
    assert args2.resource_type == "user"
