"""Partes comuns dos clientes da API: identificadores, aceite (`202`) e Operation.

Valem para todo recurso do Resource Control Loop (`schemas/common/`): a resposta de aceite e a
Operation têm o mesmo formato em `sum.service`, `ipm.organization` e nos demais tipos. A leitura é
estrita: uma resposta fora do contrato vira `ApiUnavailableError`, e não um valor inventado.
"""

import re
from dataclasses import dataclass
from typing import Any, cast

from sk.http import ApiUnavailableError

# `resourceId` e `operationId` são identificadores opacos: o mesmo padrão de
# `schemas/common/definitions.v1.schema.json` (`resourceId` e `opaqueIdentifier`).
OPAQUE_IDENTIFIER_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")


@dataclass(frozen=True, slots=True)
class RequestAccepted:
    """`202`: a identidade do pedido, para acompanhar a Operation."""

    resource_id: str
    operation_id: str


@dataclass(frozen=True, slots=True)
class OperationStatus:
    """Estado de uma Operation. `reason` só existe quando o pedido foi recusado."""

    operation_id: str
    operation_status: str
    reason: str | None


def validate_identifier(value: str, *, what: str) -> str:
    """Devolve o identificador se ele segue o contrato, ou levanta `ValueError`.

    Os identificadores entram no caminho da URL: aceitar texto livre permitiria `../`, `?` e `#`
    levarem o token da sessão a outro caminho da API. O padrão do contrato só admite letras
    minúsculas, números e hífen, caracteres que não alteram o caminho. A mensagem não repete o
    valor informado.
    """
    if not OPAQUE_IDENTIFIER_PATTERN.fullmatch(value):
        raise ValueError(
            f"{what} invalid: use lowercase letters, digits and hyphen (up to 128 characters)"
        )
    return value


def as_object(document: object, *, what: str) -> dict[str, Any]:
    if not isinstance(document, dict):
        raise ApiUnavailableError(f"API response outside the contract: {what}")
    return cast(dict[str, Any], document)


def as_text(document: dict[str, Any], key: str, *, what: str) -> str:
    value = document.get(key)
    if not isinstance(value, str):
        raise ApiUnavailableError(f"API response without {key}: {what}")
    return value


def parse_accepted(document: object) -> RequestAccepted:
    body = as_object(document, what="acceptance")
    return RequestAccepted(
        resource_id=as_text(body, "resourceId", what="acceptance"),
        operation_id=as_text(body, "operationId", what="acceptance"),
    )


def parse_operation(document: object) -> OperationStatus:
    body = as_object(document, what="operation")
    reason = body.get("operationStatusReason")
    return OperationStatus(
        operation_id=as_text(body, "operationId", what="operation"),
        operation_status=as_text(body, "operationStatus", what="operation"),
        reason=reason if isinstance(reason, str) else None,
    )
