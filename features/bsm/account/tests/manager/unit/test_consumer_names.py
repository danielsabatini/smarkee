"""Os nomes dos consumers duráveis que o Manager usa batem com os manifestos de `consumers/`."""

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from bsm_account.manager.domain.kind import ACCOUNT
from bsm_account.manager.transport.account_updated import AccountUpdatedConsumer
from bsm_account.manager.transport.consumers import (
    ObservedConsumer,
    RequestedConsumer,
    ResultConsumer,
)

CONSUMERS = Path(__file__).resolve().parents[3] / "consumers"


@pytest.mark.parametrize(
    "consumer_class", [RequestedConsumer, ObservedConsumer, ResultConsumer, AccountUpdatedConsumer]
)
def test_the_durable_name_matches_a_declared_manifest(consumer_class: Any) -> None:
    consumer = consumer_class(MagicMock(), MagicMock(), ACCOUNT)

    declared = {
        json.loads(path.read_text(encoding="utf-8"))["durable_name"]
        for path in CONSUMERS.glob("*.json")
    }

    assert consumer.durable_name in declared
