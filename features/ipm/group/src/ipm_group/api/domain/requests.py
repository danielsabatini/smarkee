"""Digest do pedido e validação da chave de idempotência (`docs/data/SSOT.md` §7.2 e §12)."""

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

from ipm_group.api.domain.errors import bad_request

IDEMPOTENCY_KEY_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def request_digest(content: Mapping[str, Any]) -> str:
    """SHA-256 (hexadecimal minúsculo) da forma canônica do conteúdo pedido.

    Forma canônica: JSON com chaves ordenadas, sem espaços, em UTF-8. O digest detecta o reuso
    da mesma chave de idempotência com outro conteúdo.
    """
    canonical = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def checked_idempotency_key(idempotency_key: str | None) -> str | None:
    """A chave informada, ou `None`; recusa uma chave fora do formato."""
    if idempotency_key is not None and not IDEMPOTENCY_KEY_PATTERN.fullmatch(idempotency_key):
        raise bad_request(
            "Idempotency-Key deve ter de 1 a 128 caracteres entre letras, dígitos, ponto, "
            "hífen, sublinhado e dois-pontos.",
            field="Idempotency-Key",
        )
    return idempotency_key
