"""Leitura do `desired` e do último resultado pelo Executor (`docs/NATS.md`).

O `desired` é lido pela leitura direta do último valor do Stream `DESIRED` (`allow_direct`), com a
identidade do Executor.
"""

import nats.js.errors
from nats.js import JetStreamContext


class DirectStateReader:
    """Leitura direta do último `desired` e do último resultado de um recurso (só leitura).

    `desired`: `manager.desired.sum.service.<resourceId>.changed`.
    Resultado: `executor.<completed|failed>.sum.service.<resourceId>`.
    """

    def __init__(self, jetstream: JetStreamContext) -> None:
        self._jetstream = jetstream

    async def last_desired(self, resource_id: str) -> bytes | None:
        return await self._last("DESIRED", f"manager.desired.sum.service.{resource_id}.changed")

    async def last_result(self, resource_id: str, kind: str) -> bytes | None:
        return await self._last("RESULT", f"executor.{kind}.sum.service.{resource_id}")

    async def _last(self, stream: str, subject: str) -> bytes | None:
        try:
            message = await self._jetstream.get_last_msg(  # pyright: ignore[reportUnknownMemberType]
                stream, subject
            )
        except nats.js.errors.NotFoundError:
            return None
        return bytes(message.data or b"")
