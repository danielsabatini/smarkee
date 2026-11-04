"""Cliente do `bsm.payment` na API da plataforma (`docs/loop/RESOURCE-CONTROL-LOOP.md` §6).

Criar, alterar e remover são escritas síncronas na admissão (decisão 0098): a API devolve o recurso
(`201`, `200` e `202` na remoção). A convergência com o provedor externo (ex.: Mercado Pago) é
assíncrona (`external-reconciled`): com `--wait`, a CLI aguarda `observedGeneration` alcançar
`desiredGeneration` e `phase == "Ready"`. O `providerToken` (nonce de tokenização) é enviado apenas
na escrita e nunca é retornado pela API.
"""

import re
from dataclasses import dataclass
from typing import Any, cast

from sk.features.api_contract import as_object, as_text, validate_identifier
from sk.http import ApiUnavailableError, call_api

PAYMENTS_PATH = "/v1/bsm/payments"
DISPLAY_NAME_PATTERN = re.compile(r"^[^\r\n\t]+$")
MAXIMUM_DISPLAY_NAME_LENGTH = 120
CUSTOMER_ACCOUNT_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:@-]+$")
MAXIMUM_CUSTOMER_ACCOUNT_ID_LENGTH = 256
ALLOWED_PROVIDERS = ("mercadopago",)
ALLOWED_METHOD_TYPES = ("credit_card", "debit_card", "pix", "boleto")
PROVIDER_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")
MINIMUM_PROVIDER_TOKEN_LENGTH = 4
MAXIMUM_PROVIDER_TOKEN_LENGTH = 256
LIST_PAGE_SIZE = 200
MAXIMUM_LIST_PAGES = 50


@dataclass(frozen=True, slots=True)
class Payment:
    """Um método de pagamento (`bsm.payment`), como a API o devolve ao dono."""

    resource_id: str
    resource_version: str
    desired_generation: int
    observed_generation: int | None
    phase: str
    customer_account_id: str
    display_name: str
    provider: str
    method_type: str
    lifecycle: str
    deletion_protection: bool
    presence: str | None
    status: str | None = None
    brand: str | None = None
    last_four_digits: str | None = None
    expiration_month: int | None = None
    expiration_year: int | None = None
    provider_customer_id: str | None = None
    provider_payment_method_id: str | None = None
    failure_reason: str | None = None


def validate_customer_account_id(value: str) -> str:
    """Devolve o `customerAccountId` se segue o contrato (`actorId`), ou levanta `ValueError`."""
    if (
        not value
        or len(value) > MAXIMUM_CUSTOMER_ACCOUNT_ID_LENGTH
        or not CUSTOMER_ACCOUNT_ID_PATTERN.fullmatch(value)
    ):
        raise ValueError(
            "customerAccountId invalid: use 1 to 256 characters (letters, digits, ., _, :, @ or -)"
        )
    return value


def validate_display_name(value: str) -> str:
    """Devolve o nome se ele segue o contrato, ou levanta `ValueError` (sem repetir o valor)."""
    if (
        not value
        or len(value) > MAXIMUM_DISPLAY_NAME_LENGTH
        or not DISPLAY_NAME_PATTERN.fullmatch(value)
    ):
        raise ValueError(
            "displayName invalid: use 1 to 128 visible characters (without control characters)"
        )
    return value


def validate_provider(value: str) -> str:
    """Devolve o provedor de pagamento se segue o contrato (`mercadopago`), ou `ValueError`."""
    if value not in ALLOWED_PROVIDERS:
        raise ValueError(f"provider invalid: use one of {', '.join(ALLOWED_PROVIDERS)}")
    return value


def validate_method_type(value: str) -> str:
    """Devolve a modalidade se segue o contrato (`credit_card`), ou `ValueError`."""
    if value not in ALLOWED_METHOD_TYPES:
        raise ValueError(f"methodType invalid: use one of {', '.join(ALLOWED_METHOD_TYPES)}")
    return value


def validate_provider_token(value: str) -> str:
    """Devolve o `providerToken` se segue o contrato, ou levanta `ValueError`."""
    if not (
        MINIMUM_PROVIDER_TOKEN_LENGTH <= len(value) <= MAXIMUM_PROVIDER_TOKEN_LENGTH
    ) or not PROVIDER_TOKEN_PATTERN.fullmatch(value):
        raise ValueError(
            "providerToken invalid: use 4 to 256 characters (letters, digits, ., _ or -)"
        )
    return value


def _generation(body: dict[str, Any], key: str, *, required: bool) -> int | None:
    value = body.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if required or value is not None:
        raise ApiUnavailableError(f"API response without {key}: payment")
    return None


def _failure_reason(body: dict[str, Any]) -> str | None:
    conditions = body.get("conditions")
    if not isinstance(conditions, list):
        return None
    for item in cast("list[object]", conditions):
        if isinstance(item, dict):
            condition = cast("dict[str, object]", item)
            reason = condition.get("reason")
            if condition.get("status") == "False" and isinstance(reason, str):
                return reason
    return None


