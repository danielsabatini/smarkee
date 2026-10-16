"""Roles que o cadastro concede (decisões 0025, 0032 e 0033)."""

from core_user_manager.domain.user import DEFAULT_PLATFORM_ROLES, UserPolicy

SUM_BASE_ROLES = {"sum.ipm.disable", "sum.ipm.enable", "sum.ipm.get"}


def test_the_default_roles_are_the_core_ones_plus_the_base_roles_of_the_sum() -> None:
    assert set(DEFAULT_PLATFORM_ROLES) == {"core.user.delete", "core.user.get"} | SUM_BASE_ROLES


def test_the_default_roles_never_include_a_service_role_or_an_admin_role() -> None:
    for role in DEFAULT_PLATFORM_ROLES:
        assert not role.startswith("ipm."), role  # chegam pelo SUM, ao ligar o serviço
        assert not role.endswith(".admin"), role  # fora do Project Grant


def test_the_policy_records_the_sorted_roles_without_repeating_any() -> None:
    policy = UserPolicy()
    assert policy._platform_roles == sorted(set(DEFAULT_PLATFORM_ROLES))  # pyright: ignore[reportPrivateUsage]
