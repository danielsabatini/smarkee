"""Execução das operações da Billing Account no armazenamento de estado (`LOOP.md` §46).

Compõe os drivers de `executor/drivers/` e não chama o provedor direto. Cada operação é idempotente
e usa o `resourceId` como identificador da conta. `billingCurrency` é imutável após a criação.
"""

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol

from bsm_account.executor.domain.errors import ActionFailedError
from bsm_account.executor.domain.identity import StoredAccount

_CURRENCIES = frozenset({"BRL", "USD", "EUR"})


class Accounts(Protocol):
    """Driver da Billing Account (`executor/drivers/account.py`)."""

    async def get_account(self, account_id: str) -> StoredAccount | None: ...

    async def save_account(self, account_id: str, account: StoredAccount) -> None: ...

    async def delete_account(self, account_id: str) -> None: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de escrita que as operações da Billing Account usam."""

    accounts: Accounts


async def execute(
    operation: str,
    account_id: str,
    desired: Mapping[str, Any],
    drivers: Drivers,
) -> None:
    writer = drivers.accounts
    match operation:
        case "create":
            await _create(account_id, desired, writer)
        case "update":
            await _update(account_id, desired, writer)
        case "delete":
            await writer.delete_account(account_id)  # ausente é sucesso idempotente
        case _:
            raise ActionFailedError("Rejected", retryable=False, message="unsupported operation")


def _account_of(desired: Mapping[str, Any]) -> StoredAccount:
    display_name = str(desired.get("displayName", ""))
    if not display_name:
        raise ActionFailedError("Rejected", retryable=False, message="desired without displayName")
    billing_currency = str(desired.get("billingCurrency", ""))
    if billing_currency not in _CURRENCIES:
        raise ActionFailedError(
            "Rejected", retryable=False, message="desired with invalid billingCurrency"
        )
    raw_contacts = desired.get("billingContacts")
    if not isinstance(raw_contacts, list) or not raw_contacts:
        raise ActionFailedError(
            "Rejected", retryable=False, message="desired without billingContacts"
        )
    contacts = [str(item) for item in raw_contacts]  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType]
    protected = desired.get("deletionProtection", True) is not False
    return StoredAccount(
        display_name=display_name,
        billing_currency=billing_currency,
        billing_contacts=contacts,
        deletion_protection=protected,
    )


async def _create(account_id: str, desired: Mapping[str, Any], writer: Accounts) -> None:
    target = _account_of(desired)
    existing = await writer.get_account(account_id)
    if existing is not None and existing.billing_currency != target.billing_currency:
        raise ActionFailedError(
            "Rejected", retryable=False, message="billingCurrency cannot be changed"
        )
    await writer.save_account(account_id, target)


async def _update(account_id: str, desired: Mapping[str, Any], writer: Accounts) -> None:
    target = _account_of(desired)
    existing = await writer.get_account(account_id)
    if existing is None:
        raise ActionFailedError("Rejected", retryable=False, message="account does not exist")
    if existing.billing_currency != target.billing_currency:
        raise ActionFailedError(
            "Rejected", retryable=False, message="billingCurrency cannot be changed"
        )
    await writer.save_account(account_id, target)
