"""O template das features (`templates/feature`) é replicado nas features (decisão 0064)."""

import importlib.util
from pathlib import Path
from typing import Any, cast

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


def test_every_feature_receives_the_template() -> None:
    expected = cast(dict[Path, str], _load_sync().expected_files())
    features = cast(list[Any], _load_sync().features())
    assert len(features) >= 3
    assert len(expected) == len(features) * sum(
        1 for path in (TEMPLATE / "files").rglob("*") if path.is_file()
    )
