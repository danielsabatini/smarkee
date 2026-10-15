"""Identificadores e relógio do Reconciler do SUM."""

import uuid
from datetime import UTC, datetime


def new_identifier() -> str:
    return str(uuid.uuid7())


def utc_now() -> datetime:
    return datetime.now(UTC)
