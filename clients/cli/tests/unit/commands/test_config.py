import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from sk.commands.config import known_keys
from sk.defaults import PRD_API_URL, PRD_ISSUER
from sk.main import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_configuration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for variable in (
        "SK_AUTH_ISSUER",
        "SK_AUTH_CLIENT_ID",
        "SK_AUTH_ALLOW_INSECURE_HTTP",
        "SK_API_URL",
        "SK_API_ALLOW_INSECURE_HTTP",
        "SK_CORE_PROJECT_ID",
        "SK_SUM_PROJECT_ID",
        "SK_IPM_PROJECT_ID",
    ):
        monkeypatch.delenv(variable, raising=False)


def config_file(tmp_path: Path) -> Path:
    return tmp_path / "sk" / "config.toml"


def write_overrides(tmp_path: Path) -> None:
    """Um arquivo de sobrescritas, como o do desenvolvimento."""
    config_file(tmp_path).parent.mkdir(exist_ok=True)
    config_file(tmp_path).write_text(
        '[auth]\nissuer = "https://issuer.example"\n[api]\nurl = "https://api.example"\n',
        encoding="utf-8",
    )


def test_keys_come_from_the_models() -> None:
    keys = known_keys()
    assert {"auth.issuer", "auth.clientId", "auth.allowInsecureHttp"} <= set(keys)
    assert {"api.url", "api.allowInsecureHttp"} <= set(keys)
    assert {"core.projectId", "sum.projectId", "ipm.projectId"} <= set(keys)
    assert keys["auth.allowInsecureHttp"].is_boolean
    assert not keys["auth.issuer"].is_boolean


