"""Mapeamento do arquivo local para `observed`: a leitura falha vira `unknown`, nunca `absent`."""

from pathlib import Path

from bsm_account.observer.domain.identity import ProviderError, StoredAccount
from bsm_account.observer.domain.observation import Drivers, log_identifiers, observe
from bsm_account.observer.drivers.account import AccountDriver
from bsm_account.observer.provider.storage import StateStoreConnection
from bsm_account.observer.settings import StorageSettings


class FakeReader:
    def __init__(self, account: StoredAccount | None, error: ProviderError | None = None) -> None:
        self._account = account
        self._error = error

    async def get_account(self, account_id: str) -> StoredAccount | None:
        if self._error:
            raise self._error
        return self._account


def drivers(reader: FakeReader) -> Drivers:
    return Drivers(accounts=reader)


def stored_account(
    *,
    display_name: str = "Produção Brasil",
    currency: str = "BRL",
    contacts: list[str] | None = None,
    protected: bool | None = True,
) -> StoredAccount:
    return StoredAccount(
        display_name=display_name,
        billing_currency=currency,
        billing_contacts=contacts if contacts is not None else ["finops@acme.example"],
        deletion_protection=protected,
    )


async def test_absent_account() -> None:
    result = await observe(drivers(FakeReader(None)), "ba-1")
    assert (result.presence, result.data) == ("absent", {})


async def test_a_present_account_returns_observed_fields() -> None:
    result = await observe(drivers(FakeReader(stored_account())), "ba-1")
    assert result.presence == "present"
    assert result.data == {
        "displayName": "Produção Brasil",
        "billingCurrency": "BRL",
        "billingContacts": ["finops@acme.example"],
        "deletionProtection": True,
    }


async def test_an_account_with_missing_or_invalid_fields_is_unknown() -> None:
    for invalid in (
        stored_account(display_name=""),
        stored_account(currency="JPY"),
        stored_account(contacts=[]),
    ):
        result = await observe(drivers(FakeReader(invalid)), "ba-1")
        assert (result.presence, result.data) == ("unknown", {})


async def test_read_failures_are_unknown() -> None:
    result = await observe(drivers(FakeReader(None, error=ProviderError("I/O error"))), "ba-1")
    assert (result.presence, result.data) == ("unknown", {})


async def test_missing_deletion_protection_is_left_out_as_a_divergence() -> None:
    result = await observe(drivers(FakeReader(stored_account(protected=None))), "ba-1")
    assert result.presence == "present"
    assert "deletionProtection" not in result.data


async def test_state_store_and_driver_read_json(tmp_path: Path) -> None:
    reader = AccountDriver(StateStoreConnection(StorageSettings(directory=str(tmp_path))))
    assert await reader.get_account("ba-1") is None

    (tmp_path / "ba-1.json").write_text(
        '{"displayName": "Conta 1", "billingCurrency": "USD", '
        '"billingContacts": ["a@b.co"], "deletionProtection": false}\n',
        encoding="utf-8",
    )
    loaded = await reader.get_account("ba-1")
    assert loaded == StoredAccount(
        display_name="Conta 1",
        billing_currency="USD",
        billing_contacts=["a@b.co"],
        deletion_protection=False,
    )

    (tmp_path / "ba-bad.json").write_text("not-json", encoding="utf-8")
    result = await observe(Drivers(accounts=reader), "ba-bad")
    assert (result.presence, result.data) == ("unknown", {})

    (tmp_path / "ba-list.json").write_text("[]", encoding="utf-8")
    result_list = await observe(Drivers(accounts=reader), "ba-list")
    assert (result_list.presence, result_list.data) == ("unknown", {})

    (tmp_path / "ba-missing.json").write_text('{"displayName": 123}', encoding="utf-8")
    result_missing = await observe(Drivers(accounts=reader), "ba-missing")
    assert (result_missing.presence, result_missing.data) == ("unknown", {})

    result_bad_id = await observe(Drivers(accounts=reader), "../escape")
    assert (result_bad_id.presence, result_bad_id.data) == ("unknown", {})


def test_log_identifiers_of_the_observation() -> None:
    assert log_identifiers("ba-1") == {}
