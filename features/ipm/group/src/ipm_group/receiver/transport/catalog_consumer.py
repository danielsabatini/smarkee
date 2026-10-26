"""Consumer de `DESIRED` de `ipm.role` para atualizar o catálogo de roles em tempo real (0088)."""

import asyncio
import json
import logging
from typing import cast

from nats.aio.msg import Msg
from nats.js import JetStreamContext

from ipm_group.common.catalog import RolesCatalog
from ipm_group.common.messaging import consume, new_instance_name

logger = logging.getLogger(__name__)

STREAM = "DESIRED"
SUBJECT_FILTER = "manager.desired.ipm.role.>"


class RoleCatalogConsumer:
    """Consome eventos `desired` de Roles para manter o catálogo do Receiver sincronizado."""

    def __init__(
        self,
        jetstream: JetStreamContext,
        catalog: RolesCatalog,
        *,
        inactive_threshold_seconds: int = 300,
    ) -> None:
        self._jetstream = jetstream
        self._catalog = catalog
        self._inactive_threshold_seconds = inactive_threshold_seconds

    async def run(self, stop: asyncio.Event) -> None:
        instance = new_instance_name()
        durable = f"ipm-group-receiver-roles-{instance}"
        subscription = await self._jetstream.pull_subscribe_bind(consumer=durable, stream=STREAM)
        await consume(
            subscription,
            self._handle,
            stop,
            batch_size=10,
            fetch_timeout_seconds=2.0,
        )

    async def _handle(self, message: Msg) -> None:
        try:
            doc: object = json.loads(message.data)
            data: object = (
                cast("dict[str, object]", doc).get("data") if isinstance(doc, dict) else None
            )
            if isinstance(data, dict):
                self._catalog.on_role_desired(cast("dict[str, object]", data))
            await message.ack()
        except Exception as error:
            logger.warning("failed to process role desired event", exc_info=error)
            await message.ack()
