"""Digest do pedido e identidade da Operation (`docs/SSOT.md` §7.2 e §12)."""

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from core.api.errors import bad_request
from core.ids import new_identifier

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def request_digest(content: Mapping[str, Any]) -> str:
    """SHA-256 (hexadecimal minúsculo) da forma canônica do conteúdo pedido.

    Forma canônica: JSON com chaves ordenadas, sem espaços, em UTF-8. O digest detecta o reuso
    da mesma chave de idempotência com outro conteúdo.
    """
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def operation_id_for(
    *, module: str, resource_type: str, requested_by: str, idempotency_key: str | None
) -> str:
    """Identidade da Operation.

    Com chave de idempotência, é derivada de forma determinística no escopo do solicitante e do
    tipo: a repetição do pedido produz o mesmo `operationId`, e chaves iguais de solicitantes
    diferentes produzem identidades diferentes. A chave em si não é guardada nem transportada.
    Sem chave, é aleatória.
    """
    if idempotency_key is None:
        return new_identifier()
    if not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise bad_request(
            "Idempotency-Key deve ter de 1 a 128 caracteres entre letras, dígitos, ponto, "
            "hífen, sublinhado e dois-pontos.",
            field="Idempotency-Key",
        )
    material = "\0".join((module, resource_type, requested_by, idempotency_key))
    return hashlib.sha256(material.encode("utf-8")).hexdigest()
