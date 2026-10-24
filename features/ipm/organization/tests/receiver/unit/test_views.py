"""A visão `resource` do Receiver: só os campos do contrato da visão, campo a campo."""

from datetime import UTC, datetime

from ipm_organization.receiver.domain.records import ResourceRecord
from ipm_organization.receiver.domain.views import organization_view

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
USER_ACCESS = {
    "grantPermissions": ["ipm.user.get"],
    "userExecutorAccountId": "394397791373230101",
    "userObserverAccountId": "394397791373230102",
}


def test_the_user_access_is_not_shown() -> None:
    """Decisão 0081: os IDs das contas de serviço não vão para o cliente (`x-resourceView`)."""
    record = ResourceRecord(
        resource_id="org-1",
        resource_version=2,
        desired_generation=2,
        lifecycle="present",
        reconciliation="active",
        phase="Ready",
        conditions=[],
        desired={
            "lifecycle": "present",
            "name": "acme",
            "platformAccess": "granted",
            "deletionProtection": True,
            "userAccess": USER_ACCESS,
            "ownerAccountId": "owner-1",
        },
        presence="present",
        observed={
            "name": "acme",
            "platformAccess": "granted",
            "organizationState": "active",
            "deletionProtection": True,
            "userAccess": {
                "grantRoles": ["ipm.user.get"],
                "administrators": [{"accountId": "394397791373230101", "roles": ["X"]}],
            },
        },
        observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    view = organization_view(record).model_dump(mode="json", by_alias=True, exclude_none=True)
    assert "userAccess" not in view["desired"] and "userAccess" not in view["observed"]
    assert view["observed"]["organizationState"] == "active"
    assert "394397791373230101" not in str(view)


def test_the_billing_account_id_is_shown_in_desired_when_present() -> None:
    record = ResourceRecord(
        resource_id="org-1",
        resource_version=2,
        desired_generation=2,
        lifecycle="present",
        reconciliation="active",
        phase="Ready",
        conditions=[],
        desired={
            "lifecycle": "present",
            "name": "acme",
            "platformAccess": "granted",
            "deletionProtection": True,
            "billingAccountId": "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d99",
            "ownerAccountId": "owner-1",
        },
        presence="present",
        observed={"name": "acme", "platformAccess": "granted", "organizationState": "active"},
        observed_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )
    view = organization_view(record).model_dump(mode="json", by_alias=True, exclude_none=True)
    assert view["desired"]["billingAccountId"] == "0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d99"
