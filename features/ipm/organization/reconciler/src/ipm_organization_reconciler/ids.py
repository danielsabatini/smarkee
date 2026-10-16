"""Identificadores e instantes.

Instantes sempre com fuso explícito (UTC), e identificadores opacos em UUIDv7 minúsculo
(`docs/MESSAGING.md` §6.5). Funções pequenas e separadas para serem substituídas nos testes.
"""

import uuid
from datetime import UTC, datetime


def new_identifier() -> str:
    """Novo identificador opaco (UUIDv7, minúsculo), válido como `resourceId` e `messageId`."""
    return str(uuid.uuid7())


def utc_now() -> datetime:
    return datetime.now(UTC)
