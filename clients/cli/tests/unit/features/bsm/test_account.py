"""Cliente do `bsm.account` (`sk.features.bsm.account`): pedidos e respostas."""

import json
import urllib.request
from pathlib import Path
from typing import Any, cast

import pytest

from sk.features.bsm import account
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


def account_document(**changes: object) -> dict[str, Any]:
    document: dict[str, Any] = {
        "resourceId": RID,
        "resourceVersion": "3",
        "desiredGeneration": 1,
        "observedGeneration": 1,
        "phase": "Ready",
        "desired": {
            "lifecycle": "present",
            "reconciliation": "active",
            "displayName": "Acme Cloud Production",
            "billingCurrency": "BRL",
            "billingContacts": ["finops@acme.com"],
        },
        "observed": {
            "presence": "present",
            "displayName": "Acme Cloud Production",
            "billingCurrency": "BRL",
            "billingContacts": ["finops@acme.com"],
        },
    }
    document.update(changes)
    return document


def last(sent: Sent) -> urllib.request.Request:
    return sent.requests[-1]


def test_the_display_name_pattern_is_the_one_of_the_published_contract() -> None:
    schema = Path(__file__).parents[6] / "schemas" / "bsm" / "account"
    defs = json.loads((schema / "definitions.v1.schema.json").read_text(encoding="utf-8"))["$defs"]
    assert account.DISPLAY_NAME_PATTERN.pattern == defs["displayName"]["pattern"]
    assert defs["displayName"]["maxLength"] == account.MAXIMUM_DISPLAY_NAME_LENGTH
    assert list(account.ALLOWED_CURRENCIES) == defs["billingCurrency"]["enum"]


@pytest.mark.parametrize("value", ["a", "Acme Cloud Production", "a" * 128])
def test_a_display_name_that_follows_the_contract_is_accepted_as_it_is(value: str) -> None:
    assert account.validate_display_name(value) == value


@pytest.mark.parametrize("value", ["", "a" * 129, "a\nb", "a\x00b", "a\x7fb"])
def test_a_display_name_outside_the_contract_is_refused_without_being_repeated(
    value: str,
) -> None:
    with pytest.raises(ValueError, match="displayName invalid") as caught:
        account.validate_display_name(value)
    assert value.strip() == "" or value not in str(caught.value)


@pytest.mark.parametrize("value", ["BRL", "USD", "EUR"])
def test_a_currency_that_follows_the_contract_is_accepted(value: str) -> None:
    assert account.validate_billing_currency(value) == value


def test_a_currency_outside_the_contract_is_refused() -> None:
    with pytest.raises(ValueError, match="billingCurrency invalid"):
        account.validate_billing_currency("GBP")


def test_billing_contacts_that_follow_the_contract_are_accepted() -> None:
    contacts = ["finops@acme.com", "billing@acme.com"]
    assert account.validate_billing_contacts(contacts) == contacts


@pytest.mark.parametrize(
    "values",
    [
        [],
        [f"c{i}@acme.com" for i in range(11)],
        ["finops@acme.com", "finops@acme.com"],
        ["a@"],
        ["@acme.com"],
        ["finops@.com"],
        ["finops@acme"],
        ["finops @acme.com"],
        ["a" * 250 + "@acme.com"],
    ],
)
def test_billing_contacts_outside_the_contract_are_refused(values: list[str]) -> None:
    with pytest.raises(ValueError, match="billingContacts invalid"):
        account.validate_billing_contacts(values)


def test_create_posts_the_account_fields_with_the_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = serve(monkeypatch, account_document(), status=201)

    created = account.create_account(
        API,
        token="t",
        display_name="Acme Cloud Production",
        billing_currency="BRL",
        billing_contacts=["finops@acme.com"],
        deletion_protection=False,
        idempotency_key="k-1",
        allow_insecure_http=False,
    )

    assert created.resource_id == RID
    request = last(sent)
    assert (request.get_method(), request.full_url) == ("POST", f"{API}/v1/bsm/accounts")
    assert request.get_header("Idempotency-key") == "k-1"
    assert request.get_header("Authorization") == "Bearer t"
    assert json.loads(cast(bytes, request.data)) == {
        "displayName": "Acme Cloud Production",
        "billingCurrency": "BRL",
        "billingContacts": ["finops@acme.com"],
        "deletionProtection": False,
    }


