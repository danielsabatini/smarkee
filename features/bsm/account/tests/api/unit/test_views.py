"""A visão `resource` do Receiver: só os campos do contrato da visão, campo a campo."""

from datetime import UTC, datetime

from bsm_account.api.domain.records import ResourceRecord
from bsm_account.api.domain.views import account_view

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)


def test_the_owner_account_id_is_not_shown_and_observed_is_filtered() -> None:
    record = ResourceRecord(
        resource_id="ba-1",
        resource_version=2,
        desired_generation=2,
        observed_generation=2,
        lifecycle="present",
        reconciliation="active",
        phase="Ready",
        conditions=[],
        desired={
            "lifecycle": "present",
            "displayName": "Produção Brasil",
            "billingCurrency": "BRL",
            "billingContacts": ["finops@acme.example"],
            "deletionProtection": True,
            "ownerAccountId": "owner-1",
            "extraInternalField": "hidden",
        },
        presence="present",
        observed={
            "displayName": "Produção Brasil",
            "billingCurrency": "BRL",
            "billingContacts": ["finops@acme.example"],
            "deletionProtection": True,
            "extraInternalField": "hidden",
        },
        observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    view = account_view(record).model_dump(mode="json", by_alias=True, exclude_none=True)
    assert "ownerAccountId" not in view["desired"]
    assert "extraInternalField" not in view["desired"]
    assert "extraInternalField" not in view["observed"]
    assert view["observed"]["billingCurrency"] == "BRL"
    assert "owner-1" not in str(view)
