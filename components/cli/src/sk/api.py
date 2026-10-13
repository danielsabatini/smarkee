"""Cliente da API da plataforma usado pelo `sk` (`docs/RESOURCE-CONTROL-LOOP.md`, §6.1).

O cadastro (`POST /v1/users`) é anônimo: esta chamada **nunca** envia `Authorization`, mesmo que
existam credenciais salvas. Só a leitura e as escritas autenticadas enviam o token.

A CLI não tem dependências HTTP além da biblioteca padrão; por isso usa `urllib`, como o
`sk.oidc`. O servidor é a autoridade sobre o conteúdo: as validações locais só evitam pedidos
que certamente seriam recusados.
"""

import json
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, cast

from sk.oidc import ensure_secure_url

HTTP_TIMEOUT_SECONDS = 10.0
USER_REGISTRATION_PATH = "/v1/users"
MAXIMUM_NAME_LENGTH = 256
MINIMUM_EMAIL_LENGTH = 3
MAXIMUM_EMAIL_LENGTH = 254

Opener = Callable[..., Any]


class ApiError(Exception):
    """Falha na chamada à API. A mensagem nunca repete os valores enviados."""


class ApiRejectedError(ApiError):
    """A API recusou o pedido (`4xx`), com o motivo que ela devolveu."""

    def __init__(
        self,
        status: int,
        message: str,
        *,
        error_code: str,
        field: str | None = None,
        retry_after_seconds: int | None = None,
    ) -> None:
        super().__init__(message)
        self.status = status
        self.error_code = error_code
        self.field = field
        self.retry_after_seconds = retry_after_seconds


class ApiUnavailableError(ApiError):
    """A API não respondeu de forma utilizável: rede, `5xx` ou resposta fora do contrato."""


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


def _retry_after(headers: Any) -> int | None:
    value = headers.get("Retry-After") if headers is not None else None
    if value is None:
        return None
    try:
        return max(0, int(value))
    except ValueError:
        return None


def _error_body(error: urllib.error.HTTPError) -> dict[str, object]:
    try:
        document = json.loads(error.read() or b"{}")
    except ValueError, OSError:
        return {}
    return cast(dict[str, object], document) if isinstance(document, dict) else {}


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
    open_url = opener or urllib.request.urlopen  # resolvido na chamada (testes substituem)
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
    try:
        with open_url(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            status = response.status
            payload = json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as error:
        document = _error_body(error)
        message = document.get("message")
        if 400 <= error.code < 500:
            field = document.get("field")
            raise ApiRejectedError(
                error.code,
                message if isinstance(message, str) else f"HTTP {error.code}",
                error_code=str(document.get("errorCode", "Unknown")),
                field=field if isinstance(field, str) else None,
                retry_after_seconds=_retry_after(error.headers),
            ) from None
        raise ApiUnavailableError(f"a API respondeu com HTTP {error.code}") from None
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise ApiUnavailableError(
            f"não foi possível alcançar a API ({type(error).__name__})"
        ) from None
    except ValueError:
        raise ApiUnavailableError("a resposta da API não é JSON") from None

    if status != 202 or not isinstance(payload, dict):
        raise ApiUnavailableError(f"resposta inesperada da API (HTTP {status})")
    document = cast(dict[str, object], payload)
    resource_id = document.get("resourceId")
    operation_id = document.get("operationId")
    if not isinstance(resource_id, str) or not isinstance(operation_id, str):
        raise ApiUnavailableError("a resposta da API não traz resourceId e operationId")
    return RegistrationAccepted(resource_id=resource_id, operation_id=operation_id)
