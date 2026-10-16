"""Isola os testes do ambiente de quem os roda: nenhuma variável `SK_*` vaza para dentro deles."""

import os

import pytest


@pytest.fixture(autouse=True)
def clean_sk_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Quem faz `source .env` (as sobrescritas de dev) não pode mudar o resultado dos testes."""
    for name in [name for name in os.environ if name.startswith("SK_")]:
        monkeypatch.delenv(name)
