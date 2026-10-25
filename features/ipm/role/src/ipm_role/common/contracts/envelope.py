"""Leitura do envelope das mensagens consumidas, em modo tolerante (`docs/SCHEMA.md` §13, §15)."""

import json
from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError

from ipm_role.common.contracts import generated
from ipm_role.common.contracts.base import fields_of, supports_major, validate_tolerant


class EnvelopeError(Exception):
    """A mensagem não é um envelope aceitável. `reason` nunca contém valores `confidential`."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def read_envelope(raw: bytes | str | Mapping[str, Any]) -> generated.MessageEnvelope:
    """Lê o envelope (JSON ou já decodificado) e confere o `MAJOR` do `schemaVersion`.

    Propriedades desconhecidas são ignoradas; todo campo conhecido continua validado.
    """
    try:
        document: Any = json.loads(raw) if isinstance(raw, bytes | str) else raw
        envelope = validate_tolerant(generated.MessageEnvelope, document)
    except ValidationError as error:
        raise EnvelopeError(f"invalid envelope fields: {fields_of(error)}") from None
    except ValueError:
        raise EnvelopeError("message is not valid JSON") from None
    if not supports_major(envelope.schema_version):
        raise EnvelopeError("schemaVersion MAJOR is not supported")
    return envelope
