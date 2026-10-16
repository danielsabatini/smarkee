"""Cliente de `core/account` na API da plataforma (`docs/RESOURCE-CONTROL-LOOP.md`, §6.1).

O cadastro (`POST /v1/core/accounts`) é anônimo: esta chamada **nunca** envia `Authorization`,
mesmo que existam credenciais salvas. O servidor é a autoridade sobre o conteúdo: as validações
locais só evitam pedidos que certamente seriam recusados.
"""

import base64
import json
import urllib.request
from dataclasses import dataclass
from typing import cast

from sk.features.api_contract import (
    OperationStatus,
    RequestAccepted,
    as_object,
    as_text,
    parse_accepted,
    parse_operation,
    validate_identifier,
)
from sk.http import ApiUnavailableError, Opener, call_api, send
from sk.identity.oidc import ensure_secure_url

USER_REGISTRATION_PATH = "/v1/core/accounts"
MAXIMUM_NAME_LENGTH = 256
MINIMUM_EMAIL_LENGTH = 3
MAXIMUM_EMAIL_LENGTH = 254


@dataclass(frozen=True, slots=True)
class RegistrationAccepted:
    """Resposta `202`: a identidade do pedido, para acompanhar o cadastro."""

    resource_id: str
    operation_id: str


def validate_registration(given_name: str, family_name: str, email: str) -> None:
    """Confere localmente os limites do contrato `api-create-request` (SCHEMA.md).

    Lança `ValueError` com a mensagem para o usuário. O servidor valida de novo, com a mesma regra.
    """
    for label, value in (("--name", given_name), ("--surname", family_name)):
        if not value.strip():
            raise ValueError(f"{label} cannot be empty.")
        if len(value.strip()) > MAXIMUM_NAME_LENGTH:
            raise ValueError(f"{label} exceeds {MAXIMUM_NAME_LENGTH} characters.")
    stripped = email.strip()
    if not MINIMUM_EMAIL_LENGTH <= len(stripped) <= MAXIMUM_EMAIL_LENGTH:
        raise ValueError("--email has a size outside the allowed range.")
    local, separator, domain = stripped.partition("@")
    if not separator or not local or "." not in domain or domain.startswith(".") or " " in stripped:
        raise ValueError("--email does not have the format of an e-mail.")


def submit_registration(
    api_url: str,
    *,
    given_name: str,
    family_name: str,
    email: str,
    allow_insecure_http: bool,
    opener: Opener | None = None,
) -> RegistrationAccepted:
    """Envia o pedido de cadastro anônimo e devolve a identidade aceita.

    Levanta `ValueError` para dados inválidos (antes de qualquer chamada), `OidcError` para uma
    URL sem TLS sem permissão, `ApiRejected` para `4xx` e `ApiUnavailable` para o resto.
    """
    validate_registration(given_name, family_name, email)
    ensure_secure_url(api_url, allow_insecure_http=allow_insecure_http)
    url = api_url.rstrip("/") + USER_REGISTRATION_PATH
    body = json.dumps(
        {"givenName": given_name.strip(), "familyName": family_name.strip(), "email": email.strip()}
    ).encode("utf-8")
    request = urllib.request.Request(  # noqa: S310 (esquema validado por ensure_secure_url)
        url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    status, payload = send(request, opener=opener)
    if status != 202 or not isinstance(payload, dict):
        raise ApiUnavailableError(f"unexpected API response (HTTP {status})")
    document = cast(dict[str, object], payload)
    resource_id = document.get("resourceId")
    operation_id = document.get("operationId")
    if not isinstance(resource_id, str) or not isinstance(operation_id, str):
        raise ApiUnavailableError("the API response does not carry resourceId and operationId")
    return RegistrationAccepted(resource_id=resource_id, operation_id=operation_id)


@dataclass(frozen=True, slots=True)
class Account:
    """A conta do solicitante, como a API a devolve a ele mesmo."""

    resource_id: str
    resource_version: str
    phase: str
    given_name: str
    family_name: str
    email: str
    platform_access: str
    deletion_protection: bool
    """`True` impede a exclusão (decisão 0043); a API a devolve sempre, e ausente vale `True`."""


def token_subject(access_token: str) -> str:
    """O `sub` do access token (o `resourceId` do próprio usuário), sem verificar a assinatura.

    O token veio do provedor e a API o verifica de novo a cada chamada; aqui só se lê quem é o
    dono da sessão. Levanta `ValueError` se o token não for um JWT legível.
    """
    parts = access_token.split(".")
    if len(parts) != 3:
        raise ValueError("the session token is not readable")
    try:
        padded = parts[1] + "=" * (-len(parts[1]) % 4)
        claims = cast("object", json.loads(base64.urlsafe_b64decode(padded)))
    except ValueError:
        raise ValueError("the session token is not readable") from None
    subject: object = (
        cast("dict[str, object]", claims).get("sub") if isinstance(claims, dict) else None
    )
    if not isinstance(subject, str):
        raise ValueError("the session token has no subject")
    return validate_identifier(subject, what="resourceId")


def _account(document: object) -> Account:
    body = as_object(document, what="account")
    desired = as_object(body.get("desired"), what="user (desired)")
    return Account(
        resource_id=as_text(body, "resourceId", what="account"),
        resource_version=as_text(body, "resourceVersion", what="account"),
        phase=as_text(body, "phase", what="account"),
        given_name=as_text(desired, "givenName", what="user (desired)"),
        family_name=as_text(desired, "familyName", what="user (desired)"),
        email=as_text(desired, "email", what="user (desired)"),
        platform_access=as_text(desired, "platformAccess", what="user (desired)"),
        deletion_protection=desired.get("deletionProtection") is not False,
    )


def get_account(
    api_url: str, *, token: str, resource_id: str, allow_insecure_http: bool
) -> Account:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "GET",
        api_url,
        f"{USER_REGISTRATION_PATH}/{resource_id}",
        token=token,
        allow_insecure_http=allow_insecure_http,
    )
    return _account(document)


def set_account_protection(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    protected: bool,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> RequestAccepted:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "PATCH",
        api_url,
        f"{USER_REGISTRATION_PATH}/{resource_id}",
        token=token,
        body={"resourceVersion": resource_version, "deletionProtection": protected},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return parse_accepted(document)


def delete_account(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> RequestAccepted:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "DELETE",
        api_url,
        f"{USER_REGISTRATION_PATH}/{resource_id}",
        token=token,
        query={"resourceVersion": resource_version},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return parse_accepted(document)


def get_operation(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    operation_id: str,
    allow_insecure_http: bool,
) -> OperationStatus:
    resource_id = validate_identifier(resource_id, what="resourceId")
    operation_id = validate_identifier(operation_id, what="operationId")
    _, document = call_api(
        "GET",
        api_url,
        f"{USER_REGISTRATION_PATH}/{resource_id}/operations/{operation_id}",
        token=token,
        allow_insecure_http=allow_insecure_http,
    )
    return parse_operation(document)
