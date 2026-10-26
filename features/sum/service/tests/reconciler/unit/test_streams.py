"""Streams lidos pelo Reconciler para reconstruir o estado (`docs/messaging/NATS.md` §7.4)."""

import pytest

from sum_service.reconciler.transport.streams import STREAMS


@pytest.mark.parametrize(("stream", "subject", "suffix"), STREAMS)
def test_every_filter_is_scoped_to_the_sum_service_resource(
    stream: str, subject: str, suffix: str
) -> None:
    assert stream in {"DESIRED", "OBSERVED", "RESULT"}
    assert subject.endswith(".sum.service.>")
    assert suffix in {"desired", "observed", "result"}