def test_list_without_a_file_shows_the_platform_defaults(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", "list"])
    assert result.exit_code == 0, result.stderr
    assert PRD_ISSUER in result.stdout
    assert PRD_API_URL in result.stdout
    assert "every value is the platform default" in result.stdout
    assert result.stdout.count("default") >= 8  # a coluna `source` de cada chave
    assert not config_file(tmp_path).exists()  # listar não cria arquivo


def test_list_shows_the_effective_value_and_where_it_comes_from(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_overrides(tmp_path)
    monkeypatch.setenv("SK_SUM_PROJECT_ID", "from-env")
    shown = runner.invoke(app, ["config", "list"]).stdout
    cells = [line.strip("│ ").split() for line in shown.splitlines() if line.startswith("│ ")]
    rows = {row[0]: row[1:] for row in cells if len(row) == 3}
    assert rows["auth.issuer"] == ["https://issuer.example", "file"]
    assert rows["api.url"] == ["https://api.example", "file"]
    assert rows["sum.projectId"] == ["from-env", "env"]
    assert rows["auth.clientId"][-1] == "default"


def test_get_prints_only_the_effective_value(tmp_path: Path) -> None:
    default = runner.invoke(app, ["config", "get", "auth.issuer"])
    assert default.exit_code == 0
    assert default.stdout == f"{PRD_ISSUER}\n"
    write_overrides(tmp_path)
    overridden = runner.invoke(app, ["config", "get", "auth.issuer"])
    assert overridden.stdout == "https://issuer.example\n"


def test_get_unknown_key_is_a_usage_error() -> None:
    result = runner.invoke(app, ["config", "get", "auth.inexistente"])
    assert result.exit_code == 2
    assert "Unknown key" in result.stderr


def test_set_creates_the_file_with_only_the_given_key(tmp_path: Path) -> None:
    assert not config_file(tmp_path).exists()
    result = runner.invoke(app, ["config", "set", "auth.issuer", "https://issuer.example"])
    assert result.exit_code == 0, result.stderr
    text = config_file(tmp_path).read_text(encoding="utf-8")
    assert text == '[auth]\nissuer = "https://issuer.example"\n'  # o resto fica no padrão


def test_set_changes_only_the_given_key(tmp_path: Path) -> None:
    write_overrides(tmp_path)
    result = runner.invoke(app, ["config", "set", "api.url", "https://api.other.example"])
    assert result.exit_code == 0, result.stderr
    text = config_file(tmp_path).read_text(encoding="utf-8")
    assert 'url = "https://api.other.example"' in text
    assert 'issuer = "https://issuer.example"' in text
    assert "clientId" not in text  # nunca gravado: continua no padrão


def test_the_project_ids_of_the_modules_are_settable_and_survive_other_changes(
    tmp_path: Path,
) -> None:
    for key, value in (
        ("core.projectId", "111"),
        ("sum.projectId", "222"),
        ("ipm.projectId", "333"),
    ):
        result = runner.invoke(app, ["config", "set", key, value])
        assert result.exit_code == 0, result.stderr
    # Uma alteração em outra seção não pode apagar as chaves de projeto já gravadas.
    result = runner.invoke(app, ["config", "set", "auth.clientId", "novo-client"])
    assert result.exit_code == 0, result.stderr
    text = config_file(tmp_path).read_text(encoding="utf-8")
    assert 'projectId = "111"' in text and "[sum]" in text and 'projectId = "222"' in text
    assert runner.invoke(app, ["config", "get", "sum.projectId"]).stdout.strip() == "222"
    assert runner.invoke(app, ["config", "get", "core.projectId"]).stdout.strip() == "111"
    assert runner.invoke(app, ["config", "get", "ipm.projectId"]).stdout.strip() == "333"


def test_the_active_organization_is_settable_and_validated(tmp_path: Path) -> None:
    assert "ipm.organizationId" in known_keys()
    resource_id = "01a14168-b59d-7475-8db7-c5cf57fa100b"

    refused = runner.invoke(app, ["config", "set", "ipm.organizationId", "../x?y"])
    assert refused.exit_code == 2
    assert not config_file(tmp_path).exists()
    # Diz o que falhou, sem repetir o valor nem expor o texto bruto do pydantic.
    assert "organizationId invalid" in " ".join(refused.stderr.split())
    assert "../x" not in refused.stderr and "pydantic" not in refused.stderr

    saved = runner.invoke(app, ["config", "set", "ipm.organizationId", resource_id])
    assert saved.exit_code == 0, saved.stderr
    assert runner.invoke(app, ["config", "get", "ipm.organizationId"]).stdout.strip() == resource_id


def test_set_boolean_accepts_true_and_false(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", "set", "auth.allowInsecureHttp", "true"])
    assert result.exit_code == 0, result.stderr
    assert "allowInsecureHttp = true" in config_file(tmp_path).read_text(encoding="utf-8")


def test_set_boolean_rejects_other_values(tmp_path: Path) -> None:
    write_overrides(tmp_path)
    before = config_file(tmp_path).read_text(encoding="utf-8")
    result = runner.invoke(app, ["config", "set", "auth.allowInsecureHttp", "sim"])
    assert result.exit_code == 2
    assert "true or false" in result.stderr
    assert config_file(tmp_path).read_text(encoding="utf-8") == before


def test_set_url_must_have_a_scheme(tmp_path: Path) -> None:
    write_overrides(tmp_path)
    before = config_file(tmp_path).read_text(encoding="utf-8")
    result = runner.invoke(app, ["config", "set", "api.url", "api.example"])
    assert result.exit_code == 2
    assert "http:// or https://" in result.stderr
    assert config_file(tmp_path).read_text(encoding="utf-8") == before


def test_set_http_without_permission_warns(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", "set", "api.url", "http://api.example"])
    assert result.exit_code == 0, result.stderr
    assert "HTTP without permission" in result.stderr
    assert 'url = "http://api.example"' in config_file(tmp_path).read_text(encoding="utf-8")


def test_set_refuses_a_file_with_invalid_keys(tmp_path: Path) -> None:
    config_file(tmp_path).parent.mkdir()
    config_file(tmp_path).write_text("[auth]\nclient_id = 'x'\n", encoding="utf-8")
    before = config_file(tmp_path).read_text(encoding="utf-8")
    result = runner.invoke(app, ["config", "set", "auth.issuer", "https://issuer.example"])
    assert result.exit_code == 2
    assert config_file(tmp_path).read_text(encoding="utf-8") == before


def test_missing_arguments_are_usage_errors() -> None:
    result = runner.invoke(app, ["config", "get"])
    assert result.exit_code == 2
    assert "Missing required argument" in result.stderr
    result = runner.invoke(app, ["config", "set", "auth.issuer"])
    assert result.exit_code == 2
    assert "the value" in result.stderr


def test_json_list_prints_native_values_and_sources(tmp_path: Path) -> None:
    write_overrides(tmp_path)
    result = runner.invoke(app, ["--output", "json", "config", "list"])
    assert result.exit_code == 0, result.stderr
    items = {item["key"]: item for item in json.loads(result.stdout)}
    assert items["api.url"] == {"key": "api.url", "value": "https://api.example", "source": "file"}
    assert items["auth.allowInsecureHttp"]["value"] is False
    assert "File:" in result.stderr and "File:" not in result.stdout


def test_json_on_get_and_set_is_refused_and_does_not_write(tmp_path: Path) -> None:
    got = runner.invoke(app, ["--output", "json", "config", "get", "api.url"])
    assert got.exit_code == 2
    refused = runner.invoke(
        app, ["--output", "json", "config", "set", "api.url", "https://x.teste"]
    )
    assert refused.exit_code == 2
    assert not config_file(tmp_path).exists()


def test_list_shows_every_settings_section() -> None:
    from sk.settings import SkSettings

    result = runner.invoke(app, ["--output", "json", "config", "list"])
    assert result.exit_code == 0
    shown = {item["key"].split(".")[0] for item in json.loads(result.stdout)}
    assert shown == set(SkSettings.model_fields)


def test_invalid_file_does_not_suggest_a_removed_command(tmp_path: Path) -> None:
    config_file(tmp_path).parent.mkdir()
    config_file(tmp_path).write_text("garbage = [", encoding="utf-8")
    result = runner.invoke(app, ["config", "list"])
    assert result.exit_code == 2
    assert "sk init" not in result.output


def test_an_integer_key_is_stored_as_a_number_and_shown_back(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", "set", "api.timeoutSeconds", "30"])
    assert result.exit_code == 0
    assert "timeoutSeconds = 30\n" in config_file(tmp_path).read_text(encoding="utf-8")
    assert runner.invoke(app, ["config", "get", "api.timeoutSeconds"]).stdout.strip() == "30"


@pytest.mark.parametrize("value", ["abc", "1.5", "-3", "٣"])
def test_an_integer_key_refuses_text(value: str, tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", "set", "api.timeoutSeconds", value])
    assert result.exit_code == 2
    assert not config_file(tmp_path).exists()


@pytest.mark.parametrize("value", ["0", "301"])
def test_an_integer_key_out_of_range_is_refused_before_writing(value: str, tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", "set", "api.timeoutSeconds", value])
    assert result.exit_code == 2
    assert not config_file(tmp_path).exists()


def test_unset_returns_the_key_to_the_default_and_drops_an_empty_section(tmp_path: Path) -> None:
    runner.invoke(app, ["config", "set", "api.url", "https://api.example"])
    runner.invoke(app, ["config", "set", "auth.issuer", "https://issuer.example"])
    result = runner.invoke(app, ["config", "unset", "api.url"])
    assert result.exit_code == 0
    content = config_file(tmp_path).read_text(encoding="utf-8")
    assert "[api]" not in content
    assert "api.example" not in content
    assert "issuer.example" in content
    assert runner.invoke(app, ["config", "get", "api.url"]).stdout.strip() == PRD_API_URL


def test_unset_keeps_the_other_keys_of_the_section(tmp_path: Path) -> None:
    runner.invoke(app, ["config", "set", "api.url", "https://api.example"])
    runner.invoke(app, ["config", "set", "api.timeoutSeconds", "30"])
    runner.invoke(app, ["config", "unset", "api.timeoutSeconds"])
    content = config_file(tmp_path).read_text(encoding="utf-8")
    assert "timeoutSeconds" not in content
    assert "api.example" in content


def test_unset_is_idempotent_and_does_not_touch_the_file(tmp_path: Path) -> None:
    write_overrides(tmp_path)
    before = config_file(tmp_path).read_text(encoding="utf-8")
    result = runner.invoke(app, ["config", "unset", "sum.projectId"])
    assert result.exit_code == 0
    assert "already at the default" in result.output
    assert config_file(tmp_path).read_text(encoding="utf-8") == before


def test_unset_without_a_file_creates_nothing(tmp_path: Path) -> None:
    result = runner.invoke(app, ["config", "unset", "api.url"])
    assert result.exit_code == 0
    assert not config_file(tmp_path).exists()


def test_unset_warns_when_an_environment_variable_still_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_overrides(tmp_path)
    monkeypatch.setenv("SK_API_URL", "https://from-env.example")
    result = runner.invoke(app, ["config", "unset", "api.url"])
    assert result.exit_code == 0
    assert "SK_API_URL" in result.output
    assert "still takes precedence" in result.output


def test_unset_refuses_an_unknown_key_and_a_missing_argument() -> None:
    assert runner.invoke(app, ["config", "unset", "api.nada"]).exit_code == 2
    assert runner.invoke(app, ["config", "unset"]).exit_code == 2


def test_unset_refuses_an_invalid_file_without_rewriting_it(tmp_path: Path) -> None:
    config_file(tmp_path).parent.mkdir()
    config_file(tmp_path).write_text("garbage = [", encoding="utf-8")
    result = runner.invoke(app, ["config", "unset", "api.url"])
    assert result.exit_code == 2
    assert config_file(tmp_path).read_text(encoding="utf-8") == "garbage = ["
