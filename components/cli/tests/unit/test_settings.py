from pathlib import Path

import pytest
from pydantic import ValidationError

from sk.commands.auth import load_auth_settings
from sk.settings import (
    CONFIG_FILE_NAME,
    AuthSettings,
    ConfigurationError,
    config_directory,
    render_section,
)


@pytest.fixture
def config_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """Isola o diretório de configuração e as variáveis SK_* do ambiente do desenvolvedor."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    for variable in ("SK_AUTH_ISSUER", "SK_AUTH_CLIENT_ID", "SK_AUTH_ALLOW_INSECURE_HTTP"):
        monkeypatch.delenv(variable, raising=False)
    return tmp_path


def write_config(config_home: Path, content: str) -> None:
    directory = config_home / "sk"
    directory.mkdir(parents=True, exist_ok=True)
    (directory / CONFIG_FILE_NAME).write_text(content, encoding="utf-8")


NO_COMMAND_LINE_VALUES: dict[str, object] = {
    "issuer": None,
    "client_id": None,
    "allow_insecure_http": False,
}


def test_config_directory_respects_xdg_config_home() -> None:
    assert config_directory({"XDG_CONFIG_HOME": "/custom"}) == Path("/custom/sk")


def test_config_directory_falls_back_to_home_config() -> None:
    assert config_directory({}) == Path.home() / ".config" / "sk"


@pytest.mark.usefixtures("config_home")
def test_defaults_apply_without_any_source() -> None:
    settings = load_auth_settings(NO_COMMAND_LINE_VALUES)
    assert settings.issuer is None
    assert settings.client_id is None
    assert settings.allow_insecure_http is False


def test_config_file_is_read_from_auth_table(config_home: Path) -> None:
    write_config(
        config_home,
        '[auth]\nissuer = "https://file.example"\nclientId = "file-client"\n'
        "allowInsecureHttp = true\n",
    )
    settings = load_auth_settings(NO_COMMAND_LINE_VALUES)
    assert settings.issuer == "https://file.example"
    assert settings.client_id == "file-client"
    assert settings.allow_insecure_http is True


def test_environment_overrides_config_file_field_by_field(
    config_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(config_home, '[auth]\nissuer = "https://file.example"\nclientId = "file-client"\n')
    monkeypatch.setenv("SK_AUTH_ISSUER", "https://env.example")
    settings = load_auth_settings(NO_COMMAND_LINE_VALUES)
    assert settings.issuer == "https://env.example"
    assert settings.client_id == "file-client"


def test_command_line_overrides_environment_and_config_file(
    config_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_config(config_home, '[auth]\nissuer = "https://file.example"\nclientId = "file-client"\n')
    monkeypatch.setenv("SK_AUTH_ISSUER", "https://env.example")
    monkeypatch.setenv("SK_AUTH_CLIENT_ID", "env-client")
    settings = load_auth_settings(
        {"issuer": "https://cli.example", "client_id": None, "allow_insecure_http": False}
    )
    assert settings.issuer == "https://cli.example"
    assert settings.client_id == "env-client"


def test_unset_flag_does_not_override_lower_sources(
    config_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("SK_AUTH_ALLOW_INSECURE_HTTP", "true")
    assert load_auth_settings(NO_COMMAND_LINE_VALUES).allow_insecure_http is True


def test_unknown_key_in_config_file_is_rejected(config_home: Path) -> None:
    write_config(config_home, '[auth]\nisuer = "https://typo.example"\n')
    with pytest.raises(ConfigurationError, match=r"chave desconhecida .*auth\.isuer"):
        load_auth_settings(NO_COMMAND_LINE_VALUES)


def test_snake_case_key_in_config_file_is_rejected(config_home: Path) -> None:
    write_config(config_home, '[auth]\nclient_id = "file-client"\n')
    with pytest.raises(ConfigurationError, match=r"auth\.client_id.*camelCase: allowInsecureHttp"):
        load_auth_settings(NO_COMMAND_LINE_VALUES)


def test_unknown_section_in_config_file_is_rejected(config_home: Path) -> None:
    write_config(config_home, '[ipm]\napiUrl = "https://api.example"\n')
    with pytest.raises(ConfigurationError, match=r"chave desconhecida .*ipm"):
        load_auth_settings(NO_COMMAND_LINE_VALUES)


def test_section_must_be_a_table(config_home: Path) -> None:
    write_config(config_home, 'auth = "https://file.example"\n')
    with pytest.raises(ConfigurationError, match="tabela TOML"):
        load_auth_settings(NO_COMMAND_LINE_VALUES)


def test_invalid_toml_is_reported(config_home: Path) -> None:
    write_config(config_home, "[auth\n")
    with pytest.raises(ConfigurationError, match="TOML inválido"):
        load_auth_settings(NO_COMMAND_LINE_VALUES)


def test_invalid_value_type_is_a_validation_error(config_home: Path) -> None:
    write_config(config_home, '[auth]\nallowInsecureHttp = "talvez"\n')
    with pytest.raises(ValidationError):
        load_auth_settings(NO_COMMAND_LINE_VALUES)


def test_config_file_is_ignored_when_requested(config_home: Path) -> None:
    write_config(config_home, '[auth]\nissuer = "https://file.example"\n')
    settings = load_auth_settings(NO_COMMAND_LINE_VALUES, include_config_file=False)
    assert settings.issuer is None


def test_rendered_section_uses_camel_case_and_round_trips(config_home: Path) -> None:
    rendered = render_section(
        "auth",
        AuthSettings(
            issuer='https://issuer.example/"quoted"',
            client_id="394397791373230085",
            allow_insecure_http=True,
        ),
    )
    assert rendered == (
        "[auth]\n"
        'issuer = "https://issuer.example/\\"quoted\\""\n'
        'clientId = "394397791373230085"\n'
        "allowInsecureHttp = true\n"
    )
    write_config(config_home, rendered)
    settings = load_auth_settings(NO_COMMAND_LINE_VALUES)
    assert settings.issuer == 'https://issuer.example/"quoted"'
    assert settings.client_id == "394397791373230085"
    assert settings.allow_insecure_http is True


def test_rendered_section_omits_unset_fields() -> None:
    assert render_section("auth", AuthSettings(issuer="https://issuer.example")) == (
        '[auth]\nissuer = "https://issuer.example"\nallowInsecureHttp = false\n'
    )
