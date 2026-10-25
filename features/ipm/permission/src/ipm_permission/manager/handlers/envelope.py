"""Validação do envelope das mensagens consumidas pelo Manager (`docs/MESSAGING.md`)."""

from collections.abc import Mapping
from typing import Any

from ipm_permission.common.contracts import generated
from ipm_permission.common.contracts.envelope import EnvelopeError, read_envelope
from ipm_permission.common.resource import MODULE
from ipm_permission.manager.domain.errors import PermanentMessageError
from ipm_permission.manager.domain.kind import ResourceKind


def parse_envelope(
    kind: ResourceKind, raw_message: Mapping[str, Any], *, message_type: str, emitter: str
) -> generated.MessageEnvelope:
    try:
        envelope = read_envelope(raw_message)
    except EnvelopeError as error:
        raise PermanentMessageError(error.reason) from None
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
