"""Publicação do `requested` pelo Receiver (`docs/NATS.md`).

Publica com `Nats-Msg-Id` igual ao `operationId`: o transporte descarta a repetição do mesmo pedido.
O `traceparent` da requisição, se houver, vai no header NATS de mesmo nome, sem alteração
(decisão 0055); ele não faz parte do envelope.
"""

from nats.js import JetStreamContext

from sum_service.common.messaging import JetStreamPublisher
from sum_service.common.ports import PublishError
from sum_service.receiver.domain.errors import unavailable


class RequestedPublisher:
    def __init__(self, jetstream: JetStreamContext) -> None:
        self._publisher = JetStreamPublisher(jetstream)

    async def publish(self, subject: str, payload: bytes, *, message_id: str) -> None:
        """Recusa do transporte vira 503 com `Retry-After`: o cliente repete com a mesma chave."""
        try:
            await self._publisher.publish(subject, payload, message_id=message_id)
        except PublishError:
            raise unavailable() from None
