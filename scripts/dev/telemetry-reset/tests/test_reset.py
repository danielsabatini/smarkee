"""Limpeza dos sinais de telemetria, contra uma árvore de pastas temporária."""

from pathlib import Path

import pytest

from smarkee_dev_telemetry_reset.main import find_signal_files, run


def make_tree(root: Path) -> dict[str, Path]:
    files = {
        "platform_active": root / "infrastructure/dev/platform-telemeter/logs/infra/logs.jsonl",
        "platform_rotated": root
        / "infrastructure/dev/platform-telemeter/logs/infra/logs-2026-10-19T18-01-23-size.jsonl",
        "platform_traces": root / "infrastructure/dev/platform-telemeter/traces/traces.jsonl",
        "feature_logs": root / "features/ipm/organization/telemeter/logs/logs.jsonl",
        "feature_traces": root / "features/ipm/organization/telemeter/traces/traces.jsonl",
    }
    for path in files.values():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('{"resourceLogs":[]}\n', encoding="utf-8")
    return files


def keep_files(root: Path) -> list[Path]:
    """Arquivos que nunca podem ser tocados: `.gitkeep`, configuração e dados de outras pastas."""
    keep = [
        root / "infrastructure/dev/platform-telemeter/logs/infra/.gitkeep",
        root / "features/ipm/organization/telemeter/config.yaml",
        root / "infrastructure/dev/telemetry-router/data/queue.db",
        root / "features/ipm/organization/telemeter/logs/notes.txt",
    ]
    for path in keep:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("keep", encoding="utf-8")
    return keep


def test_without_apply_it_only_lists_and_reports_that_signals_remain(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    files = make_tree(tmp_path)

    code = run(tmp_path, apply=False)

    assert code == 1
    assert all(path.stat().st_size > 0 for path in files.values())
    assert "Nothing changed" in capsys.readouterr().out


def test_apply_truncates_the_active_files_and_removes_the_rotated_ones(tmp_path: Path) -> None:
    files = make_tree(tmp_path)
    keep = keep_files(tmp_path)

    code = run(tmp_path, apply=True)

    assert code == 0
    assert not files["platform_rotated"].exists()
    for name in ("platform_active", "platform_traces", "feature_logs", "feature_traces"):
        assert files[name].exists() and files[name].stat().st_size == 0  # o coletor segue gravando
    assert all(path.read_text(encoding="utf-8") == "keep" for path in keep)
    assert find_signal_files(tmp_path) == []


def test_a_second_run_finds_nothing_left(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    make_tree(tmp_path)
    run(tmp_path, apply=True)
    capsys.readouterr()

    assert run(tmp_path, apply=False) == 0  # só arquivos vazios: nada a limpar
    assert "No telemetry signals" in capsys.readouterr().out


def test_symbolic_links_are_never_followed(tmp_path: Path) -> None:
    make_tree(tmp_path)
    outside = tmp_path / "outside.jsonl"
    outside.write_text("important", encoding="utf-8")
    link = tmp_path / "infrastructure/dev/platform-telemeter/logs/app/logs.jsonl"
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(outside)

    run(tmp_path, apply=True)

    assert outside.read_text(encoding="utf-8") == "important"


def test_it_refuses_a_directory_that_is_not_the_repository(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert run(tmp_path, apply=True) == 2
    assert "is this the repository" in capsys.readouterr().err
