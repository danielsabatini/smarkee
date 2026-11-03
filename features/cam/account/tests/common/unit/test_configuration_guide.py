"""O guia `docs/CONFIGURATION.md` acompanha os `settings.py` dos papéis (decisões 0067 e 0070)."""

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest

FEATURE_DIR = Path(__file__).resolve().parents[3]
GENERATOR = FEATURE_DIR.parents[2] / "templates" / "feature" / "configuration_guide.py"


def _load_generator() -> ModuleType:
    spec = importlib.util.spec_from_file_location("configuration_guide", GENERATOR)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.skipif(
    not GENERATOR.exists(), reason="o gerador do guia fica no repositório, não na imagem"
)
def test_configuration_guide_matches_the_settings_of_the_roles() -> None:
    guide = FEATURE_DIR / "docs" / "CONFIGURATION.md"
    expected = _load_generator().render_guide(FEATURE_DIR)
    assert guide.read_text(encoding="utf-8") == expected, (
        "docs/CONFIGURATION.md diverge dos settings.py: regenere com "
        "`uv run python ../../../templates/feature/configuration_guide.py`"
    )
