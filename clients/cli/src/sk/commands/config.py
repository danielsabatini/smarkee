"""Comandos `sk config`: consulta a configuração efetiva e altera o arquivo de sobrescritas.

As chaves vêm dos modelos de configuração (`sk.settings`): um campo novo aparece aqui sem
mudança neste módulo. O arquivo é gerenciado pelo sk: uma alteração regrava as seções a partir
dos valores validados, e comentários feitos à mão não são preservados.
"""

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Annotated, Any, NoReturn, cast

import typer
from pydantic import BaseModel, ValidationError
from pydantic.alias_generators import to_camel

from sk import ui
from sk.command_app import SkTyper
from sk.defaults import PRD_API_URL
from sk.files import write_private_file
from sk.settings import (
    ApiSettings,
    AuthSettings,
    BsmSettings,
    ConfigurationError,
    CoreSettings,
    IpmSettings,
    OperatorSettings,
    SkSettings,
    SumSettings,
    config_file_path,
    convert_file_document,
    read_config_document,
    render_section,
)

ConfigValue = str | bool | int
"""Tipos de valor que o arquivo guarda: texto, booleano ou inteiro."""

EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2

SECTION_MODELS: dict[str, type[BaseModel]] = {
    "auth": AuthSettings,
    "api": ApiSettings,
    "core": CoreSettings,
    "sum": SumSettings,
    "ipm": IpmSettings,
    "bsm": BsmSettings,
    "operator": OperatorSettings,
}
# Chaves que são endereços: precisam começar com http:// ou https://.
URL_KEYS = {"auth.issuer", "api.url"}

config_app = SkTyper(
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
    is_integer: bool = False

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
                is_integer=field.annotation is int,
            )
            keys[key.dotted] = key
    return keys


def _describe(error: Exception) -> str:
    """Texto do erro para a pessoa. Num `ValidationError`, só o que falhou: sem o valor informado
    nem o endereço de documentação do pydantic."""
    if isinstance(error, ValidationError):
        return "; ".join(
            f"{'.'.join(str(part) for part in item['loc'])}: "
            f"{item['msg'].removeprefix('Value error, ')}"
            for item in error.errors(include_input=False, include_url=False)
        )
    return str(error)


def _exit_with(error: Exception, title: str, hint: str, code: int) -> NoReturn:
    ui.error(title, _describe(error), hint=hint)
    raise typer.Exit(code) from error


