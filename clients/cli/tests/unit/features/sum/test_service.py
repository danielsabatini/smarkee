"""Cliente do `sum.service` (`sk.features.sum.service`): pedidos, identificadores e respostas."""

import json
import urllib.request
from pathlib import Path
from typing import Any, cast

import pytest

from sk.features.sum import service
from sk.http import ApiUnavailableError

API = "https://api.teste"
RID = "01a14168-b59d-7475-8db7-c5cf57fa100b"
OTHER = "b9c4c98c-7392-5016-a724-6e1cd0c1bed9"


class Response:
    def __init__(self, document: object, status: int = 200) -> None:
        self.status = status
        self._body = json.dumps(document).encode()

    def read(self) -> bytes:
        return self._body

    def __enter__(self) -> Response:
        return self

    def __exit__(self, *_: object) -> None:
        return None


class Sent:
    """Substitui `urlopen`: devolve a resposta combinada e guarda o último pedido."""

    def __init__(self, document: object, status: int = 200) -> None:
        self.response = Response(document, status)
        self.request: urllib.request.Request | None = None

    def __call__(self, request: urllib.request.Request, timeout: float = 0) -> Response:
        self.request = request
        return self.response


def link(**changes: object) -> dict[str, Any]:
    document: dict[str, Any] = {
        "resourceId": RID,
        "resourceVersion": "3",
        "desiredGeneration": 2,
        "observedGeneration": 2,
        "phase": "Ready",
        "desired": {"service": "ipm", "lifecycle": "present"},
        "observed": {"servicePermissions": ["ipm.organization.get"]},
    }
    document.update(changes)
    return document


def serve(monkeypatch: pytest.MonkeyPatch, document: object, status: int = 200) -> Sent:
    sent = Sent(document, status)
    monkeypatch.setattr(urllib.request, "urlopen", sent)
    return sent


def request_of(sent: Sent) -> urllib.request.Request:
    assert sent.request is not None
    return sent.request


# ---------------------------------------------------------------------- identificadores


@pytest.mark.parametrize(
    "value", [RID, OTHER, "a", "ab", "0", "abc-123", "r1", "a" * 128, "9f2d-5e8a"]
)
def test_an_identifier_that_follows_the_contract_is_accepted_as_it_is(value: str) -> None:
    assert service.validate_identifier(value, what="resourceId") == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        " ",
        "-a",
        "a-",
        "-",
        "A",
        RID.upper(),
        "a" * 129,
        "../../admin",
        "..",
        ".",
        "a/b",
        "a%2Fb",
        "a_b",
        "a.b",
        f"{RID}?x=1",
        f"{RID}#",
        f"{RID}\n",
        "{" + RID + "}",
        "ç",
    ],
)
def test_an_identifier_outside_the_contract_is_refused_without_being_repeated(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="resourceId invalid") as caught:
        service.validate_identifier(value, what="resourceId")
    assert value.strip() == "" or value not in str(caught.value)


def test_the_pattern_is_the_one_of_the_published_contract() -> None:
    schema = Path(__file__).parents[6] / "schemas" / "common" / "definitions.v1.schema.json"
    defs = json.loads(schema.read_text(encoding="utf-8"))["$defs"]
    assert service.OPAQUE_IDENTIFIER_PATTERN.pattern == defs["resourceId"]["pattern"]
    assert service.OPAQUE_IDENTIFIER_PATTERN.pattern == defs["opaqueIdentifier"]["pattern"]


def test_every_call_that_puts_an_identifier_in_the_path_refuses_a_bad_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = serve(monkeypatch, link())
    bad = "../../admin"
    calls = (
        lambda: service.get_service(API, token="t", resource_id=bad, allow_insecure_http=False),
        lambda: service.disable_service(
            API, token="t", resource_id=bad, resource_version="1", allow_insecure_http=False
        ),
    )
    for call in calls:
        with pytest.raises(ValueError):
            call()
    assert sent.request is None  # nenhum pedido saiu


# ---------------------------------------------------------------------- pedidos


