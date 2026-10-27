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
        "desiredGeneration": 1,
        "observedGeneration": 1,
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
    sent = serve(monkeypatch, organization_document(), status=201)

    created = organization.create_organization(
        API, token="t", name="acme", idempotency_key="k-1", allow_insecure_http=False
    )

    assert (created.resource_id, created.name, created.phase) == (RID, "acme", "Ready")
    request = last(sent)
    assert (request.get_method(), request.full_url) == ("POST", f"{API}/v1/ipm/organizations")
    assert request.get_header("Idempotency-key") == "k-1"
    assert request.get_header("Authorization") == "Bearer t"
    assert json.loads(cast(bytes, request.data)) == {"name": "acme"}


def test_update_patches_the_name_with_the_version(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = serve(monkeypatch, organization_document(name="novo"), status=200)

    updated = organization.update_organization(
        API,
        token="t",
        resource_id=RID,
        resource_version="3",
        name="novo",
        idempotency_key="k-2",
        allow_insecure_http=False,
    )

    assert updated.resource_id == RID
    request = last(sent)
    assert (request.get_method(), request.full_url) == (
        "PATCH",
        f"{API}/v1/ipm/organizations/{RID}",
    )
    assert json.loads(cast(bytes, request.data)) == {"resourceVersion": "3", "name": "novo"}


def test_delete_sends_the_version_in_the_query(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = serve(
        monkeypatch,
        organization_document(
            phase="Deleting",
            desired={"lifecycle": "absent", "name": "acme", "platformAccess": "granted"},
        ),
        status=202,
    )

    deleted = organization.delete_organization(
        API,
        token="t",
        resource_id=RID,
        resource_version="3",
        idempotency_key="k-3",
        allow_insecure_http=False,
    )

    assert (deleted.resource_id, deleted.phase) == (RID, "Deleting")
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
        desired_generation=1,
        observed_generation=1,
        phase="Ready",
        name="acme",
        lifecycle="present",
        platform_access="granted",
        deletion_protection=True,  # o documento sem o campo conta como protegido
        organization_state="active",
    )


def test_deletion_protection_is_read_as_sent_and_absent_means_protected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = organization_document()
    document["desired"]["deletionProtection"] = False
    serve(monkeypatch, document)
    unprotected = organization.get_organization(
        API, token="t", resource_id=RID, allow_insecure_http=False
    )
    assert unprotected.deletion_protection is False


def test_set_protection_patches_the_flag_with_the_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = serve(monkeypatch, organization_document(), status=200)

    organization.set_organization_protection(
        API,
        token="t",
        resource_id=RID,
        resource_version="3",
        protected=False,
        idempotency_key="k-1",
        allow_insecure_http=False,
    )

    request = last(sent)
    assert request.get_method() == "PATCH"
    assert request.full_url == f"{API}/v1/ipm/organizations/{RID}"
    assert json.loads(cast(bytes, request.data)) == {
        "resourceVersion": "3",
        "deletionProtection": False,
    }


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
    )
    for call in calls:
        with pytest.raises(ValueError):
            call()
    assert sent.requests == []  # nenhum pedido saiu


def test_create_and_update_send_billing_account_id_when_given(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = serve(monkeypatch, organization_document(), status=201)
    ba_id = "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d99"

    organization.create_organization(
        API,
        token="t",
        name="acme",
        billing_account_id=ba_id,
        idempotency_key="k-1",
        allow_insecure_http=False,
    )
    assert json.loads(cast(bytes, last(sent).data)) == {
        "name": "acme",
        "billingAccountId": ba_id,
    }

    organization.update_organization(
        API,
        token="t",
        resource_id=RID,
        resource_version="3",
        billing_account_id=ba_id,
        idempotency_key="k-2",
        allow_insecure_http=False,
    )
    assert json.loads(cast(bytes, last(sent).data)) == {
        "resourceVersion": "3",
        "billingAccountId": ba_id,
    }
