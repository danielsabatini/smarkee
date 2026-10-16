"""Base HTTP do `sk` para a API da plataforma (`docs/RESOURCE-CONTROL-LOOP.md`, §6.1).

Reúne a chamada autenticada (`call_api`), o envio de um pedido já montado (`send`) e os erros
comuns aos clientes de cada feature (`features/core/account`, `features/sum/service`). Cada cliente
conhece o contrato da sua feature; aqui só há o que não depende dela.

A CLI não tem dependências HTTP além da biblioteca padrão; por isso usa `urllib`, como o
`sk.identity.oidc`. O servidor é a autoridade sobre o conteúdo: as validações locais só evitam
pedidos que certamente seriam recusados.
"""

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from typing import Any, cast

from sk.identity.oidc import ensure_secure_url

HTTP_TIMEOUT_SECONDS = 10.0

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


def send(request: urllib.request.Request, *, opener: Opener | None = None) -> tuple[int, object]:
    """Envia o pedido e devolve `(status, corpo JSON)`.

    `4xx` vira `ApiRejectedError` com o motivo da API; `5xx`, rede ou corpo fora de JSON viram
    `ApiUnavailableError`.
    """
    open_url = opener or urllib.request.urlopen  # resolvido na chamada (testes substituem)
    try:
        with open_url(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            return response.status, json.loads(response.read() or b"{}")
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
        raise ApiUnavailableError(f"the API answered HTTP {error.code}") from None
    except (urllib.error.URLError, OSError, TimeoutError) as error:
        raise ApiUnavailableError(f"could not reach the API ({type(error).__name__})") from None
    except ValueError:
        raise ApiUnavailableError("the API response is not JSON") from None


def call_api(
    method: str,
    api_url: str,
    path: str,
    *,
    token: str,
    body: Mapping[str, object] | None = None,
    query: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
    allow_insecure_http: bool,
    opener: Opener | None = None,
) -> tuple[int, object]:
    """Chamada autenticada (`Authorization: Bearer`). Devolve `(status, corpo JSON)`.

    Erros como em `send`. O token nunca entra em mensagem de erro.
    """
    ensure_secure_url(api_url, allow_insecure_http=allow_insecure_http)
    url = api_url.rstrip("/") + path
    if query:
        url += "?" + urllib.parse.urlencode(query)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    request_headers = {
        "Accept": "application/json",
        "Authorization": f"Bearer {token}",
        **({"Content-Type": "application/json"} if data is not None else {}),
        **(headers or {}),
    }
    request = urllib.request.Request(  # noqa: S310 (esquema validado por ensure_secure_url)
        url, data=data, method=method, headers=request_headers
    )
    return send(request, opener=opener)
