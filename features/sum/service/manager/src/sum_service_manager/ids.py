"""Identificadores e relógio do Manager do SUM."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Instante atual em UTC, com fuso (o envelope exige fuso)."""
    return datetime.now(UTC)
