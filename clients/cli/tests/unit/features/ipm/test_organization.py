"""Cliente do `ipm.organization` (`sk.features.ipm.organization`): pedidos e respostas."""

import json
import urllib.request
from pathlib import Path
from typing import Any, cast

import pytest

from sk.features.ipm import organization
from sk.http import ApiUnavailableError

API = "https://api.teste"
RID = "01a14168-b59d-7475-8db7-c5cf57fa100b"
OPID = "b9c4c98c-7392-5016-a724-6e1cd0c1bed9"


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
    """Substitui `urlopen`: devolve as respostas combinadas, em sequência, e guarda os pedidos."""

    def __init__(self, *responses: Response) -> None:
        self.responses = list(responses)
        self.requests: list[urllib.request.Request] = []

    def __call__(self, request: urllib.request.Request, timeout: float = 0) -> Response:
        self.requests.append(request)
        return self.responses.pop(0) if len(self.responses) > 1 else self.responses[0]


def serve(monkeypatch: pytest.MonkeyPatch, *documents: object, status: int = 200) -> Sent:
    sent = Sent(*(Response(document, status) for document in documents))
    monkeypatch.setattr(urllib.request, "urlopen", sent)
    return sent


def organization_document(**changes: object) -> dict[str, Any]:
    document: dict[str, Any] = {
        "resourceId": RID,
        "resourceVersion": "3",
        "phase": "Ready",
        "desired": {
            "lifecycle": "present",
            "reconciliation": "active",
            "name": "acme",
            "platformAccess": "granted",
        },
        "observed": {"presence": "present", "name": "acme", "organizationState": "active"},
    }
    document.update(changes)
    return document


def last(sent: Sent) -> urllib.request.Request:
    return sent.requests[-1]


def test_the_name_pattern_is_the_one_of_the_published_contract() -> None:
    schema = Path(__file__).parents[6] / "schemas" / "ipm" / "organization"
    defs = json.loads((schema / "definitions.v1.schema.json").read_text(encoding="utf-8"))["$defs"]
    assert organization.ORGANIZATION_NAME_PATTERN.pattern == defs["organizationName"]["pattern"]


@pytest.mark.parametrize("value", ["a", "acme", "acme-1", "1a", "a" * 63])
def test_a_name_that_follows_the_contract_is_accepted_as_it_is(value: str) -> None:
    assert organization.validate_name(value) == value


@pytest.mark.parametrize("value", ["", "A", "-a", "a-", "a" * 64, "a b", "a_b", "a.b", "ç", "a\n"])
def test_a_name_outside_the_contract_is_refused_without_being_repeated(value: str) -> None:
    with pytest.raises(ValueError, match="name invalid") as caught:
        organization.validate_name(value)
    assert value.strip() == "" or value not in str(caught.value)


