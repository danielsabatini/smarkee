"""Cliente do `bsm.account` na API da plataforma (`docs/loop/RESOURCE-CONTROL-LOOP.md` §6).

Criar, alterar e remover são escritas síncronas na admissão (decisão 0098): a API devolve o recurso
(`201`, `200` e `202` na remoção). A Billing Account é dado do SSOT e nasce `Ready` e convergida.
Não há Operation. A leitura das respostas é estrita.
"""

import re
from dataclasses import dataclass
from typing import Any, cast

from sk.features.api_contract import as_object, as_text, validate_identifier
from sk.http import ApiUnavailableError, call_api

ACCOUNTS_PATH = "/v1/bsm/accounts"
# `displayName` de `schemas/bsm/account/definitions.v1.schema.json`: texto visível, sem controle.
DISPLAY_NAME_PATTERN = re.compile(r"^[^\u0000-\u001f\u007f]+$")
MAXIMUM_DISPLAY_NAME_LENGTH = 128
ALLOWED_CURRENCIES = ("BRL", "USD", "EUR")
MINIMUM_EMAIL_LENGTH = 3
MAXIMUM_EMAIL_LENGTH = 254
MAXIMUM_BILLING_CONTACTS = 10
LIST_PAGE_SIZE = 200  # o máximo da API
MAXIMUM_LIST_PAGES = 50  # trava contra um cursor que nunca termina


@dataclass(frozen=True, slots=True)
class BillingAccount:
    """Uma Billing Account, como a API a devolve ao dono (o `ownerAccountId` nunca é exposto)."""

    resource_id: str
    resource_version: str
    desired_generation: int
    observed_generation: int | None
    phase: str
    display_name: str
    billing_currency: str
    billing_contacts: tuple[str, ...]
    lifecycle: str
    deletion_protection: bool
    """`True` impede a exclusão (decisão 0043); a API a devolve sempre, e ausente vale `True`."""
    presence: str | None
    """Presença lida do provedor (`present`, `absent`, `unknown`); `None` antes da observação."""
    failure_reason: str | None = None


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


def validate_billing_currency(value: str) -> str:
    """Devolve a moeda se ela segue o contrato (`BRL`, `USD` ou `EUR`), ou levanta `ValueError`."""
    if value not in ALLOWED_CURRENCIES:
        raise ValueError(f"billingCurrency invalid: use one of {', '.join(ALLOWED_CURRENCIES)}")
    return value


def validate_billing_contacts(values: list[str]) -> list[str]:
    """Devolve os contatos de cobrança sem duplicatas se seguem o contrato, ou `ValueError`."""
    if not values:
        raise ValueError("billingContacts invalid: provide at least 1 contact e-mail")
    if len(values) > MAXIMUM_BILLING_CONTACTS:
        raise ValueError(
            f"billingContacts invalid: provide at most {MAXIMUM_BILLING_CONTACTS} contact e-mails"
        )
    if len(set(values)) != len(values):
        raise ValueError("billingContacts invalid: contact e-mails must not repeat")
    for contact in values:
        if not MINIMUM_EMAIL_LENGTH <= len(contact) <= MAXIMUM_EMAIL_LENGTH:
            raise ValueError("billingContacts invalid: e-mail size is outside the allowed range")
        local, separator, domain = contact.partition("@")
        if (
            not separator
            or not local
            or "." not in domain
            or domain.startswith(".")
            or " " in contact
        ):
            raise ValueError(
                "billingContacts invalid: contact does not have the format of an e-mail"
            )
    return list(values)


def _generation(body: dict[str, Any], key: str, *, required: bool) -> int | None:
    value = body.get(key)
    if isinstance(value, int) and not isinstance(value, bool):
        return value
    if required or value is not None:
        raise ApiUnavailableError(f"API response without {key}: billing account")
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


