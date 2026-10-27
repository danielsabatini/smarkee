"""Validação das chaves públicas da service account, sem I/O (decisão 0094).

A API recebe só chaves **públicas** (a privada nasce e fica no cliente). Cada uma é lida como
RSA SubjectPublicKeyInfo em PEM, exige no mínimo 2048 bits e recebe o `fingerprint`: SHA-256, em
hexadecimal minúsculo, do DER SPKI. O PEM é regravado no formato canônico, então a mesma chave
sempre produz os mesmos bytes e o mesmo fingerprint.
"""

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

MINIMUM_KEY_BITS = 2048
MAXIMUM_VALIDITY = timedelta(days=365)
MAXIMUM_KEYS = 3


class InvalidKeyError(ValueError):
    """Chave recusada. A mensagem diz a regra violada, nunca o conteúdo enviado."""


@dataclass(frozen=True, slots=True)
class DesiredKey:
    public_key: str
    expires_at: str
    fingerprint: str

    def as_dict(self) -> dict[str, str]:
        return {
            "publicKey": self.public_key,
            "expiresAt": self.expires_at,
            "fingerprint": self.fingerprint,
        }


def _canonical(public_key_pem: str) -> tuple[str, str]:
    try:
        key = serialization.load_pem_public_key(public_key_pem.encode("ascii"))
    except ValueError, UnicodeEncodeError:
        raise InvalidKeyError("A chave pública não é um PEM SubjectPublicKeyInfo válido.") from None
    if not isinstance(key, rsa.RSAPublicKey):
        raise InvalidKeyError("A chave pública deve ser RSA.")
    if key.key_size < MINIMUM_KEY_BITS:
        raise InvalidKeyError(f"A chave RSA deve ter no mínimo {MINIMUM_KEY_BITS} bits.")
    der = key.public_bytes(
        serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
    )
    pem = key.public_bytes(
        serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode("ascii")
    return pem, hashlib.sha256(der).hexdigest()


def _utc_text(moment: datetime) -> str:
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def desired_keys(
    specifications: Iterable[tuple[str, datetime]],
    *,
    now: datetime,
    retained: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[DesiredKey]:
    """Valida as chaves pedidas (par `publicKey`, `expiresAt`) e devolve as do `desired`.

    Regras: de 1 a 3 chaves, sem repetição, vencimento no futuro e em até 365 dias. Uma chave que
    já está no `desired` (`retained`, por fingerprint) é mantida como está, mesmo vencida: reenviar
    a lista lida não renova nem recusa as chaves antigas.
    """
    keys: dict[str, DesiredKey] = {}
    for public_key, expires_at in specifications:
        pem, fingerprint = _canonical(public_key)
        if fingerprint in keys:
            raise InvalidKeyError("A mesma chave pública foi informada mais de uma vez.")
        kept = (retained or {}).get(fingerprint)
        if kept is not None:
            keys[fingerprint] = DesiredKey(
                str(kept["publicKey"]), str(kept["expiresAt"]), fingerprint
            )
            continue
        if expires_at.tzinfo is None:
            raise InvalidKeyError("O vencimento da chave deve ter fuso explícito.")
        if expires_at <= now:
            raise InvalidKeyError("O vencimento da chave deve estar no futuro.")
        if expires_at > now + MAXIMUM_VALIDITY:
            raise InvalidKeyError("O vencimento da chave deve ser em até 365 dias.")
        keys[fingerprint] = DesiredKey(pem, _utc_text(expires_at), fingerprint)
    if not 1 <= len(keys) <= MAXIMUM_KEYS:
        raise InvalidKeyError(f"Informe de 1 a {MAXIMUM_KEYS} chaves públicas.")
    return sorted(keys.values(), key=lambda key: key.fingerprint)
