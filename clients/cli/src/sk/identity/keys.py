"""Geração, assinatura e manipulação de chaves de service account (decisão 0094).

A chave privada nasce e fica exclusivamente no cliente: o servidor recebe apenas a chave
pública. O arquivo gravado localmente adota o formato do Zitadel:
`{"type": "serviceaccount", "keyId": "<keyId>", "key": "<PEM>", "userId": "<userId>"}`,
com permissão 0600 e gravação exclusiva.
"""

import base64
import hashlib
import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from sk.files import create_private_file, write_private_file

DEFAULT_EXPIRES_IN_DAYS = 90
MAXIMUM_EXPIRES_IN_DAYS = 365
MINIMUM_RSA_KEY_SIZE = 2048


class KeyFileError(Exception):
    """Erro ao ler, validar ou gravar o arquivo de chave."""


@dataclass(frozen=True, slots=True)
class GeneratedKeyPair:
    """Par de chaves RSA gerado localmente."""

    private_pem: str
    public_pem: str
    fingerprint: str
    expires_at: str


def _base64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def _format_expiry(expires_in_days: int) -> str:
    if expires_in_days <= 0:
        raise ValueError("expires-in must be greater than 0")
    if expires_in_days > MAXIMUM_EXPIRES_IN_DAYS:
        raise ValueError(f"expires-in cannot exceed {MAXIMUM_EXPIRES_IN_DAYS} days")
    return (datetime.now(UTC) + timedelta(days=expires_in_days)).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_key_pair(expires_in_days: int = DEFAULT_EXPIRES_IN_DAYS) -> GeneratedKeyPair:
    """Gera um par de chaves RSA de 2048 bits e calcula o fingerprint SPKI SHA-256."""
    expires_at = _format_expiry(expires_in_days)
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=MINIMUM_RSA_KEY_SIZE,
    )
    private_pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    ).decode("utf-8")
    public_key = private_key.public_key()
    public_pem = public_key.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    spki_der = public_key.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    fingerprint = hashlib.sha256(spki_der).hexdigest()
    return GeneratedKeyPair(
        private_pem=private_pem,
        public_pem=public_pem,
        fingerprint=fingerprint,
        expires_at=expires_at,
    )


def parse_public_key_file(
    path: Path, expires_in_days: int = DEFAULT_EXPIRES_IN_DAYS
) -> tuple[str, str, str]:
    """Lê uma chave pública RSA existente (BYO key), valida o tamanho e calcula o fingerprint.

    Devolve `(public_pem, fingerprint, expires_at)`.
    """
    expires_at = _format_expiry(expires_in_days)
    try:
        content = path.read_bytes()
    except OSError as error:
        raise KeyFileError(f"could not read public key file {path}: {error.strerror}") from error
    try:
        loaded = serialization.load_pem_public_key(content)
    except Exception as error:
        raise KeyFileError(f"file {path} is not a valid PEM public key") from error
    if not isinstance(loaded, rsa.RSAPublicKey):
        raise KeyFileError(f"public key in {path} must be an RSA key")
    if loaded.key_size < MINIMUM_RSA_KEY_SIZE:
        raise KeyFileError(
            f"RSA key in {path} is too small ({loaded.key_size} bits; minimum is "
            f"{MINIMUM_RSA_KEY_SIZE})"
        )
    public_pem = loaded.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    ).decode("utf-8")
    spki_der = loaded.public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    fingerprint = hashlib.sha256(spki_der).hexdigest()
    return public_pem, fingerprint, expires_at


def write_key_file(path: Path, *, private_pem: str, user_id: str = "", key_id: str = "") -> None:
    """Grava o arquivo de chave exclusivamente (recusa sobrescrever), com permissão 0600."""
    payload = {
        "type": "serviceaccount",
        "keyId": key_id,
        "key": private_pem,
        "userId": user_id,
    }
    content = json.dumps(payload, indent=2) + "\n"
    try:
        create_private_file(path, content)
    except FileExistsError as error:
        raise KeyFileError(
            f"key file {path} already exists. Choose another path or delete the existing file."
        ) from error
    except OSError as error:
        raise KeyFileError(f"could not write key file {path}: {error.strerror}") from error


def update_key_file(path: Path, *, user_id: str, key_id: str) -> None:
    """Atualiza `keyId` e `userId` em um arquivo de chave existente, preservando a chave privada."""
    try:
        content = path.read_text(encoding="utf-8")
        data = cast(dict[str, Any], json.loads(content))
    except OSError as error:
        raise KeyFileError(f"could not read key file {path}: {error.strerror}") from error
    except json.JSONDecodeError as error:
        raise KeyFileError(f"invalid JSON in key file {path}") from error

    data["userId"] = user_id
    data["keyId"] = key_id
    try:
        write_private_file(path, json.dumps(data, indent=2) + "\n")
    except OSError as error:
        raise KeyFileError(f"could not update key file {path}: {error.strerror}") from error


def read_key_file(path: Path) -> dict[str, str]:
    """Lê e valida o arquivo de chave da service account."""
    try:
        content = path.read_text(encoding="utf-8")
        raw = json.loads(content)
    except FileNotFoundError as error:
        raise KeyFileError(f"key file not found: {path}") from error
    except OSError as error:
        raise KeyFileError(f"could not read key file {path}: {error.strerror}") from error
    except json.JSONDecodeError as error:
        raise KeyFileError(f"invalid JSON in key file: {path}") from error

    if not isinstance(raw, dict):
        raise KeyFileError(f"invalid key file format in {path}: expected a JSON object")
    data = cast(dict[str, Any], raw)
    if data.get("type") != "serviceaccount":
        raise KeyFileError(
            f"invalid key file in {path}: type must be 'serviceaccount', got {data.get('type')!r}"
        )
    key_pem = data.get("key")
    if not isinstance(key_pem, str) or not key_pem.strip():
        raise KeyFileError(f"invalid key file in {path}: missing or empty 'key' field")
    user_id = data.get("userId")
    if not isinstance(user_id, str) or not user_id.strip():
        raise KeyFileError(f"invalid key file in {path}: missing or empty 'userId' field")
    key_id = data.get("keyId")
    if not isinstance(key_id, str) or not key_id.strip():
        raise KeyFileError(
            f"key file {path} has no keyId. Complete it with `sk ipm serviceaccount key-file`."
        )
    return {
        "type": "serviceaccount",
        "key": key_pem,
        "userId": user_id,
        "keyId": key_id,
    }


def sign_jwt_assertion(
    private_pem: str,
    key_id: str,
    user_id: str,
    issuer: str,
    *,
    validity_seconds: int = 300,
) -> str:
    """Assina uma assertion JWT RS256 para troca no token endpoint (RFC 7523)."""
    try:
        private_key = serialization.load_pem_private_key(private_pem.encode("utf-8"), password=None)
    except Exception as error:
        raise KeyFileError("could not load private key from key file") from error
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise KeyFileError("key in key file is not an RSA private key")

    now = int(time.time())
    header = {"alg": "RS256", "typ": "JWT", "kid": key_id}
    payload = {
        "iss": user_id,
        "sub": user_id,
        "aud": issuer,
        "iat": now,
        "exp": now + validity_seconds,
    }
    header_b64 = _base64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_b64 = _base64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_b64}.{payload_b64}"
    signature = private_key.sign(
        signing_input.encode("ascii"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    signature_b64 = _base64url_encode(signature)
    return f"{signing_input}.{signature_b64}"
