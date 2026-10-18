"""Conexão NATS do Executor, leitura do `desired` e publicação do resultado (`docs/NATS.md`).

O `desired` é lido pela leitura direta do último valor do Stream `DESIRED` (`allow_direct`), com a
identidade do Executor. O resultado sai com `Nats-Msg-Id` igual ao `actionId` e o tipo, para
deduplicar.
"""

from typing import Any

import nats
import nats.errors
import nats.js.errors
from nats.aio.client import Client as NatsClient
from nats.js import JetStreamContext
from pydantic import SecretStr

from sum_service_executor.engine.executor import PublishError
from sum_service_executor.logging_config import TRACEPARENT_HEADER, current_traceparent

PUBLISH_TIMEOUT_SECONDS = 5.0


async def connect(
    url: str, user: str, password: SecretStr | None, *, name: str = "sum-service-executor"
) -> NatsClient:
    secret = password.get_secret_value() if password else None
    options: dict[str, Any] = {"servers": [url], "user": user, "password": secret, "name": name}
    return await nats.connect(**options)  # pyright: ignore[reportUnknownMemberType]


def jetstream_of(client: NatsClient) -> JetStreamContext:
    return client.jetstream()  # pyright: ignore[reportUnknownMemberType]


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


class JetStreamPublisher:
    def __init__(self, jetstream: JetStreamContext) -> None:
        self._jetstream = jetstream

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        headers = {"Nats-Msg-Id": message_id}
        traceparent = current_traceparent()
        if traceparent is not None:
            headers[TRACEPARENT_HEADER] = traceparent
        try:
            await self._jetstream.publish(
                subject, payload, timeout=PUBLISH_TIMEOUT_SECONDS, headers=headers
            )
        except (nats.errors.Error, nats.js.errors.Error, TimeoutError, OSError) as error:
            raise PublishError(type(error).__name__) from error