def _optional_str(mapping: dict[str, Any], key: str) -> str | None:
    val = mapping.get(key)
    return val if isinstance(val, str) else None


def _optional_int(mapping: dict[str, Any], key: str) -> int | None:
    val = mapping.get(key)
    return val if isinstance(val, int) and not isinstance(val, bool) else None


def _payment(document: object) -> Payment:
    body = as_object(document, what="payment")
    desired = as_object(body.get("desired"), what="payment (desired)")
    observed = as_object(body.get("observed") or {}, what="payment (observed)")
    return Payment(
        resource_id=as_text(body, "resourceId", what="payment"),
        resource_version=as_text(body, "resourceVersion", what="payment"),
        desired_generation=cast("int", _generation(body, "desiredGeneration", required=True)),
        observed_generation=_generation(body, "observedGeneration", required=False),
        phase=as_text(body, "phase", what="payment"),
        customer_account_id=as_text(desired, "customerAccountId", what="payment (desired)"),
        display_name=as_text(desired, "displayName", what="payment (desired)"),
        provider=as_text(desired, "provider", what="payment (desired)"),
        method_type=as_text(desired, "methodType", what="payment (desired)"),
        lifecycle=as_text(desired, "lifecycle", what="payment (desired)"),
        deletion_protection=desired.get("deletionProtection") is not False,
        presence=_optional_str(observed, "presence"),
        status=_optional_str(observed, "status"),
        brand=_optional_str(observed, "brand"),
        last_four_digits=_optional_str(observed, "lastFourDigits"),
        expiration_month=_optional_int(observed, "expirationMonth"),
        expiration_year=_optional_int(observed, "expirationYear"),
        provider_customer_id=_optional_str(observed, "providerCustomerId"),
        provider_payment_method_id=_optional_str(observed, "providerPaymentMethodId"),
        failure_reason=_failure_reason(body),
    )


def create_payment(
    api_url: str,
    *,
    token: str,
    customer_account_id: str,
    display_name: str,
    provider: str = "mercadopago",
    method_type: str = "credit_card",
    provider_token: str,
    deletion_protection: bool | None = None,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> Payment:
    validate_customer_account_id(customer_account_id)
    validate_display_name(display_name)
    validate_provider(provider)
    validate_method_type(method_type)
    validate_provider_token(provider_token)
    body: dict[str, Any] = {
        "customerAccountId": customer_account_id,
        "displayName": display_name,
        "provider": provider,
        "methodType": method_type,
        "providerToken": provider_token,
    }
    if deletion_protection is not None:
        body["deletionProtection"] = deletion_protection
    _, document = call_api(
        "POST",
        api_url,
        PAYMENTS_PATH,
        token=token,
        body=body,
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _payment(document)


def update_payment(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    display_name: str | None = None,
    provider_token: str | None = None,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> Payment:
    resource_id = validate_identifier(resource_id, what="resourceId")
    body: dict[str, Any] = {"resourceVersion": resource_version}
    if display_name is not None:
        body["displayName"] = validate_display_name(display_name)
    if provider_token is not None:
        body["providerToken"] = validate_provider_token(provider_token)
    _, document = call_api(
        "PATCH",
        api_url,
        f"{PAYMENTS_PATH}/{resource_id}",
        token=token,
        body=body,
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _payment(document)


def set_payment_protection(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    protected: bool,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> Payment:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "PATCH",
        api_url,
        f"{PAYMENTS_PATH}/{resource_id}",
        token=token,
        body={"resourceVersion": resource_version, "deletionProtection": protected},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _payment(document)


def delete_payment(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> Payment:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "DELETE",
        api_url,
        f"{PAYMENTS_PATH}/{resource_id}",
        token=token,
        query={"resourceVersion": resource_version},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _payment(document)


def get_payment(
    api_url: str, *, token: str, resource_id: str, allow_insecure_http: bool
) -> Payment:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "GET",
        api_url,
        f"{PAYMENTS_PATH}/{resource_id}",
        token=token,
        allow_insecure_http=allow_insecure_http,
    )
    return _payment(document)


def list_payments(api_url: str, *, token: str, allow_insecure_http: bool) -> tuple[Payment, ...]:
    payments: list[Payment] = []
    cursor: str | None = None
    for _ in range(MAXIMUM_LIST_PAGES):
        query = {"limit": str(LIST_PAGE_SIZE)}
        if cursor is not None:
            query["cursor"] = cursor
        _, document = call_api(
            "GET",
            api_url,
            PAYMENTS_PATH,
            token=token,
            query=query,
            allow_insecure_http=allow_insecure_http,
        )
        body = as_object(document, what="payments list")
        raw_items = body.get("items")
        if not isinstance(raw_items, list):
            raise ApiUnavailableError("API response without items in the payments list")
        payments.extend(_payment(item) for item in cast("list[object]", raw_items))
        next_cursor = body.get("nextCursor")
        if not isinstance(next_cursor, str) or not next_cursor:
            break
        cursor = next_cursor
    else:
        raise ApiUnavailableError("listing did not end within the allowed number of pages")
    return tuple(payments)