def test_create_posts_the_name_with_the_idempotency_key(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = serve(monkeypatch, {"resourceId": RID, "operationId": OPID}, status=202)

    accepted = organization.create_organization(
        API, token="t", name="acme", idempotency_key="k-1", allow_insecure_http=False
    )

    assert (accepted.resource_id, accepted.operation_id) == (RID, OPID)
    request = last(sent)
    assert (request.get_method(), request.full_url) == ("POST", f"{API}/v1/ipm/organizations")
    assert request.get_header("Idempotency-key") == "k-1"
    assert request.get_header("Authorization") == "Bearer t"
    assert json.loads(cast(bytes, request.data)) == {"name": "acme"}


def test_update_patches_the_name_with_the_version(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = serve(monkeypatch, {"resourceId": RID, "operationId": OPID}, status=202)

    organization.update_organization(
        API,
        token="t",
        resource_id=RID,
        resource_version="3",
        name="novo",
        idempotency_key="k-2",
        allow_insecure_http=False,
    )

    request = last(sent)
    assert (request.get_method(), request.full_url) == (
        "PATCH",
        f"{API}/v1/ipm/organizations/{RID}",
    )
    assert json.loads(cast(bytes, request.data)) == {"resourceVersion": "3", "name": "novo"}


def test_delete_sends_the_version_in_the_query(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = serve(monkeypatch, {"resourceId": RID, "operationId": OPID}, status=202)

    organization.delete_organization(
        API,
        token="t",
        resource_id=RID,
        resource_version="3",
        idempotency_key="k-3",
        allow_insecure_http=False,
    )

    request = last(sent)
    assert request.get_method() == "DELETE"
    assert request.full_url == f"{API}/v1/ipm/organizations/{RID}?resourceVersion=3"
    assert request.data is None


def test_get_reads_the_fields_of_the_organization(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, organization_document())

    found = organization.get_organization(
        API, token="t", resource_id=RID, allow_insecure_http=False
    )

    assert found == organization.Organization(
        resource_id=RID,
        resource_version="3",
        phase="Ready",
        name="acme",
        lifecycle="present",
        platform_access="granted",
        organization_state="active",
    )


def test_a_not_yet_observed_organization_has_no_state(monkeypatch: pytest.MonkeyPatch) -> None:
    document = organization_document(phase="Pending")
    del document["observed"]
    serve(monkeypatch, document)

    found = organization.get_organization(
        API, token="t", resource_id=RID, allow_insecure_http=False
    )

    assert found.organization_state is None


@pytest.mark.parametrize("field", ["resourceId", "resourceVersion", "phase", "desired"])
def test_an_answer_without_a_required_field_is_outside_the_contract(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    document = organization_document()
    del document[field]
    serve(monkeypatch, document)

    with pytest.raises(ApiUnavailableError):
        organization.get_organization(API, token="t", resource_id=RID, allow_insecure_http=False)


def test_the_list_follows_the_cursor_until_the_last_page(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = serve(
        monkeypatch,
        {"items": [organization_document()], "nextCursor": "c-1"},
        {"items": [organization_document(resourceId="outra")]},
    )

    found = organization.list_organizations(API, token="t", allow_insecure_http=False)

    assert [item.resource_id for item in found] == [RID, "outra"]
    assert [request.full_url for request in sent.requests] == [
        f"{API}/v1/ipm/organizations?limit=200",
        f"{API}/v1/ipm/organizations?limit=200&cursor=c-1",
    ]


def test_a_listing_that_never_ends_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, {"items": [], "nextCursor": "again"})

    with pytest.raises(ApiUnavailableError, match="did not end"):
        organization.list_organizations(API, token="t", allow_insecure_http=False)


def test_a_listing_without_items_is_outside_the_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, {"nope": []})

    with pytest.raises(ApiUnavailableError):
        organization.list_organizations(API, token="t", allow_insecure_http=False)


def test_every_call_that_puts_an_identifier_in_the_path_refuses_a_bad_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = serve(monkeypatch, organization_document())
    bad = "../../admin"
    calls = (
        lambda: organization.get_organization(
            API, token="t", resource_id=bad, allow_insecure_http=False
        ),
        lambda: organization.update_organization(
            API,
            token="t",
            resource_id=bad,
            resource_version="1",
            name="x",
            idempotency_key="k",
            allow_insecure_http=False,
        ),
        lambda: organization.delete_organization(
            API,
            token="t",
            resource_id=bad,
            resource_version="1",
            idempotency_key="k",
            allow_insecure_http=False,
        ),
        lambda: organization.get_operation(
            API, token="t", resource_id=RID, operation_id=bad, allow_insecure_http=False
        ),
    )
    for call in calls:
        with pytest.raises(ValueError):
            call()
    assert sent.requests == []  # nenhum pedido saiu


def test_the_operation_has_a_reason_only_when_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(
        monkeypatch,
        {"operationId": OPID, "operationStatus": "rejected", "operationStatusReason": "validation"},
        {"operationId": OPID, "operationStatus": "completed"},
    )

    refused = organization.get_operation(
        API, token="t", resource_id=RID, operation_id=OPID, allow_insecure_http=False
    )
    done = organization.get_operation(
        API, token="t", resource_id=RID, operation_id=OPID, allow_insecure_http=False
    )

    assert (refused.operation_status, refused.reason) == ("rejected", "validation")
    assert (done.operation_status, done.reason) == ("completed", None)
