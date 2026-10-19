"""O consumer associa o `traceparent` do header NATS ao contexto da mensagem (decisão 0055)."""

from typing import Any, cast

import pytest
from nats.aio.msg import Msg

from core_account.common.logging_config import bind_traceparent, current_traceparent
from core_account.manager.domain.kind import ResourceKind
from core_account.manager.transport import consumers
from core_account.manager.transport.consumers import Disposition, ObservedConsumer

TRACEPARENT = "00-4bf92f3577b34da6a3ce929d0e0e4736-00f067aa0ba902b7-01"


class FakeMessage:
    def __init__(self, headers: dict[str, str] | None) -> None:
        self.headers = headers
        self.data = b"{}"
        self.acked = False

    async def ack(self) -> None:
        self.acked = True


async def settle_with(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str] | None
) -> str | None:
    seen: list[str | None] = []

    async def fake_process(*_: Any) -> Disposition:
        seen.append(current_traceparent())
        return Disposition.ACK

    monkeypatch.setattr(consumers, "process_requested", fake_process)
    consumer = ObservedConsumer(
        cast(Any, None), cast(Any, None), ResourceKind("account", cast(Any, None))
    )
    message = FakeMessage(headers)
    await consumer._settle(cast(Msg, message))  # pyright: ignore[reportPrivateUsage]
    assert message.acked
    assert current_traceparent() is None  # o contexto vale só para esta mensagem
    return seen[0]


async def test_the_header_traceparent_is_the_context_while_the_message_is_handled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bind_traceparent(None)
    assert await settle_with(monkeypatch, {"traceparent": TRACEPARENT}) == TRACEPARENT


@pytest.mark.parametrize("headers", [None, {}, {"traceparent": "garbage"}])
async def test_a_missing_or_invalid_header_clears_a_previous_context(
    monkeypatch: pytest.MonkeyPatch, headers: dict[str, str] | None
) -> None:
    bind_traceparent(TRACEPARENT)  # contexto da mensagem anterior não pode vazar
    assert await settle_with(monkeypatch, headers) is None
