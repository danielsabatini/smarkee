"""Remoção da conta (`core.account`): o SUM apaga as ligações do dono (decisão 0044).

A conta só é apagada sem serviço habilitado (decisão 0040), então as ligações que sobram estão
desabilitadas e apontam para um dono que não existe mais. Cada módulo apaga o que é seu: o SUM reage
ao `updated` com `removed` da conta, em vez de o `core` escrever no SSOT do SUM. Repetir não tem
efeito.
"""

import logging
from typing import Any

from psycopg_pool import AsyncConnectionPool

from sum_service.common.contracts.envelope import EnvelopeError, read_envelope
from sum_service.controller.store.ssot import ControllerSsotStore

logger = logging.getLogger(__name__)

ACCOUNT_UPDATED_SUBJECT = "manager.updated.core.account.>"


def removed_account_id(data: bytes) -> str | None:
    """`resourceId` da conta removida, ou `None` se o `updated` não é de remoção (a ignorar)."""
    try:
        envelope = read_envelope(data)
    except EnvelopeError:
        return None
    if envelope.module != "core" or envelope.resource_type != "account":
        return None
    if envelope.message_type.value != "updated":
        return None
    return envelope.resource_id if envelope.data.get("removed") is True else None


class AccountRemovedHandler:
    """Sink do `StateConsumer` do `UPDATED` de `core.account`."""

    def __init__(self, pool: AsyncConnectionPool[Any]) -> None:
        self._pool = pool

    async def on_message(self, data: bytes) -> object:
        account_id = removed_account_id(data)
        if account_id is None:
            return None  # `updated` comum da conta: nada a fazer
        async with self._pool.connection() as connection:
            store = ControllerSsotStore(connection)
            async with store.transaction():
                removed = await store.delete_owned_by(account_id)
        logger.info(
            "links of a removed account deleted",
            extra={"smarkee.account.id": account_id, "smarkee.links.removed": removed},
        )
        return account_id
