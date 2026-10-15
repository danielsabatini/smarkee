"""Identificadores e relógio do Receiver do SUM."""

import uuid
from datetime import UTC, datetime


def new_identifier() -> str:
    """UUIDv7: atribuído pelo Receiver ao recurso e à operação (`docs/RESOURCE-CONTROL-LOOP.md`)."""
    return str(uuid.uuid7())


def utc_now() -> datetime:
    """Instante atual em UTC, com fuso (o envelope exige fuso)."""
    return datetime.now(UTC)
