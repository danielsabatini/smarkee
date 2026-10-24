"""Permissões que o cadastro concede (decisões 0025, 0032, 0033 e 0082)."""

from core_account.manager.domain.account import DEFAULT_PLATFORM_PERMISSIONS, AccountPolicy

ACCOUNT_LEVEL_PERMISSIONS = {
    "bsm.account.create",
    "bsm.account.delete",
    "bsm.account.get",
    "bsm.account.list",
    "bsm.account.update",
    "core.account.delete",
    "core.account.get",
}
SUM_BASE_PERMISSIONS = {
    "sum.ipm.disable",
    "sum.ipm.enable",
    "sum.ipm.get",
}


def test_the_default_permissions_are_the_account_level_ones_plus_the_sum_base_ones() -> None:
    assert set(DEFAULT_PLATFORM_PERMISSIONS) == ACCOUNT_LEVEL_PERMISSIONS | SUM_BASE_PERMISSIONS


def test_the_default_permissions_never_include_a_service_permission_or_an_admin_permission() -> (
    None
):
    for permission in DEFAULT_PLATFORM_PERMISSIONS:
        assert not permission.startswith("ipm."), permission  # chegam pelo SUM, ao ligar o serviço
        assert not permission.endswith(".admin"), permission  # fora do Project Grant


def test_the_policy_records_the_sorted_permissions_without_repeating_any() -> None:
    policy = AccountPolicy()
    assert policy._platform_permissions == sorted(set(DEFAULT_PLATFORM_PERMISSIONS))  # pyright: ignore[reportPrivateUsage]
