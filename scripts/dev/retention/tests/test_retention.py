"""Testes unitários do utilitário de retenção."""

from datetime import UTC, datetime, timedelta

import pytest

from smarkee_dev_retention.engine import (
    apply_retention,
    filter_targets,
    plan_retention,
)
from smarkee_dev_retention.model import (
    TARGET_TABLES,
    TargetTable,
    parse_duration,
)


def test_parse_duration_valid() -> None:
    assert parse_duration("0s") == timedelta(seconds=0)
    assert parse_duration("0") == timedelta(seconds=0)
    assert parse_duration("60s") == timedelta(seconds=60)
    assert parse_duration("30m") == timedelta(minutes=30)
    assert parse_duration("24h") == timedelta(hours=24)
    assert parse_duration("7d") == timedelta(days=7)


def test_parse_duration_invalid() -> None:
    with pytest.raises(ValueError, match="Formato de duração inválido"):
        parse_duration("invalid")
    with pytest.raises(ValueError, match="Formato de duração inválido"):
        parse_duration("24x")


def test_filter_targets() -> None:
    all_targets = filter_targets()
    assert len(all_targets) == len(TARGET_TABLES)

    cam_targets = filter_targets(module="cam")
    assert all(t.module == "cam" for t in cam_targets)
    assert len(cam_targets) == 2

    outbox_only = filter_targets(table_kind="outbox")
    assert all(t.table_kind == "outbox" for t in outbox_only)
    assert len(outbox_only) == 10

    perm_outbox = filter_targets(module="ipm", resource_type="permission", table_kind="outbox")
    assert len(perm_outbox) == 1
    assert perm_outbox[0].table_name == "permission_outbox"


class FakeRetentionDatabase:
    def __init__(self, counts: dict[str, int]) -> None:
        self.counts = counts
        self.purged: list[str] = []

    def count_expired(self, target: TargetTable, cutoff: datetime) -> int:
        return self.counts.get(target.table_name, 0)

    def purge_expired(self, target: TargetTable, cutoff: datetime) -> int:
        count = self.counts.get(target.table_name, 0)
        self.purged.append(target.table_name)
        return count


def test_plan_and_apply_retention() -> None:
    targets = [
        TargetTable(
            "cam", "account", "cam", "account_outbox", "outbox", "cam_maintenance_login"
        ),
        TargetTable(
            "cam",
            "account",
            "cam",
            "account_idempotency",
            "idempotency",
            "cam_maintenance_login",
        ),
    ]
    db = FakeRetentionDatabase({"account_outbox": 15, "account_idempotency": 3})
    cutoff = datetime.now(UTC)

    plan = plan_retention(db, targets, cutoff)  # pyright: ignore[reportArgumentType]
    assert len(plan) == 2
    assert plan[0].count == 15
    assert plan[1].count == 3

    results = apply_retention(db, targets, cutoff)  # pyright: ignore[reportArgumentType]
    assert len(results) == 2
    assert results[0].count == 15
    assert results[1].count == 3
    assert db.purged == ["account_outbox", "account_idempotency"]