def _read_or_exit() -> dict[str, Any]:
    try:
        return read_config_document(config_file_path())
    except ConfigurationError as error:
        _exit_with(
            error,
            "Invalid configuration",
            "Fix the file, or remove it to return to the defaults.",
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


def _stored_value(document: dict[str, Any], key: ConfigKey) -> ConfigValue | None:
    section: object = document.get(key.section)
    if not isinstance(section, dict):
        return None
    table = cast(dict[str, object], section)
    value = table.get(key.file_name)
    return value if isinstance(value, str | bool | int) else None


def _text(value: ConfigValue) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _parse_value(key: ConfigKey, raw: str) -> ConfigValue:
    if key.is_boolean:
        if raw not in ("true", "false"):
            ui.error(
                "Invalid value",
                f"{key.dotted} accepts only true or false.",
                hint="Use true or false.",
            )
            raise typer.Exit(EXIT_USAGE_ERROR)
        return raw == "true"
    if key.is_integer:
        if not (raw.isascii() and raw.isdecimal()):
            ui.error(
                "Invalid value",
                f"{key.dotted} accepts only a whole number.",
                hint="Use digits only, for example 10.",
            )
            raise typer.Exit(EXIT_USAGE_ERROR)
        return int(raw)
    if not raw.strip():
        ui.error("Empty value", f"{key.dotted} cannot be empty.")
        raise typer.Exit(EXIT_USAGE_ERROR)
    if key.dotted in URL_KEYS and not raw.startswith(("http://", "https://")):
        ui.error(
            "Invalid address",
            f"{key.dotted} must start with http:// or https://.",
            hint=f"Provide the full address, for example {PRD_API_URL}.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return raw


def _effective_values() -> dict[str, ConfigValue]:
    """Valor efetivo de cada chave (parâmetro, variável, arquivo ou padrão, nesta ordem)."""
    try:
        settings = SkSettings()
    except (ValidationError, ConfigurationError) as error:
        _exit_with(
            error,
            "Invalid configuration",
            "Fix the file or the SK_* variables.",
            EXIT_USAGE_ERROR,
        )
    values: dict[str, ConfigValue] = {}
    for key in known_keys().values():
        section = cast(BaseModel, getattr(settings, key.section))
        values[key.dotted] = cast("ConfigValue", getattr(section, key.field_name))
    return values


def _source_of(key: ConfigKey, document: dict[str, Any]) -> str:
    variable = f"SK_{key.section.upper()}_{key.field_name.upper()}"
    if variable in os.environ:
        return "env"
    return "file" if _stored_value(document, key) is not None else "default"


def _rewrite_file(document: dict[str, Any], *, path: Path) -> dict[str, BaseModel]:
    """Valida o `document` inteiro, como o carregamento faz, e regrava o arquivo `path`.

    Devolve as seções validadas. Levanta `ValidationError` ou `ConfigurationError` se o documento
    não vale, e `OSError` se a gravação falha.
    """
    values = convert_file_document(SkSettings, document, path=path)
    sections = {
        name: model.model_validate(values.get(name, {})) for name, model in SECTION_MODELS.items()
    }
    # Todas as seções são regravadas, mas só com os campos que o arquivo tem (as sobrescritas):
    # um valor que ficou no padrão não vai para o arquivo.
    content = "\n".join(
        render_section(name, model) for name, model in sections.items() if model.model_fields_set
    )
    write_private_file(path, content)
    return sections


def store_value(
    key: ConfigKey, value: ConfigValue, document: dict[str, Any], *, path: Path
) -> dict[str, BaseModel]:
    """Grava `value` em `key` no arquivo `path`, a partir do `document` lido dele.

    É o que `sk config set` faz, e também o que outros comandos usam quando precisam gravar uma
    configuração (por exemplo `sk ipm organization create --wait`). Valida o documento inteiro,
    como o carregamento faz. Devolve as seções validadas. Levanta `ValidationError` ou
    `ConfigurationError` se o valor ou o arquivo não valem, e `OSError` se a gravação falha.
    """
    section = dict(document.get(key.section, {}))
    section[key.file_name] = value
    return _rewrite_file({**document, key.section: section}, path=path)


def remove_value(key: ConfigKey, document: dict[str, Any], *, path: Path) -> None:
    """Remove `key` do arquivo `path` (o valor volta a ser o padrão) e o regrava.

    O contrário de `store_value`, com os mesmos erros. Uma seção que fica sem chaves deixa de
    existir no arquivo.
    """
    section = {
        name: v for name, v in dict(document.get(key.section, {})).items() if name != key.file_name
    }
    rest = {name: v for name, v in document.items() if name != key.section}
    _rewrite_file({**rest, **({key.section: section} if section else {})}, path=path)


@config_app.command(
    "list",
    structured=True,
    help=(
        "Show every key, its effective value and where the value comes from.\n\n"
        "Examples:\n\b\n"
        "  sk config list\n"
        "  sk --output json config list"
    ),
)
def list_command() -> None:
    path = config_file_path()
    document = _read_or_exit()
    effective = _effective_values()
    rows = [
        [key.dotted, _text(effective[key.dotted]), _source_of(key, document)]
        for key in known_keys().values()
    ]
    ui.table(
        "Configuration",
        ["key", "value", "source"],
        rows,
        data=[
            {"key": key.dotted, "value": effective[key.dotted], "source": _source_of(key, document)}
            for key in known_keys().values()
        ],
    )
    if path.exists():
        ui.note(f"File: {path}. SK_* variables and parameters take precedence over it.")
    else:
        ui.note("No configuration file: every value is the platform default.")


@config_app.command(
    "get",
    help=(
        "Show the effective value of a key, unformatted (useful in scripts).\n\n"
        "Examples:\n\b\n"
        "  sk config get api.url\n"
        "  sk config get auth.issuer"
    ),
)
def get_command(
    name: Annotated[
        str | None,
        typer.Argument(help="Key, such as auth.issuer or api.url (required)."),
    ] = None,
) -> None:
    key = _key_or_exit(name)
    # Saída de dado para scripts, e não mensagem ao usuário: sem painel nem cor.
    typer.echo(_text(_effective_values()[key.dotted]))


@config_app.command(
    "set",
    help=(
        "Store the value of a key and rewrite the file. Comments written by hand "
        "are not preserved.\n\n"
        "Examples:\n\b\n"
        "  sk config set api.timeoutSeconds 120\n"
        "  sk config set api.url http://gateway.internal:8080"
    ),
)
def set_command(
    name: Annotated[
        str | None,
        typer.Argument(help="Key, such as auth.issuer or api.url (required)."),
    ] = None,
    raw_value: Annotated[
        str | None,
        typer.Argument(help="New value (required). Booleans accept only true or false."),
    ] = None,
) -> None:
    key = _key_or_exit(name)
    value_text = _require_argument(raw_value, "the value")
    path = config_file_path()
    value = _parse_value(key, value_text)

    document = _read_or_exit()
    try:
        sections = store_value(key, value, document, path=path)
    except (ValidationError, ConfigurationError) as error:
        _exit_with(error, "Value refused", "Fix the value and repeat.", EXIT_USAGE_ERROR)
    except OSError as error:
        ui.error("Could not write the configuration", f"{path}: {error.strerror}")
        raise typer.Exit(EXIT_FAILURE) from error

    ui.panel(
        "Configuration updated",
        [("key", key.dotted), ("value", _text(value)), ("file", str(path))],
    )
    section_allows_http = bool(getattr(sections[key.section], "allow_insecure_http", True))
    if isinstance(value, str) and value.startswith("http://") and not section_allows_http:
        ui.warning(
            f"{key.dotted} is HTTP without permission: use will refuse this address until "
            f"`{key.section}.allowInsecureHttp` is true."
        )


@config_app.command(
    "unset",
    help=(
        "Remove a key from the file, so its value goes back to the default. Comments written by "
        "hand are not preserved.\n\n"
        "Examples:\n\b\n"
        "  sk config unset api.timeoutSeconds"
    ),
)
def unset_command(
    name: Annotated[
        str | None,
        typer.Argument(help="Key, such as auth.issuer or api.url (required)."),
    ] = None,
) -> None:
    key = _key_or_exit(name)
    path = config_file_path()
    document = _read_or_exit()
    variable = f"SK_{key.section.upper()}_{key.field_name.upper()}"

    if _stored_value(document, key) is None:
        # Idempotente: já está no padrão, e o arquivo nem é tocado.
        ui.note(f"{key.dotted} is not in the file: it is already at the default.")
    else:
        try:
            remove_value(key, document, path=path)
        except (ValidationError, ConfigurationError) as error:
            _exit_with(error, "Could not update", "Fix the file and repeat.", EXIT_USAGE_ERROR)
        except OSError as error:
            ui.error("Could not write the configuration", f"{path}: {error.strerror}")
            raise typer.Exit(EXIT_FAILURE) from error
        ui.panel("Configuration updated", [("key", key.dotted), ("file", str(path))])
        ui.note(f"{key.dotted} is back to the default.")
    if variable in os.environ:
        ui.warning(f"{variable} is set and still takes precedence over the file and the default.")
