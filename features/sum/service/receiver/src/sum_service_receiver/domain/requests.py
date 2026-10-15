"""Regras de entrada do Receiver para `sum.service` (decisão 0033). Puro.

O Receiver valida o formato, confere a role da ação e atribui os identificadores. Quem decide se a
ligação é aceita (catálogo, unicidade, versão) é o Manager.
"""

import hashlib
import json
import re
import uuid
from typing import Any

from sum_service_receiver.domain.errors import bad_request

SERVICE_PATTERN = re.compile(r"^[a-z][a-z0-9]*$")
RESOURCE_ID_PATTERN = re.compile(r"^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")
VERSION_PATTERN = re.compile(r"^[A-Za-z0-9-]{1,64}$")
IDEMPOTENCY_NAMESPACE = uuid.UUID("0199c8b0-0000-7000-8000-00000000f00d")


def validate_service(value: object) -> str:
    if (
        not isinstance(value, str)
        or not SERVICE_PATTERN.fullmatch(value)
        or not 2 <= len(value) <= 32
    ):
        raise bad_request(
            "serviço inválido: use um nome curto em minúsculas, como ipm.", field="service"
        )
    return value


def validate_resource_id(value: str) -> str:
    if not RESOURCE_ID_PATTERN.fullmatch(value):
        raise bad_request("identificador inválido.", field="resourceId")
    return value


def validate_version(value: str | None) -> str:
    if value is None or not VERSION_PATTERN.fullmatch(value):
        raise bad_request(
            "resourceVersion é obrigatório e deve ser o valor da última leitura.",
            field="resourceVersion",
        )
    return value


def request_digest(document: dict[str, Any]) -> str:
    """SHA-256 do corpo canônico do pedido: a mesma chave de idempotência com outro corpo é
    `422`."""
    canonical = json.dumps(document, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def operation_id_for(subject: str, idempotency_key: str) -> str:
    """Identificador determinístico da operação para uma chave de idempotência do solicitante."""
    return str(uuid.uuid5(IDEMPOTENCY_NAMESPACE, f"{subject}\0{idempotency_key}"))
