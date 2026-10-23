"""Resultado de uma observação: mapeia o estado persistido para `observed` de `bsm.account`."""

from dataclasses import dataclass
from typing import Any, Protocol

from bsm_account.observer.domain.identity import ProviderError, StoredAccount

_CURRENCIES = frozenset({"BRL", "USD", "EUR"})


class Accounts(Protocol):
    """Driver de leitura da Billing Account (`observer/drivers/account.py`)."""

    async def get_account(self, account_id: str) -> StoredAccount | None: ...


@dataclass(frozen=True, slots=True)
class Drivers:
    """Os drivers de leitura que a observação usa: espelho dos drivers de escrita do Executor."""

    accounts: Accounts


@dataclass(frozen=True, slots=True)
class Observation:
    presence: str
    """`present`, `absent` ou `unknown`."""

    data: dict[str, Any]


async def observe(drivers: Drivers, account_id: str) -> Observation:
    """Lê a Billing Account. Qualquer falha de leitura é `unknown`, nunca `absent`."""
    try:
        account = await drivers.accounts.get_account(account_id)
    except ProviderError:
        return Observation("unknown", {})
    if account is None:
        return Observation("absent", {})
    if (
        not account.display_name
        or account.billing_currency not in _CURRENCIES
        or not account.billing_contacts
    ):
        return Observation("unknown", {})
    data: dict[str, Any] = {
        "displayName": account.display_name,
        "billingCurrency": account.billing_currency,
        "billingContacts": list(account.billing_contacts),
    }
    if account.deletion_protection is not None:
        data["deletionProtection"] = account.deletion_protection
    return Observation("present", data)


def log_identifiers(resource_id: str) -> dict[str, str]:
    """Identificadores de negócio extras nos logs de cada observação (decisão 0061).

    Gancho que o motor do Observer (template, perfil `loop-engines`) chama. A Billing Account não é
    uma Organization: não há identificador extra além de `resource_id`.
    """
    _ = resource_id
    return {}