def _billing_account(document: object) -> BillingAccount:
    body = as_object(document, what="billing account")
    desired = as_object(body.get("desired"), what="billing account (desired)")
    observed = as_object(body.get("observed") or {}, what="billing account (observed)")
    contacts: Any = desired.get("billingContacts")
    if not isinstance(contacts, list) or not all(
        isinstance(item, str) for item in cast("list[object]", contacts)
    ):
        raise ApiUnavailableError("API response without billingContacts")
    presence = observed.get("presence")
    return BillingAccount(
        resource_id=as_text(body, "resourceId", what="billing account"),
        resource_version=as_text(body, "resourceVersion", what="billing account"),
        desired_generation=cast("int", _generation(body, "desiredGeneration", required=True)),
        observed_generation=_generation(body, "observedGeneration", required=False),
        phase=as_text(body, "phase", what="billing account"),
        display_name=as_text(desired, "displayName", what="billing account (desired)"),
        billing_currency=as_text(desired, "billingCurrency", what="billing account (desired)"),
        billing_contacts=tuple(cast("list[str]", contacts)),
        lifecycle=as_text(desired, "lifecycle", what="billing account (desired)"),
        deletion_protection=desired.get("deletionProtection") is not False,
        presence=presence if isinstance(presence, str) else None,
        failure_reason=_failure_reason(body),
    )


def create_account(
    api_url: str,
    *,
    token: str,
    display_name: str,
    billing_currency: str,
    billing_contacts: list[str],
    deletion_protection: bool | None = None,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> BillingAccount:
    validate_display_name(display_name)
    validate_billing_currency(billing_currency)
    contacts = validate_billing_contacts(billing_contacts)
    body: dict[str, Any] = {
        "displayName": display_name,
        "billingCurrency": billing_currency,
        "billingContacts": contacts,
    }
    if deletion_protection is not None:
        body["deletionProtection"] = deletion_protection
    _, document = call_api(
        "POST",
        api_url,
        ACCOUNTS_PATH,
        token=token,
        body=body,
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _billing_account(document)


def update_account(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    display_name: str | None = None,
    billing_contacts: list[str] | None = None,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> BillingAccount:
    resource_id = validate_identifier(resource_id, what="resourceId")
    body: dict[str, Any] = {"resourceVersion": resource_version}
    if display_name is not None:
        body["displayName"] = validate_display_name(display_name)
    if billing_contacts is not None:
        body["billingContacts"] = validate_billing_contacts(billing_contacts)
    _, document = call_api(
        "PATCH",
        api_url,
        f"{ACCOUNTS_PATH}/{resource_id}",
        token=token,
        body=body,
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _billing_account(document)


def set_account_protection(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    protected: bool,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> BillingAccount:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "PATCH",
        api_url,
        f"{ACCOUNTS_PATH}/{resource_id}",
        token=token,
        body={"resourceVersion": resource_version, "deletionProtection": protected},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _billing_account(document)


def delete_account(
    api_url: str,
    *,
    token: str,
    resource_id: str,
    resource_version: str,
    idempotency_key: str,
    allow_insecure_http: bool,
) -> BillingAccount:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "DELETE",
        api_url,
        f"{ACCOUNTS_PATH}/{resource_id}",
        token=token,
        query={"resourceVersion": resource_version},
        headers={"Idempotency-Key": idempotency_key},
        allow_insecure_http=allow_insecure_http,
    )
    return _billing_account(document)


def get_account(
    api_url: str, *, token: str, resource_id: str, allow_insecure_http: bool
) -> BillingAccount:
    resource_id = validate_identifier(resource_id, what="resourceId")
    _, document = call_api(
        "GET",
        api_url,
        f"{ACCOUNTS_PATH}/{resource_id}",
        token=token,
        allow_insecure_http=allow_insecure_http,
    )
    return _billing_account(document)


def list_accounts(
    api_url: str, *, token: str, allow_insecure_http: bool
) -> tuple[BillingAccount, ...]:
    accounts: list[BillingAccount] = []
    cursor: str | None = None
    for _ in range(MAXIMUM_LIST_PAGES):
        query = {"limit": str(LIST_PAGE_SIZE)}
        if cursor is not None:
            query["cursor"] = cursor
        _, document = call_api(
            "GET",
            api_url,
            ACCOUNTS_PATH,
            token=token,
            query=query,
            allow_insecure_http=allow_insecure_http,
        )
        body = as_object(document, what="billing accounts list")
        raw_items = body.get("items")
        if not isinstance(raw_items, list):
            raise ApiUnavailableError("API response without items in the billing accounts list")
        accounts.extend(_billing_account(item) for item in cast("list[object]", raw_items))
        next_cursor = body.get("nextCursor")
        if not isinstance(next_cursor, str) or not next_cursor:
            break
        cursor = next_cursor
    else:
        raise ApiUnavailableError("listing did not end within the allowed number of pages")
    return tuple(accounts)
