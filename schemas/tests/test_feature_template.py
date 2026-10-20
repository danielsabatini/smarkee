"""O template das features (`templates/feature`) é replicado nas features (decisão 0064)."""

import importlib.util
from pathlib import Path
from typing import Any, cast

import pytest

TEMPLATE = Path(__file__).resolve().parents[2] / "templates" / "feature"


def _load_sync() -> Any:
    spec = importlib.util.spec_from_file_location("feature_template_sync", TEMPLATE / "sync.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_feature_copies_match_the_template() -> None:
    """Se falhar: `python templates/feature/sync.py` regrava as cópias (decisão 0064)."""
    divergent = cast(list[Path], _load_sync().divergent_files())
    assert divergent == [], [str(path) for path in divergent]


def test_every_profile_names_existing_features() -> None:
    module = _load_sync()
    existing = {f"{path.parent.name}/{path.name}" for path, _ in cast(list[Any], module.features())}
    for profile, names in cast(dict[str, tuple[str, ...]], module.PROFILES).items():
        assert set(names) <= existing, profile
        assert (TEMPLATE / "optional" / profile).is_dir()


def test_existing_features_are_found() -> None:
    """As features existentes são sempre encontradas; uma feature nova não exige editar o teste."""
    packages = {values["@@PACKAGE@@"] for _, values in cast(list[Any], _load_sync().features())}
    assert {"core_account", "ipm_organization", "sum_service"} <= packages


@pytest.mark.parametrize(
    ("module_name", "resource_type"), [("Core", "account"), ("core", "my-type"), ("", "account")]
)
def test_new_feature_rejects_invalid_names(module_name: str, resource_type: str) -> None:
    with pytest.raises(ValueError):
        _load_sync().new_feature(module_name, resource_type)


def test_new_feature_rejects_existing_feature() -> None:
    with pytest.raises(FileExistsError):
        _load_sync().new_feature("core", "account")
