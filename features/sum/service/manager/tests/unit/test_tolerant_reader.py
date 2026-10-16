"""Leitura tolerante de mensagens internas (`docs/SCHEMA.md` §15 e §13)."""

import json
from typing import Any

import pytest
from pydantic import ValidationError

from sum_service_manager.contracts import generated
from sum_service_manager.contracts.base import supports_major, validate_tolerant
from sum_service_manager.domain.errors import PermanentMessageError
from sum_service_manager.transport.requested import CreateRequest, parse_request

RESOURCE_ID = "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e"
OWNER = "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4f"

ENVELOPE: dict[str, Any] = {
    "messageId": "0199c8b2-1a2b-7c3d-8e4f-5a6b7c8d9e0f",
    "schemaVersion": "1.0",
    "messageType": "requested",
    "emitter": "receiver",
    "module": "sum",
    "resourceType": "service",
    "resourceId": RESOURCE_ID,
    "operation": "create",
    "requestedBy": OWNER,
    "correlationId": "0199c8b2-1a2b-7c3d-8e4f-5a6b7c8d9e10",
    "occurredAt": "2026-10-15T14:00:00Z",
    "publishedAt": "2026-10-15T14:00:01Z",
    "data": {
        "operationId": "0199c8b2-1a2b-7c3d-8e4f-5a6b7c8d9e11",
        "requestDigest": "a" * 64,
        "specification": {"service": "ipm", "ownerUserId": OWNER},
    },
}


def encoded(**changes: Any) -> bytes:
    return json.dumps({**ENVELOPE, **changes}).encode()


def test_the_consumer_ignores_an_unknown_field_of_a_newer_minor() -> None:
    message: dict[str, Any] = {**ENVELOPE, "schemaVersion": "1.1", "futureField": "x"}

    envelope = validate_tolerant(generated.MessageEnvelope, message)

    assert envelope.resource_id == RESOURCE_ID
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


def test_the_manager_accepts_a_requested_with_an_unknown_field_of_a_newer_minor() -> None:
    parsed = parse_request(encoded(schemaVersion="1.1", futureField="x"))
    assert isinstance(parsed, CreateRequest)
    assert parsed.resource_id == RESOURCE_ID and parsed.service == "ipm"


@pytest.mark.parametrize("version", ["2.0", "0.9", "3.1"])
def test_the_manager_refuses_a_requested_of_another_major(version: str) -> None:
    with pytest.raises(PermanentMessageError, match="MAJOR"):
        parse_request(encoded(schemaVersion=version))
