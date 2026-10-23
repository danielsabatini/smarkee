"""Driver de leitura e escrita da Billing Account no armazenamento de estado (decisão 0073)."""

from bsm_account.executor.domain.identity import ProviderError, StoredAccount
from bsm_account.executor.provider.storage import StateStoreConnection


class AccountDriver:
    def __init__(self, connection: StateStoreConnection) -> None:
        self._connection = connection

    async def get_account(self, account_id: str) -> StoredAccount | None:
        record = await self._connection.read_record(account_id)
        if record is None:
            return None
        display_name = record.get("displayName")
        billing_currency = record.get("billingCurrency")
        contacts = record.get("billingContacts")
        protection = record.get("deletionProtection")
        if (
            not isinstance(display_name, str)
            or not isinstance(billing_currency, str)
            or not isinstance(contacts, list)
            or not all(isinstance(item, str) for item in contacts)  # pyright: ignore[reportUnknownVariableType]
        ):
            raise ProviderError(
                "ExternalError",
                retryable=False,
                detail="stored account is missing required fields",
            )
        return StoredAccount(
            display_name=display_name,
            billing_currency=billing_currency,
            billing_contacts=[str(item) for item in contacts],  # pyright: ignore[reportUnknownVariableType,reportUnknownArgumentType]
            deletion_protection=protection if isinstance(protection, bool) else True,
        )

    async def save_account(self, account_id: str, account: StoredAccount) -> None:
        await self._connection.write_record(
            account_id,
            {
                "displayName": account.display_name,
                "billingCurrency": account.billing_currency,
                "billingContacts": list(account.billing_contacts),
                "deletionProtection": account.deletion_protection,
            },
        )

    async def delete_account(self, account_id: str) -> None:
        await self._connection.delete_record(account_id)