def test_enable_posts_the_service_with_the_idempotency_key(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = serve(monkeypatch, link(), status=201)
    admitted = service.enable_service(
        API, token="t", service="ipm", idempotency_key="chave-1", allow_insecure_http=False
    )
    request = request_of(sent)
    assert (request.get_method(), request.full_url) == ("POST", f"{API}/v1/sum/services")
    assert request.get_header("Idempotency-key") == "chave-1"
    assert json.loads(cast(bytes, request.data)) == {"service": "ipm"}
    assert (admitted.resource_id, admitted.desired_generation) == (RID, 2)


def test_disable_deletes_with_the_resource_version_in_the_query(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = serve(monkeypatch, link(), status=202)
    service.disable_service(
        API, token="t", resource_id=RID, resource_version="3", allow_insecure_http=False
    )
    request = request_of(sent)
    assert request.get_method() == "DELETE"
    assert request.full_url == f"{API}/v1/sum/services/{RID}?resourceVersion=3"


# ---------------------------------------------------------------------- respostas


def test_a_link_is_read_with_its_observed_permissions(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, link())
    found = service.get_service(API, token="t", resource_id=RID, allow_insecure_http=False)
    assert (found.resource_version, found.phase, found.service, found.lifecycle) == (
        "3",
        "Ready",
        "ipm",
        "present",
    )
    assert found.observed_permissions == ("ipm.organization.get",)
    assert (found.desired_generation, found.observed_generation) == (2, 2)
    assert found.failure_reason is None


def test_a_link_not_yet_observed_has_no_observed_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = link()
    del document["observedGeneration"]
    serve(monkeypatch, document)
    found = service.get_service(API, token="t", resource_id=RID, allow_insecure_http=False)
    assert found.observed_generation is None


def test_the_failure_reason_is_read_from_the_false_condition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(
        monkeypatch,
        link(conditions=[{"status": "False", "reason": "ProviderUnavailable"}]),
    )
    found = service.get_service(API, token="t", resource_id=RID, allow_insecure_http=False)
    assert found.failure_reason == "ProviderUnavailable"


@pytest.mark.parametrize("observed", [None, {}])
def test_a_link_not_yet_observed_has_no_permissions(
    monkeypatch: pytest.MonkeyPatch, observed: object
) -> None:
    serve(monkeypatch, link(observed=observed))
    found = service.get_service(API, token="t", resource_id=RID, allow_insecure_http=False)
    assert found.observed_permissions == ()


@pytest.mark.parametrize(
    "missing", ["resourceId", "resourceVersion", "desiredGeneration", "phase", "desired"]
)
def test_a_link_without_a_required_field_is_a_contract_failure(
    monkeypatch: pytest.MonkeyPatch, missing: str
) -> None:
    document = link()
    del document[missing]
    serve(monkeypatch, document)
    with pytest.raises(ApiUnavailableError, match=r"outside the contract|without "):
        service.get_service(API, token="t", resource_id=RID, allow_insecure_http=False)


@pytest.mark.parametrize("bad", [[], "texto", 3, None])
def test_a_response_that_is_not_an_object_is_a_contract_failure(
    monkeypatch: pytest.MonkeyPatch, bad: object
) -> None:
    serve(monkeypatch, bad)
    with pytest.raises(ApiUnavailableError, match="outside the contract"):
        service.get_service(API, token="t", resource_id=RID, allow_insecure_http=False)


def test_invalid_service_permissions_are_a_contract_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    serve(monkeypatch, link(observed={"servicePermissions": "x"}))
    with pytest.raises(ApiUnavailableError, match="servicePermissions"):
        service.get_service(API, token="t", resource_id=RID, allow_insecure_http=False)


@pytest.mark.parametrize("document", [{"items": "x"}, {}, []])
def test_a_list_without_items_is_a_contract_failure(
    monkeypatch: pytest.MonkeyPatch, document: object
) -> None:
    serve(monkeypatch, document)
    with pytest.raises(ApiUnavailableError):
        service.list_services(API, token="t", allow_insecure_http=False)


def test_a_list_reads_every_item(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, {"items": [link(), link(resourceId=OTHER)]})
    items = service.list_services(API, token="t", allow_insecure_http=False)
    assert [item.resource_id for item in items] == [RID, OTHER]


@pytest.mark.parametrize("document", [{"resourceId": RID}, {}, []])
def test_an_admission_that_is_not_the_resource_is_a_contract_failure(
    monkeypatch: pytest.MonkeyPatch, document: object
) -> None:
    serve(monkeypatch, document, status=201)
    with pytest.raises(ApiUnavailableError):
        service.enable_service(
            API, token="t", service="ipm", idempotency_key="k", allow_insecure_http=False
        )
