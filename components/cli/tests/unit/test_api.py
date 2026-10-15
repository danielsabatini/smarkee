"""Cliente da API do cadastro (`sk.api`): contrato do pedido, respostas e erros."""

import json
import urllib.error
from email.message import Message
from io import BytesIO
from typing import Any

import pytest

from sk.api import (
    ApiRejectedError,
    ApiUnavailableError,
    submit_registration,
    validate_registration,
)
from sk.oidc import OidcError


class FakeResponse:
    def __init__(self, status: int, body: dict[str, Any] | bytes) -> None:
        self.status = status
        self._body = body if isinstance(body, bytes) else json.dumps(body).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> FakeResponse:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class Recorder:
    """Substitui o `urlopen`: registra o pedido e devolve a resposta preparada."""

    def __init__(self, response: object) -> None:
        self.response = response
        self.requests: list[Any] = []

    def __call__(self, request: Any, timeout: float) -> FakeResponse:
        self.requests.append(request)
        if isinstance(self.response, BaseException):
            raise self.response
        assert isinstance(self.response, FakeResponse)
        return self.response


def http_error(
    status: int, body: dict[str, Any], retry_after: str | None = None
) -> urllib.error.HTTPError:
    headers = Message()
    if retry_after is not None:
        headers["Retry-After"] = retry_after
    return urllib.error.HTTPError(
        "https://api.example/v1/core/users",
        status,
        "erro",
        headers,
        BytesIO(json.dumps(body).encode()),
    )


def submit(opener: Recorder, **overrides: Any) -> Any:
    arguments: dict[str, Any] = {
        "given_name": "Ana",
        "family_name": "Souza",
        "email": "ana@example.com",
        "allow_insecure_http": False,
        "opener": opener,
    }
    arguments.update(overrides)
    return submit_registration("https://api.example", **arguments)


ACCEPTED = {"resourceId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e", "operationId": "op-1"}


def test_the_request_is_anonymous_and_carries_only_the_contract_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Mesmo com um token salvo no ambiente, o cadastro não o envia.
    monkeypatch.setenv("SK_AUTH_CLIENT_ID", "client-1")
    opener = Recorder(FakeResponse(202, ACCEPTED))

    accepted = submit(opener)

    request = opener.requests[0]
    assert request.get_method() == "POST"
    assert request.full_url == "https://api.example/v1/core/users"
    assert request.get_header("Authorization") is None
    assert json.loads(request.data) == {
        "givenName": "Ana",
        "familyName": "Souza",
        "email": "ana@example.com",
    }
    assert accepted.resource_id == ACCEPTED["resourceId"]
    assert accepted.operation_id == "op-1"


def test_a_password_is_never_part_of_the_request() -> None:
    opener = Recorder(FakeResponse(202, ACCEPTED))
    submit(opener)
    assert b"password" not in opener.requests[0].data.lower()


def test_a_rejected_field_maps_to_the_error_and_the_field() -> None:
    opener = Recorder(
        http_error(
            400, {"errorCode": "ValidationFailed", "message": "Campo inválido", "field": "email"}
        )
    )
    with pytest.raises(ApiRejectedError) as raised:
        submit(opener)
    assert raised.value.status == 400
    assert raised.value.field == "email"
    assert raised.value.error_code == "ValidationFailed"


def test_rate_limit_keeps_the_retry_after_hint() -> None:
    opener = Recorder(http_error(429, {"errorCode": "RateLimited", "message": "x"}, "42"))
    with pytest.raises(ApiRejectedError) as raised:
        submit(opener)
    assert raised.value.status == 429
    assert raised.value.retry_after_seconds == 42


def test_a_server_error_is_unavailable() -> None:
    opener = Recorder(http_error(503, {"errorCode": "ServiceUnavailable", "message": "x"}))
    with pytest.raises(ApiUnavailableError):
        submit(opener)


def test_a_network_failure_is_unavailable() -> None:
    opener = Recorder(urllib.error.URLError("connection refused"))
    with pytest.raises(ApiUnavailableError):
        submit(opener)


def test_a_response_outside_the_contract_is_unavailable() -> None:
    with pytest.raises(ApiUnavailableError):
        submit(Recorder(FakeResponse(202, {"resourceId": "x"})))


def test_a_non_json_body_is_unavailable() -> None:
    with pytest.raises(ApiUnavailableError):
        submit(Recorder(FakeResponse(202, b"<html>")))


def test_plain_http_is_refused_without_permission() -> None:
    opener = Recorder(FakeResponse(202, ACCEPTED))
    with pytest.raises(OidcError):
        submit_registration(
            "http://api.example",
            given_name="Ana",
            family_name="Souza",
            email="ana@example.com",
            allow_insecure_http=False,
            opener=opener,
        )
    assert opener.requests == []


@pytest.mark.parametrize(
    ("given", "family", "email", "message"),
    [
        ("  ", "Souza", "ana@example.com", "--name não pode ser vazio"),
        ("Ana", "", "ana@example.com", "--surname não pode ser vazio"),
        ("Ana", "x" * 257, "ana@example.com", "excede 256"),
        ("Ana", "Souza", "sem-arroba", "formato de um e-mail"),
        ("Ana", "Souza", "a@semponto", "formato de um e-mail"),
        ("Ana", "Souza", "a b@example.com", "formato de um e-mail"),
        ("Ana", "Souza", "a@example.com" + "x" * 250, "tamanho"),
    ],
)
def test_invalid_data_is_refused_before_any_request(
    given: str, family: str, email: str, message: str
) -> None:
    opener = Recorder(FakeResponse(202, ACCEPTED))
    with pytest.raises(ValueError, match=message):
        submit_registration(
            "https://api.example",
            given_name=given,
            family_name=family,
            email=email,
            allow_insecure_http=False,
            opener=opener,
        )
    assert opener.requests == []


def test_validate_accepts_a_common_address() -> None:
    validate_registration("Ana", "Souza", "ana.souza+teste@dominio.com.br")
