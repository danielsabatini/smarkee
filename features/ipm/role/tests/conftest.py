"""Isola os testes do `config.toml` e dos segredos montados da máquina (decisão 0067)."""

from pathlib import Path

import pytest


@pytest.fixture(autouse=True)
def isolate_configuration_files(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    """Sem `config.toml` nem diretório de segredos, salvo no teste que os cria."""
    monkeypatch.setenv("SMARKEE_CONFIG_PATH", str(tmp_path / "sem-config.toml"))
    monkeypatch.setenv("SMARKEE_SECRETS_DIR", str(tmp_path / "sem-segredos"))
