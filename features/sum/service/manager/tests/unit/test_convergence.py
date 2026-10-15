import pytest

from sum_service_manager.domain.convergence import phase_after_observation

ROLES = ("ipm.organization.get", "ipm.organization.list")


@pytest.mark.parametrize(
    ("lifecycle", "presence", "observed", "expected"),
    [
        ("present", "present", ROLES, "Ready"),
        ("present", "present", (*ROLES, "ipm.outro.x"), "Ready"),
        ("present", "present", ROLES[:1], "Reconciling"),
        ("present", "present", (), "Reconciling"),
        ("present", "absent", (), "Reconciling"),
        ("absent", "present", (), "Ready"),
        ("absent", "absent", (), "Ready"),
        ("absent", "present", ROLES[:1], "Reconciling"),
    ],
)
def test_the_phase_follows_the_observed_roles(
    lifecycle: str, presence: str, observed: tuple[str, ...], expected: str
) -> None:
    phase = phase_after_observation(
        lifecycle=lifecycle, desired_roles=ROLES, presence=presence, observed_roles=observed
    )
    assert phase == expected


def test_an_unknown_observation_never_changes_the_phase() -> None:
    assert (
        phase_after_observation(
            lifecycle="present", desired_roles=ROLES, presence="unknown", observed_roles=()
        )
        is None
    )