def test_update_patches_the_fields_with_the_version(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = serve(monkeypatch, account_document(), status=200)

    account.update_account(
        API,
        token="t",
        resource_id=RID,
        resource_version="3",
        display_name="Novo Nome",
        billing_contacts=["novo@acme.com"],
        idempotency_key="k-2",
        allow_insecure_http=False,
    )

    request = last(sent)
    assert (request.get_method(), request.full_url) == (
        "PATCH",
        f"{API}/v1/bsm/accounts/{RID}",
    )
    assert json.loads(cast(bytes, request.data)) == {
        "resourceVersion": "3",
        "displayName": "Novo Nome",
        "billingContacts": ["novo@acme.com"],
    }


def test_delete_sends_the_version_in_the_query(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = serve(monkeypatch, account_document(phase="Deleting"), status=202)

    deleted = account.delete_account(
        API,
        token="t",
        resource_id=RID,
        resource_version="3",
        idempotency_key="k-3",
        allow_insecure_http=False,
    )

    assert deleted.phase == "Deleting"
    request = last(sent)
    assert request.get_method() == "DELETE"
    assert request.full_url == f"{API}/v1/bsm/accounts/{RID}?resourceVersion=3"
    assert request.data is None


def test_get_reads_the_fields_of_the_account(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, account_document())

    found = account.get_account(API, token="t", resource_id=RID, allow_insecure_http=False)

    assert found == account.BillingAccount(
        resource_id=RID,
        resource_version="3",
        desired_generation=1,
        observed_generation=1,
        phase="Ready",
        display_name="Acme Cloud Production",
        billing_currency="BRL",
        billing_contacts=("finops@acme.com",),
        lifecycle="present",
        deletion_protection=True,
        presence="present",
    )


def test_deletion_protection_is_read_as_sent_and_absent_means_protected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = account_document()
    document["desired"]["deletionProtection"] = False
    serve(monkeypatch, document)
    unprotected = account.get_account(API, token="t", resource_id=RID, allow_insecure_http=False)
    assert unprotected.deletion_protection is False


def test_set_protection_patches_the_flag_with_the_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = serve(monkeypatch, account_document(), status=200)

    account.set_account_protection(
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
    assert request.full_url == f"{API}/v1/bsm/accounts/{RID}"
    assert json.loads(cast(bytes, request.data)) == {
        "resourceVersion": "3",
        "deletionProtection": False,
    }


def test_a_not_yet_observed_account_has_no_presence(monkeypatch: pytest.MonkeyPatch) -> None:
    document = account_document(phase="Pending")
    del document["observed"]
    serve(monkeypatch, document)

    found = account.get_account(API, token="t", resource_id=RID, allow_insecure_http=False)

    assert found.presence is None


@pytest.mark.parametrize("field", ["resourceId", "resourceVersion", "phase", "desired"])
def test_an_answer_without_a_required_field_is_outside_the_contract(
    monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    document = account_document()
    del document[field]
    serve(monkeypatch, document)

    with pytest.raises(ApiUnavailableError):
        account.get_account(API, token="t", resource_id=RID, allow_insecure_http=False)


def test_an_answer_without_billing_contacts_is_outside_the_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    document = account_document()
    del document["desired"]["billingContacts"]
    serve(monkeypatch, document)

    with pytest.raises(ApiUnavailableError, match="billingContacts"):
        account.get_account(API, token="t", resource_id=RID, allow_insecure_http=False)


def test_the_list_follows_the_cursor_until_the_last_page(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = serve(
        monkeypatch,
        {"items": [account_document()], "nextCursor": "c-1"},
        {"items": [account_document(resourceId="outra")]},
    )

    found = account.list_accounts(API, token="t", allow_insecure_http=False)

    assert [item.resource_id for item in found] == [RID, "outra"]
    assert [request.full_url for request in sent.requests] == [
        f"{API}/v1/bsm/accounts?limit=200",
        f"{API}/v1/bsm/accounts?limit=200&cursor=c-1",
    ]


def test_a_listing_that_never_ends_is_refused(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, {"items": [], "nextCursor": "again"})

    with pytest.raises(ApiUnavailableError, match="did not end"):
        account.list_accounts(API, token="t", allow_insecure_http=False)


def test_a_listing_without_items_is_outside_the_contract(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, {"nope": []})

    with pytest.raises(ApiUnavailableError):
        account.list_accounts(API, token="t", allow_insecure_http=False)


def test_every_call_that_puts_an_identifier_in_the_path_refuses_a_bad_one(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = serve(monkeypatch, account_document())
    bad = "../../admin"
    calls = (
        lambda: account.get_account(API, token="t", resource_id=bad, allow_insecure_http=False),
        lambda: account.update_account(
            API,
            token="t",
            resource_id=bad,
            resource_version="1",
            display_name="x",
            idempotency_key="k",
            allow_insecure_http=False,
        ),
        lambda: account.delete_account(
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
    assert sent.requests == []
