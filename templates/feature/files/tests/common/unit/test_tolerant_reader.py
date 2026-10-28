"""Leitura tolerante de mensagens internas (`docs/data/SCHEMA.md` §15 e §13)."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from @@PACKAGE@@.common.contracts import generated
from @@PACKAGE@@.common.contracts.base import supports_major, validate_tolerant
from @@PACKAGE@@.common.contracts.envelope import EnvelopeError, read_envelope

ENVELOPE: dict[str, Any] = {
    "messageId": "0199c8b2-1a2b-7c3d-8e4f-5a6b7c8d9e0f",
    "schemaVersion": "1.0",
    "messageType": "desired",
    "emitter": "api",
    "module": "@@MODULE@@",
    "resourceType": "@@TYPE@@",
    "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
    "operation": "changed",
    "desiredGeneration": 1,
    "requestedBy": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
    "correlationId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
    "causationId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
    "occurredAt": "2026-10-09T14:00:00Z",
    "publishedAt": "2026-10-09T14:00:01Z",
    "data": {},
}


def test_the_consumer_ignores_an_unknown_field_of_a_newer_minor() -> None:
    message: dict[str, Any] = {**ENVELOPE, "schemaVersion": "1.1", "futureField": "x"}

    envelope = validate_tolerant(generated.MessageEnvelope, message)

    assert envelope.resource_id == ENVELOPE["resourceId"]
    assert not hasattr(envelope, "futureField")


def test_the_strict_mode_of_production_still_rejects_an_unknown_field() -> None:
    with pytest.raises(ValidationError):
        generated.MessageEnvelope.model_validate({**ENVELOPE, "futureField": "x"})


def test_the_tolerant_mode_still_validates_the_known_fields() -> None:
    with pytest.raises(ValidationError):
        validate_tolerant(generated.MessageEnvelope, {**ENVELOPE, "messageType": "invalido"})


@pytest.mark.parametrize(
    ("version", "supported"), [("1.0", True), ("1.7", True), ("2.0", False), ("0.9", False)]
)
def test_only_the_supported_major_is_accepted(version: str, supported: bool) -> None:
    assert supports_major(version) is supported


def test_read_envelope_accepts_json_bytes_and_decoded_documents() -> None:
    from_bytes = read_envelope(json.dumps(ENVELOPE).encode())
    from_mapping = read_envelope(ENVELOPE)
    assert from_bytes.message_id == from_mapping.message_id == ENVELOPE["messageId"]


def test_read_envelope_ignores_a_field_of_a_newer_minor() -> None:
    envelope = read_envelope({**ENVELOPE, "schemaVersion": "1.4", "futureField": "x"})
    assert envelope.resource_id == ENVELOPE["resourceId"]


@pytest.mark.parametrize(
    ("raw", "reason"),
    [
        (b"{not json", "message is not valid JSON"),
        (json.dumps({**ENVELOPE, "schemaVersion": "2.0"}), "schemaVersion MAJOR is not supported"),
    ],
)
def test_read_envelope_rejects_what_it_cannot_accept(raw: bytes | str, reason: str) -> None:
    with pytest.raises(EnvelopeError) as raised:
        read_envelope(raw)
    assert raised.value.reason == reason


def test_read_envelope_names_the_invalid_fields_but_never_their_values() -> None:
    secret = "valor-confidencial"
    with pytest.raises(EnvelopeError) as raised:
        read_envelope({**ENVELOPE, "messageType": secret})
    assert "messageType" in raised.value.reason
    assert secret not in raised.value.reason
