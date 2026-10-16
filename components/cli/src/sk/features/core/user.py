"""Cliente de `core/user` na API da plataforma: o cadastro (`docs/RESOURCE-CONTROL-LOOP.md`, §6.1).

O cadastro (`POST /v1/core/users`) é anônimo: esta chamada **nunca** envia `Authorization`,
mesmo que existam credenciais salvas. O servidor é a autoridade sobre o conteúdo: as validações
locais só evitam pedidos que certamente seriam recusados.
"""

import json
import urllib.request
from dataclasses import dataclass
from typing import cast

from sk.http import ApiUnavailableError, Opener, send
from sk.identity.oidc import ensure_secure_url

USER_REGISTRATION_PATH = "/v1/core/users"
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
            raise ValueError(f"{label} não pode ser vazio.")
        if len(value.strip()) > MAXIMUM_NAME_LENGTH:
            raise ValueError(f"{label} excede {MAXIMUM_NAME_LENGTH} caracteres.")
    stripped = email.strip()
    if not MINIMUM_EMAIL_LENGTH <= len(stripped) <= MAXIMUM_EMAIL_LENGTH:
        raise ValueError("--email tem tamanho fora do permitido.")
    local, separator, domain = stripped.partition("@")
    if not separator or not local or "." not in domain or domain.startswith(".") or " " in stripped:
        raise ValueError("--email não tem o formato de um e-mail.")


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
        raise ApiUnavailableError(f"resposta inesperada da API (HTTP {status})")
    document = cast(dict[str, object], payload)
    resource_id = document.get("resourceId")
    operation_id = document.get("operationId")
    if not isinstance(resource_id, str) or not isinstance(operation_id, str):
        raise ApiUnavailableError("a resposta da API não traz resourceId e operationId")
    return RegistrationAccepted(resource_id=resource_id, operation_id=operation_id)
