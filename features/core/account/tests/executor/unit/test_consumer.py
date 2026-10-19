"""O consumer do Executor devolve a mensagem ao transporte conforme o desfecho da `action`."""

from dataclasses import dataclass, field
from typing import Any, cast

import nats.errors
import pytest
from nats.aio.msg import Msg
from nats.js import JetStreamContext

from core_account.common.ports import PublishError
from core_account.executor.engine.executor import Disposition, Executor
from core_account.executor.transport import nats as executor_nats
from core_account.executor.transport.nats import ActionConsumer


@dataclass
class FakeMessage:
    data: bytes = b"{}"
    headers: dict[str, str] | None = None
    settled: list[str] = field(default_factory=lambda: [])

    async def ack(self) -> None:
        self.settled.append("ack")

    async def term(self) -> None:
        self.settled.append("term")

    async def nak(self, delay: float | None = None) -> None:
        self.settled.append(f"nak:{delay}")


class FakeExecutor:
    def __init__(self, outcome: Disposition | Exception) -> None:
        self.outcome = outcome

    async def handle(self, data: bytes) -> Disposition:
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


async def settle(outcome: Disposition | Exception) -> list[str]:
    consumer = ActionConsumer(
        cast(JetStreamContext, None), cast(Executor, FakeExecutor(outcome)), partition=0
    )
    message = FakeMessage()
    await consumer._settle(cast(Msg, message))  # pyright: ignore[reportPrivateUsage]
    return message.settled


@pytest.mark.parametrize(
    ("outcome", "settled"),
    [
        (Disposition.ACK, ["ack"]),
        (Disposition.TERM, ["term"]),
        (PublishError("TimeoutError"), [f"nak:{executor_nats.REDELIVERY_DELAY_SECONDS}"]),
        (nats.errors.ConnectionClosedError(), [f"nak:{executor_nats.REDELIVERY_DELAY_SECONDS}"]),
        (OSError(), [f"nak:{executor_nats.REDELIVERY_DELAY_SECONDS}"]),
    ],
)
async def test_the_message_is_acked_terminated_or_returned_to_the_queue(
    outcome: Disposition | Exception, settled: list[str]
) -> None:
    assert await settle(outcome) == settled


def test_each_partition_has_its_own_durable_consumer() -> None:
    names: list[Any] = [
        ActionConsumer(cast(JetStreamContext, None), cast(Executor, None), partition=index)
        for index in range(2)
    ]
    assert [consumer._durable for consumer in names] == [  # pyright: ignore[reportPrivateUsage]
        "core-account-executor-action-p0",
        "core-account-executor-action-p1",
    ]
