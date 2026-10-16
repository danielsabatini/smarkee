"""Leitura tolerante de mensagens internas (`docs/SCHEMA.md` §15 e §13)."""

from typing import Any

import pytest
from pydantic import ValidationError

from ipm_organization_manager.contracts import generated
from ipm_organization_manager.contracts.base import supports_major, validate_tolerant

ENVELOPE: dict[str, Any] = {
    "messageId": "0199c8b2-1a2b-7c3d-8e4f-5a6b7c8d9e0f",
    "schemaVersion": "1.0",
    "messageType": "observed",
    "emitter": "observer",
    "module": "ipm",
    "resourceType": "organization",
    "resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
    "operation": "changed",
    "presence": "present",
    "observedAt": "2026-10-09T14:00:00Z",
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


def test_the_manager_accepts_a_requested_with_an_unknown_field_and_refuses_another_major() -> None:
    from ipm_organization_manager.domain.errors import PermanentMessageError
    from ipm_organization_manager.domain.kind import ORGANIZATION
    from ipm_organization_manager.handlers.envelope import parse_envelope

    requested: dict[str, Any] = {
        **ENVELOPE,
        "messageType": "requested",
        "emitter": "receiver",
        "operation": "create",
        "requestedBy": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e",
        "correlationId": "0199c8b0-0a1b-7c2d-8e3f-4a5b6c7d8e9f",
        "futureField": "x",
    }
    for key in ("presence", "observedAt"):
        requested.pop(key)

    parsed = parse_envelope(ORGANIZATION, requested, message_type="requested", emitter="receiver")
    assert parsed.resource_id == ENVELOPE["resourceId"]

    with pytest.raises(PermanentMessageError):
        parse_envelope(
            ORGANIZATION,
            {**requested, "schemaVersion": "2.0"},
            message_type="requested",
            emitter="receiver",
        )
