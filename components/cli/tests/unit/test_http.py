"""Base HTTP (`sk.http`): montagem do pedido autenticado e tradução das falhas."""

import io
import json
import urllib.error
import urllib.request
from email.message import Message
from typing import Any, cast

import pytest

from sk.http import ApiRejectedError, ApiUnavailableError, call_api, send
from sk.identity.oidc import OidcError

API = "https://api.teste"


class Response:
    def __init__(self, body: bytes, status: int = 200) -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class Opener:
    """Substitui `urlopen`: devolve ou levanta o combinado e guarda o pedido e o prazo."""

    def __init__(self, outcome: Response | BaseException) -> None:
        self.outcome = outcome
        self.request: urllib.request.Request | None = None
        self.timeout: float | None = None

    def __call__(self, request: urllib.request.Request, timeout: float = 0) -> Response:
        self.request, self.timeout = request, timeout
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return self.outcome


def ok(document: object, status: int = 200) -> Opener:
    return Opener(Response(json.dumps(document).encode(), status))


def http_error(
    status: int, body: bytes | None = None, headers: dict[str, str] | None = None
) -> urllib.error.HTTPError:
    message = Message()
    for key, value in (headers or {}).items():
        message[key] = value
    return urllib.error.HTTPError(API, status, "x", message, io.BytesIO(body or b""))


def sent(opener: Opener) -> urllib.request.Request:
    assert opener.request is not None
    return opener.request


def call(opener: Opener, **overrides: Any) -> tuple[int, object]:
    arguments: dict[str, Any] = {
        "token": "token-secreto",
        "allow_insecure_http": False,
        "opener": opener,
    }
    return call_api("GET", API, "/v1/x", **{**arguments, **overrides})


# ---------------------------------------------------------------------- pedido


def test_the_request_carries_the_bearer_token_and_accepts_json() -> None:
    opener = ok({"a": 1})
    assert call(opener) == (200, {"a": 1})
    request = sent(opener)
    assert request.get_header("Authorization") == "Bearer token-secreto"
    assert request.get_header("Accept") == "application/json"
    assert request.get_header("Content-type") is None  # sem corpo, sem Content-Type
    assert opener.timeout == 10.0


def test_the_url_is_the_base_without_a_trailing_slash_plus_the_path() -> None:
    opener = ok({})
    call_api("GET", API + "/", "/v1/x", token="t", allow_insecure_http=False, opener=opener)
    assert sent(opener).full_url == f"{API}/v1/x"


def test_a_body_is_sent_as_json_and_the_query_is_encoded() -> None:
    opener = ok({}, 202)
    call_api(
        "POST",
        API,
        "/v1/x",
        token="t",
        body={"nome": "Ação"},
        query={"a": "b c", "d": "&"},
        allow_insecure_http=False,
        opener=opener,
    )
    request = sent(opener)
    assert request.get_method() == "POST"
    assert request.full_url == f"{API}/v1/x?a=b+c&d=%26"
    assert request.get_header("Content-type") == "application/json"
    assert json.loads(cast(bytes, request.data)) == {"nome": "Ação"}


def test_extra_headers_are_added() -> None:
    opener = ok({})
    call(opener, headers={"Idempotency-Key": "k-1"})
    assert sent(opener).get_header("Idempotency-key") == "k-1"


def test_an_empty_body_is_read_as_an_empty_object() -> None:
    assert call(Opener(Response(b""))) == (200, {})


def test_plain_http_is_refused_before_any_request_and_allowed_with_permission() -> None:
    opener = ok({})
    with pytest.raises(OidcError):
        call_api(
            "GET", "http://api.teste", "/v1/x", token="t", allow_insecure_http=False, opener=opener
        )
    assert opener.request is None
    call_api("GET", "http://api.teste", "/v1/x", token="t", allow_insecure_http=True, opener=opener)
    assert sent(opener).full_url == "http://api.teste/v1/x"


# ---------------------------------------------------------------------- falhas


def test_a_4xx_keeps_the_reason_the_code_and_the_field() -> None:
    body = json.dumps({"message": "inválido", "errorCode": "ValidationFailed", "field": "x"})
    with pytest.raises(ApiRejectedError) as caught:
        call(Opener(http_error(400, body.encode())))
    error = caught.value
    assert (error.status, str(error), error.error_code, error.field) == (
        400,
        "inválido",
        "ValidationFailed",
        "x",
    )
    assert error.retry_after_seconds is None


def test_a_4xx_without_a_readable_body_still_says_what_happened() -> None:
    for body in (None, b"isto nao e json", b"[1, 2]"):
        with pytest.raises(ApiRejectedError) as caught:
            call(Opener(http_error(404, body)))
        assert (str(caught.value), caught.value.error_code, caught.value.field) == (
            "HTTP 404",
            "Unknown",
            None,
        )


@pytest.mark.parametrize(
    ("header", "expected"), [("30", 30), ("0", 0), ("-5", 0), ("amanhã", None), (None, None)]
)
def test_retry_after_is_read_when_it_is_a_number(header: str | None, expected: int | None) -> None:
    headers = {"Retry-After": header} if header is not None else None
    with pytest.raises(ApiRejectedError) as caught:
        call(Opener(http_error(429, b"{}", headers)))
    assert caught.value.retry_after_seconds == expected


def test_a_non_text_message_or_field_is_ignored() -> None:
    body = json.dumps({"message": 3, "field": ["x"]}).encode()
    with pytest.raises(ApiRejectedError) as caught:
        call(Opener(http_error(400, body)))
    assert (str(caught.value), caught.value.field) == ("HTTP 400", None)


@pytest.mark.parametrize("status", [500, 502, 503])
def test_a_5xx_is_unavailable_without_the_body(status: int) -> None:
    with pytest.raises(ApiUnavailableError) as caught:
        call(Opener(http_error(status, b'{"message": "detalhe interno"}')))
    assert str(caught.value) == f"a API respondeu com HTTP {status}"


@pytest.mark.parametrize(
    "failure",
    [
        urllib.error.URLError("detalhe-interno"),
        OSError("detalhe-interno"),
        TimeoutError("detalhe-interno"),
    ],
)
def test_a_network_failure_is_unavailable_and_names_only_the_kind(
    failure: BaseException,
) -> None:
    with pytest.raises(ApiUnavailableError) as caught:
        call(Opener(failure))
    assert type(failure).__name__ in str(caught.value)
    assert "detalhe-interno" not in str(caught.value)  # a mensagem do erro não vaza


def test_a_body_that_is_not_json_is_unavailable() -> None:
    with pytest.raises(ApiUnavailableError, match="não é JSON"):
        call(Opener(Response(b"<html>")))


def test_the_token_never_appears_in_an_error_message() -> None:
    failures: list[BaseException] = [
        http_error(400, b'{"message": "recusado"}'),
        http_error(503),
        urllib.error.URLError("falha"),
    ]
    for failure in failures:
        with pytest.raises((ApiRejectedError, ApiUnavailableError)) as caught:
            call(Opener(failure))
        assert "token-secreto" not in str(caught.value)


def test_send_returns_the_status_and_the_body_of_a_prepared_request() -> None:
    request = urllib.request.Request(f"{API}/v1/x", method="POST")
    opener = ok({"resourceId": "r"}, 202)
    assert send(request, opener=opener) == (202, {"resourceId": "r"})
    assert opener.request is request
