"""Validação do envelope das mensagens consumidas pelo Manager

(`docs/messaging/MESSAGING.md`)."""

from collections.abc import Mapping
from typing import Any

from core_account.common.contracts import generated
from core_account.common.contracts.envelope import EnvelopeError, read_envelope
from core_account.common.resource import MODULE
from core_account.manager.domain.errors import PermanentMessageError
from core_account.manager.domain.kind import ResourceKind


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
