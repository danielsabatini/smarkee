import json
from datetime import UTC, datetime

import pytest

from core_account.publisher.domain.publication import PublicationRejectedError
from core_account.publisher.outbox.publication import PUBLISHED_BY, publication_envelope

WHEN = datetime(2026, 10, 15, 14, 0, 1, tzinfo=UTC)
VALID = {
    "messageId": "0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1b",
    "schemaVersion": "1.0",
    "messageType": "desired",
    "emitter": "api",
    "module": "core",
    "resourceType": "account",
    "resourceId": "0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1c",
    "operation": "changed",
    "desiredGeneration": 1,
    "requestedBy": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
    "correlationId": "0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1d",
    "causationId": "0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1e",
    "occurredAt": "2026-10-15T14:00:00Z",
    "data": {"lifecycle": "present", "reconciliation": "active"},
}


def test_the_publication_adds_the_publisher_identity_and_the_time() -> None:
    body = json.loads(publication_envelope(VALID, WHEN))
    assert body["publishedBy"] == PUBLISHED_BY
    assert body["publishedAt"].startswith("2026-10-15T14:00:01")
    assert body["emitter"] == "api"


@pytest.mark.parametrize("field", ["messageId", "module", "resourceId", "data"])
def test_a_message_outside_the_envelope_is_rejected(field: str) -> None:
    broken = {key: value for key, value in VALID.items() if key != field}
    with pytest.raises(PublicationRejectedError):
        publication_envelope(broken, WHEN)


def test_an_unknown_field_is_rejected() -> None:
    with pytest.raises(PublicationRejectedError):
        publication_envelope({**VALID, "campoNovo": "x"}, WHEN)


def test_an_absent_optional_field_is_not_published_as_null() -> None:
    # O schema do envelope recusa `null`: campo opcional ausente continua ausente.
    body = json.loads(publication_envelope(VALID, WHEN))
    assert "observedGeneration" not in body
    assert None not in body.values()
