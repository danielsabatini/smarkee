"""Ações do Executor: Billing Account local, idempotência e escrita atômica."""

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from bsm_account.executor.actions.account_actions import Drivers, execute
from bsm_account.executor.domain.errors import ActionFailedError
from bsm_account.executor.domain.identity import ProviderError, StoredAccount
from bsm_account.executor.drivers.account import AccountDriver
from bsm_account.executor.provider.storage import StateStoreConnection
from bsm_account.executor.settings import StorageSettings

DESIRED: dict[str, Any] = {
    "lifecycle": "present",
    "displayName": "Produção Brasil",
    "billingCurrency": "BRL",
    "billingContacts": ["finops@acme.example"],
    "deletionProtection": True,
}


@dataclass
class FakeAccountDriver:
    accounts: dict[str, StoredAccount] = field(default_factory=lambda: {})
    calls: list[tuple[Any, ...]] = field(default_factory=lambda: [])
    fail_on: str | None = None

    def _maybe_fail(self, name: str) -> None:
        if self.fail_on == name:
            raise ProviderError("ProviderUnavailable", retryable=True)

    async def get_account(self, account_id: str) -> StoredAccount | None:
        self._maybe_fail("get_account")
        return self.accounts.get(account_id)

    async def save_account(self, account_id: str, account: StoredAccount) -> None:
        self._maybe_fail("save_account")
        self.calls.append(("save_account", account_id, account))
        self.accounts[account_id] = account

    async def delete_account(self, account_id: str) -> None:
        self._maybe_fail("delete_account")
        self.calls.append(("delete_account", account_id))
        self.accounts.pop(account_id, None)


def drivers(writer: FakeAccountDriver) -> Drivers:
    return Drivers(accounts=writer)


async def test_create_saves_the_account() -> None:
    writer = FakeAccountDriver()

    await execute("create", "ba-1", DESIRED, drivers(writer))

    expected = StoredAccount(
        display_name="Produção Brasil",
        billing_currency="BRL",
        billing_contacts=["finops@acme.example"],
        deletion_protection=True,
    )
    assert writer.calls == [("save_account", "ba-1", expected)]
    assert writer.accounts["ba-1"] == expected


async def test_create_and_update_reject_currency_change() -> None:
    existing = StoredAccount(
        display_name="Produção Brasil",
        billing_currency="BRL",
        billing_contacts=["finops@acme.example"],
        deletion_protection=True,
    )
    writer = FakeAccountDriver(accounts={"ba-1": existing})

    for operation in ("create", "update"):
        with pytest.raises(ActionFailedError) as raised:
            await execute(operation, "ba-1", {**DESIRED, "billingCurrency": "USD"}, drivers(writer))
        assert (raised.value.reason, raised.value.retryable) == ("Rejected", False)


async def test_update_saves_when_account_exists() -> None:
    existing = StoredAccount(
        display_name="Antigo",
        billing_currency="BRL",
        billing_contacts=["finops@acme.example"],
        deletion_protection=True,
    )
    writer = FakeAccountDriver(accounts={"ba-1": existing})

    await execute("update", "ba-1", {**DESIRED, "displayName": "Novo"}, drivers(writer))
    assert len(writer.calls) == 1
    assert writer.accounts["ba-1"].display_name == "Novo"


async def test_update_of_a_missing_account_is_a_permanent_failure() -> None:
    with pytest.raises(ActionFailedError) as raised:
        await execute("update", "ba-1", DESIRED, drivers(FakeAccountDriver()))
    assert raised.value.reason == "Rejected" and not raised.value.retryable


@pytest.mark.parametrize(
    "invalid_desired",
    [
        {"lifecycle": "present"},
        {**DESIRED, "displayName": ""},
        {**DESIRED, "billingCurrency": "JPY"},
        {**DESIRED, "billingContacts": []},
    ],
)
async def test_create_with_invalid_desired_is_rejected(invalid_desired: dict[str, Any]) -> None:
    writer = FakeAccountDriver()
    with pytest.raises(ActionFailedError) as raised:
        await execute("create", "ba-1", invalid_desired, drivers(writer))
    assert (raised.value.reason, raised.value.retryable) == ("Rejected", False)
    assert writer.calls == []


async def test_delete_removes_the_account_and_missing_is_success() -> None:
    existing = StoredAccount(
        display_name="Produção Brasil",
        billing_currency="BRL",
        billing_contacts=["finops@acme.example"],
        deletion_protection=False,
    )
    writer = FakeAccountDriver(accounts={"ba-1": existing})

    await execute("delete", "ba-1", {"lifecycle": "absent"}, drivers(writer))
    await execute("delete", "ba-1", {"lifecycle": "absent"}, drivers(writer))

    assert writer.accounts == {}
    assert [call[0] for call in writer.calls] == ["delete_account"] * 2


async def test_an_unsupported_operation_is_rejected() -> None:
    with pytest.raises(ActionFailedError):
        await execute("reconcile", "ba-1", DESIRED, drivers(FakeAccountDriver()))


async def test_provider_failures_propagate_to_the_engine() -> None:
    with pytest.raises(ProviderError):
        await execute("create", "ba-1", DESIRED, drivers(FakeAccountDriver(fail_on="save_account")))


async def test_state_store_and_driver_persist_atomically(tmp_path: Path) -> None:
    nested = tmp_path / "nested"
    writer = AccountDriver(StateStoreConnection(StorageSettings(directory=str(nested))))
    account = StoredAccount(
        display_name="Conta 1",
        billing_currency="BRL",
        billing_contacts=["a@b.co"],
        deletion_protection=True,
    )
    await writer.save_account("ba-1", account)
    assert await writer.get_account("ba-1") == account

    await writer.delete_account("ba-1")
    assert await writer.get_account("ba-1") is None
    await writer.delete_account("ba-1")

    with pytest.raises(ProviderError) as raised:
        await writer.save_account("../escape", account)
    assert not raised.value.retryable
