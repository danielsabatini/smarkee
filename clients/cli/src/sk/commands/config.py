"""Comandos `sk config`: consulta e altera o arquivo de configuração.

As chaves vêm dos modelos de configuração (`sk.settings`): um campo novo aparece aqui sem
mudança neste módulo. O arquivo é gerenciado pelo sk: uma alteração regrava as seções a partir
dos valores validados, e comentários feitos à mão não são preservados.
"""

from dataclasses import dataclass
from typing import Annotated, Any, NoReturn, cast

import typer
from pydantic import BaseModel, ValidationError
from pydantic.alias_generators import to_camel

from sk import ui
from sk.files import write_private_file
from sk.settings import (
    AuthSettings,
    ConfigurationError,
    CoreSettings,
    IpmSettings,
    SkSettings,
    SumSettings,
    config_file_path,
    convert_file_document,
    read_config_document,
    render_section,
)

EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2

SECTION_MODELS: dict[str, type[BaseModel]] = {
    "auth": AuthSettings,
    "core": CoreSettings,
    "sum": SumSettings,
    "ipm": IpmSettings,
}
# Chaves que são endereços: precisam começar com http:// ou https://.
URL_KEYS = {"auth.issuer", "core.apiUrl"}

config_app = typer.Typer(
    help="Inspect and change the sk configuration file.",
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)


@dataclass(frozen=True, slots=True)
class ConfigKey:
    """Uma chave do arquivo: seção, nome no arquivo (camelCase) e tipo do valor."""

    section: str
    file_name: str
    field_name: str
    is_boolean: bool

    @property
    def dotted(self) -> str:
        return f"{self.section}.{self.file_name}"


def known_keys() -> dict[str, ConfigKey]:
    keys: dict[str, ConfigKey] = {}
    for section, model in SECTION_MODELS.items():
        for field_name, field in model.model_fields.items():
            key = ConfigKey(
                section=section,
                file_name=to_camel(field_name),
                field_name=field_name,
                is_boolean=field.annotation is bool,
            )
            keys[key.dotted] = key
    return keys


def _exit_with(error: Exception, title: str, hint: str, code: int) -> NoReturn:
    ui.error(title, str(error), hint=hint)
    raise typer.Exit(code) from error


def _read_or_exit() -> dict[str, Any]:
    try:
        return read_config_document(config_file_path())
    except ConfigurationError as error:
        _exit_with(
            error,
            "Invalid configuration",
            "Fix the file or run `sk init --force`.",
            EXIT_USAGE_ERROR,
        )


