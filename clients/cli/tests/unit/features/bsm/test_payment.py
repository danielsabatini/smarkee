"""Cliente do `bsm.payment` (`sk.features.bsm.payment`): pedidos e respostas."""

import json
import urllib.request
from pathlib import Path
from typing import Any, cast

import pytest

from sk.features.bsm import payment

API = "https://api.teste"
RID = "019c8a40-0000-7000-8000-000000000042"


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


def payment_document(**changes: object) -> dict[str, Any]:
    document: dict[str, Any] = {
        "resourceId": RID,
        "resourceVersion": "3",
        "desiredGeneration": 1,
        "observedGeneration": 1,
        "phase": "Ready",
        "desired": {
            "lifecycle": "present",
            "reconciliation": "active",
            "customerAccountId": "394397791373230085",
            "displayName": "Corporate Visa",
            "provider": "mercadopago",
            "methodType": "credit_card",
        },
        "observed": {
            "presence": "present",
            "provider": "mercadopago",
            "methodType": "credit_card",
            "status": "active",
            "brand": "visa",
            "lastFourDigits": "4242",
            "expirationMonth": 12,
            "expirationYear": 2030,
            "providerCustomerId": "mp_cust_394397791373230085",
            "providerPaymentMethodId": "mp_card_019c8a400000",
        },
    }
    document.update(changes)
    return document


def last(sent: Sent) -> urllib.request.Request:
    return sent.requests[-1]


def test_the_patterns_are_the_ones_of_the_published_contract() -> None:
    schema = Path(__file__).parents[6] / "schemas" / "bsm" / "payment"
    defs = json.loads((schema / "definitions.v1.schema.json").read_text(encoding="utf-8"))["$defs"]
    assert payment.DISPLAY_NAME_PATTERN.pattern == defs["displayName"]["pattern"]
    assert defs["displayName"]["maxLength"] == payment.MAXIMUM_DISPLAY_NAME_LENGTH
    assert list(payment.ALLOWED_PROVIDERS) == defs["paymentProvider"]["enum"]
    assert list(payment.ALLOWED_METHOD_TYPES) == defs["paymentMethodType"]["enum"]
    assert payment.PROVIDER_TOKEN_PATTERN.pattern == defs["providerToken"]["pattern"]
    assert defs["providerToken"]["maxLength"] == payment.MAXIMUM_PROVIDER_TOKEN_LENGTH


def test_validators_accept_valid_inputs_and_reject_invalid_ones() -> None:
    assert payment.validate_customer_account_id("394397791373230085") == "394397791373230085"
    assert payment.validate_display_name("Corporate Visa") == "Corporate Visa"
    assert payment.validate_provider("mercadopago") == "mercadopago"
    assert payment.validate_method_type("credit_card") == "credit_card"
    assert payment.validate_provider_token("mp_tok_visa_4242") == "mp_tok_visa_4242"

    with pytest.raises(ValueError, match="customerAccountId invalid"):
        payment.validate_customer_account_id("")
    with pytest.raises(ValueError, match="displayName invalid"):
        payment.validate_display_name("a\nb")
    with pytest.raises(ValueError, match="provider invalid"):
        payment.validate_provider("stripe")
    with pytest.raises(ValueError, match="methodType invalid"):
        payment.validate_method_type("wire_transfer")
    with pytest.raises(ValueError, match="providerToken invalid") as caught:
        payment.validate_provider_token("secret token with spaces")
    assert "secret token" not in str(caught.value)


def test_create_posts_the_payment_fields_with_the_idempotency_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    sent = serve(monkeypatch, payment_document(), status=201)

    created = payment.create_payment(
        API,
        token="t",
        customer_account_id="394397791373230085",
        display_name="Corporate Visa",
        provider="mercadopago",
        method_type="credit_card",
        provider_token="mp_tok_visa_4242",
        deletion_protection=False,
        idempotency_key="k-1",
        allow_insecure_http=False,
    )

    assert created.resource_id == RID
    request = last(sent)
    assert (request.get_method(), request.full_url) == ("POST", f"{API}/v1/bsm/payments")
    assert request.get_header("Idempotency-key") == "k-1"
    assert json.loads(cast(bytes, request.data)) == {
        "customerAccountId": "394397791373230085",
        "displayName": "Corporate Visa",
        "provider": "mercadopago",
        "methodType": "credit_card",
        "providerToken": "mp_tok_visa_4242",
        "deletionProtection": False,
    }


def test_update_patches_the_fields_with_the_version(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = serve(monkeypatch, payment_document(), status=200)

    payment.update_payment(
        API,
        token="t",
        resource_id=RID,
        resource_version="3",
        display_name="Mastercard Gold",
        provider_token="mp_tok_master_5454",
        idempotency_key="k-2",
        allow_insecure_http=False,
    )

    request = last(sent)
    assert (request.get_method(), request.full_url) == (
        "PATCH",
        f"{API}/v1/bsm/payments/{RID}",
    )
    assert json.loads(cast(bytes, request.data)) == {
        "resourceVersion": "3",
        "displayName": "Mastercard Gold",
        "providerToken": "mp_tok_master_5454",
    }


def test_delete_sends_the_version_in_the_query(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = serve(monkeypatch, payment_document(phase="Deleting"), status=202)

    deleted = payment.delete_payment(
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
    assert request.full_url == f"{API}/v1/bsm/payments/{RID}?resourceVersion=3"


def test_get_reads_the_fields_of_the_payment(monkeypatch: pytest.MonkeyPatch) -> None:
    serve(monkeypatch, payment_document())

    found = payment.get_payment(API, token="t", resource_id=RID, allow_insecure_http=False)

    assert found == payment.Payment(
        resource_id=RID,
        resource_version="3",
        desired_generation=1,
        observed_generation=1,
        phase="Ready",
        customer_account_id="394397791373230085",
        display_name="Corporate Visa",
        provider="mercadopago",
        method_type="credit_card",
        lifecycle="present",
        deletion_protection=True,
        presence="present",
        status="active",
        brand="visa",
        last_four_digits="4242",
        expiration_month=12,
        expiration_year=2030,
        provider_customer_id="mp_cust_394397791373230085",
        provider_payment_method_id="mp_card_019c8a400000",
    )


def test_list_follows_the_cursor_until_the_last_page(monkeypatch: pytest.MonkeyPatch) -> None:
    sent = serve(
        monkeypatch,
        {"items": [payment_document()], "nextCursor": "c-1"},
        {"items": [payment_document(resourceId="outra")]},
    )

    found = payment.list_payments(API, token="t", allow_insecure_http=False)

    assert [item.resource_id for item in found] == [RID, "outra"]
    assert [request.full_url for request in sent.requests] == [
        f"{API}/v1/bsm/payments?limit=200",
        f"{API}/v1/bsm/payments?limit=200&cursor=c-1",
    ]
