"""Regras do preparo para os usuários (`userAccess`, decisão 0081), compartilhadas pelo Manager e
pelo Reconciler."""

from typing import Any

from ipm_organization.common import user_access as access
from ipm_organization.common.contracts import generated

DESIRED = access.desired_user_access(
    user_executor_account_id="executor", user_observer_account_id="observer"
)


def observed(grant: list[str] | None, **held: list[str]) -> dict[str, Any]:
    result: dict[str, Any] = {
        "administrators": [{"accountId": a, "roles": r} for a, r in sorted(held.items())]
    }
    if grant is not None:
        result["grantRoles"] = grant
    return result


READY = observed(
    access.grant_catalog(),
    executor=["ORG_USER_CREATOR", "PROJECT_GRANT_OWNER"],
    observer=["ORG_OWNER_VIEWER"],
)


def test_the_catalog_is_the_contract_enum_sorted() -> None:
    """O catálogo não é configuração: é o `grantableRole` do contrato (decisão 0081)."""
    catalog = access.grant_catalog()
    assert catalog == sorted(role.value for role in generated.GrantableRole)
    assert "ipm.user.bind" in catalog
    assert not {"ipm.organization.create", "ipm.organization.delete", "ipm.user.admin"} & set(
        catalog
    )
    assert DESIRED["grantRoles"] == catalog


def test_a_prepared_organization_is_converged() -> None:
    assert access.converged(DESIRED, READY)
    extra = observed(
        list(reversed(access.grant_catalog())),
        executor=["ORG_USER_CREATOR", "PROJECT_GRANT_OWNER", "ORG_OWNER"],
        observer=["ORG_OWNER_VIEWER"],
        someone=["ORG_OWNER"],
    )
    assert access.converged(DESIRED, extra)  # papéis e contas a mais não são da plataforma


def test_a_missing_or_different_grant_is_not_converged() -> None:
    held = {
        "executor": ["ORG_USER_CREATOR", "PROJECT_GRANT_OWNER"],
        "observer": ["ORG_OWNER_VIEWER"],
    }
    assert not access.converged(DESIRED, observed(None, **held))
    assert not access.converged(DESIRED, observed(["ipm.user.get"], **held))
    assert not access.converged(DESIRED, observed([*access.grant_catalog(), "x.y.z"], **held))


def test_a_missing_role_of_a_user_account_is_not_converged() -> None:
    catalog = access.grant_catalog()
    assert not access.converged(
        DESIRED, observed(catalog, executor=["ORG_USER_CREATOR"], observer=["ORG_OWNER_VIEWER"])
    )
    assert not access.converged(
        DESIRED, observed(catalog, executor=["ORG_USER_CREATOR", "PROJECT_GRANT_OWNER"])
    )


def test_an_observation_without_user_access_is_not_converged() -> None:
    assert not access.converged(DESIRED, None)
    assert not access.converged(DESIRED, "broken")


def test_it_is_managed_only_with_user_access_and_platform_access() -> None:
    assert access.is_managed({"platformAccess": "granted", "userAccess": DESIRED})
    assert not access.is_managed({"platformAccess": "revoked", "userAccess": DESIRED})
    assert not access.is_managed({"platformAccess": "granted"})  # anterior à decisão 0081