def _require_argument(value: str | None, label: str) -> str:
    # Argumentos obrigatórios são validados aqui, e não pelo Typer, para não exibir "[required]".
    if value is None:
        ui.error(
            "Missing required argument",
            f"Provide {label}.",
            hint="See the order with `sk config --help`.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return value


def _key_or_exit(name: str | None) -> ConfigKey:
    name = _require_argument(name, "the key")
    keys = known_keys()
    if name not in keys:
        ui.error(
            "Unknown key",
            f"{name} does not exist.",
            hint=f"Valid keys: {', '.join(sorted(keys))}.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return keys[name]


def _stored_value(document: dict[str, Any], key: ConfigKey) -> str | bool | None:
    section: object = document.get(key.section)
    if not isinstance(section, dict):
        return None
    table = cast(dict[str, object], section)
    value = table.get(key.file_name)
    return value if isinstance(value, str | bool) else None


def _text(value: str | bool) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return value


def _parse_value(key: ConfigKey, raw: str) -> str | bool:
    if key.is_boolean:
        if raw not in ("true", "false"):
            ui.error(
                "Invalid value",
                f"{key.dotted} accepts only true or false.",
                hint="Use true or false.",
            )
            raise typer.Exit(EXIT_USAGE_ERROR)
        return raw == "true"
    if not raw.strip():
        ui.error("Empty value", f"{key.dotted} cannot be empty.")
        raise typer.Exit(EXIT_USAGE_ERROR)
    if key.dotted in URL_KEYS and not raw.startswith(("http://", "https://")):
        ui.error(
            "Invalid address",
            f"{key.dotted} must start with http:// or https://.",
            hint="Provide the full address, for example https://api.smarkee.com.br.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return raw


@config_app.command("list", help="Show every key and the value stored for each.")
def list_command() -> None:
    path = config_file_path()
    document = _read_or_exit()
    rows: list[tuple[str, str]] = []
    for key in known_keys().values():
        value = _stored_value(document, key)
        rows.append((key.dotted, "unset" if value is None else _text(value)))
    ui.panel("Configuration", rows)
    if not path.exists():
        ui.note(f"There is no file at {path}. Run `sk init` to create it.")
    else:
        ui.note(f"File: {path}. SK_* variables and parameters take precedence over it.")


@config_app.command(
    "get",
    help="Show the stored value of a key, unformatted (useful in scripts).",
)
def get_command(
    name: Annotated[
        str | None,
        typer.Argument(help="Key, such as auth.issuer or core.apiUrl (required)."),
    ] = None,
) -> None:
    key = _key_or_exit(name)
    value = _stored_value(_read_or_exit(), key)
    if value is None:
        ui.error(
            "Not set",
            f"{name} has no value in the file.",
            hint=f"Use `sk config set {name} <value>`.",
        )
        raise typer.Exit(EXIT_FAILURE)
    # Saída de dado para scripts, e não mensagem ao usuário: sem painel nem cor.
    typer.echo(_text(value))


@config_app.command(
    "set",
    help=(
        "Store the value of a key and rewrite the file. Comments written by hand are not preserved."
    ),
)
def set_command(
    name: Annotated[
        str | None,
        typer.Argument(help="Key, such as auth.issuer or core.apiUrl (required)."),
    ] = None,
    raw_value: Annotated[
        str | None,
        typer.Argument(help="New value (required). Booleans accept only true or false."),
    ] = None,
) -> None:
    key = _key_or_exit(name)
    value_text = _require_argument(raw_value, "the value")
    path = config_file_path()
    if not path.exists():
        ui.error(
            "Configuration not found",
            f"There is no file at {path}.",
            hint="Run `sk init` to create it.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    value = _parse_value(key, value_text)

    document = _read_or_exit()
    section = dict(document.get(key.section, {}))
    section[key.file_name] = value
    document[key.section] = section
    try:
        # Valida o documento inteiro, como o carregamento faz: chaves e valores.
        values = convert_file_document(SkSettings, document, path=path)
        auth = AuthSettings.model_validate(values.get("auth", {}))
        core = CoreSettings.model_validate(values.get("core", {}))
        sum_settings = SumSettings.model_validate(values.get("sum", {}))
        ipm_settings = IpmSettings.model_validate(values.get("ipm", {}))
    except (ValidationError, ConfigurationError) as error:
        _exit_with(error, "Value refused", "Fix the value and repeat.", EXIT_USAGE_ERROR)

    # Todas as seções são regravadas: omitir uma apagaria o que o arquivo já tinha nela.
    content = render_section("auth", auth) + "\n" + render_section("core", core)
    if sum_settings.project_id:
        content += "\n" + render_section("sum", sum_settings)
    if ipm_settings.project_id:
        content += "\n" + render_section("ipm", ipm_settings)
    try:
        write_private_file(path, content)
    except OSError as error:
        ui.error("Could not write the configuration", f"{path}: {error.strerror}")
        raise typer.Exit(EXIT_FAILURE) from error

    ui.panel(
        "Configuration updated",
        [("key", key.dotted), ("value", _text(value)), ("file", str(path))],
    )
    section_allows_http = {"auth": auth, "core": core}.get(key.section, core).allow_insecure_http
    if isinstance(value, str) and value.startswith("http://") and not section_allows_http:
        ui.warning(
            f"{key.dotted} is HTTP without permission: use will refuse this address until "
            f"`{key.section}.allowInsecureHttp` is true."
        )
