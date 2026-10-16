"""Validação do envelope das mensagens consumidas pelo Manager (`docs/MESSAGING.md`)."""

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from ipm_organization_manager.contracts import generated
from ipm_organization_manager.contracts.base import supports_major, validate_tolerant
from ipm_organization_manager.domain.errors import PermanentMessageError
from ipm_organization_manager.domain.kind import MODULE, ResourceKind

SCHEMA_VERSION = "1.0"


def fields_of(error: ValidationError) -> str:
    return ", ".join(".".join(str(part) for part in item["loc"]) for item in error.errors())


def parse_envelope(
    kind: ResourceKind, raw_message: Mapping[str, Any], *, message_type: str, emitter: str
) -> generated.MessageEnvelope:
    try:
        envelope = validate_tolerant(generated.MessageEnvelope, raw_message)
    except ValidationError as error:
        raise PermanentMessageError(f"envelope inválido nos campos: {fields_of(error)}") from None
    if not supports_major(envelope.schema_version):
        raise PermanentMessageError("MAJOR de schemaVersion não suportado")
    if (
        envelope.message_type.value != message_type
        or envelope.emitter.value != emitter
        or envelope.module != MODULE
        or envelope.resource_type != kind.resource_type
    ):
        raise PermanentMessageError(f"a mensagem não é um {message_type} de {emitter} deste tipo")
    return envelope


def require[T](value: T | None) -> T:
    if value is None:
        raise PermanentMessageError("campo obrigatório ausente")
    return value
