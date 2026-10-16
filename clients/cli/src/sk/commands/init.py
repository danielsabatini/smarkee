"""Comando `sk init`: cria o arquivo de configuração com os endereços de produção.

O arquivo passa a ser o ponto de partida da CLI. Depois, `sk config` altera valores. Parâmetros
e variáveis `SK_*` sobrescrevem o que for gravado, na ordem da decisão 0008; o padrão é o de
produção (`sk.defaults`).
"""

from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from sk import ui
from sk.defaults import PRD_API_URL, PRD_ISSUER, PROVISIONAL_CLIENT_ID
from sk.files import write_private_file
from sk.help import ORDER_WITHOUT_FILE, command, option
from sk.identity.oidc import OidcError, ensure_secure_url
from sk.settings import (
    AuthSettings,
    ConfigurationError,
    CoreSettings,
    SkSettingsWithoutConfigFile,
    config_file_path,
    render_section,
)

EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2

INIT_HELP = command(
    "Create the platform configuration file, with the production addresses. "
    "It does not overwrite an existing file without --force.",
    order=ORDER_WITHOUT_FILE,
)


def _help_issuer() -> str:
    return option(
        "Login provider address.",
        kind="String",
        variable="SK_AUTH_ISSUER",
        file=None,
        default=PRD_ISSUER,
    )


def _help_client_id() -> str:
    return option(
        "Identifier of sk at the login provider. Provisional until production exists.",
        kind="String",
        variable="SK_AUTH_CLIENT_ID",
        file=None,
        default=PROVISIONAL_CLIENT_ID,
    )


def _help_api_url() -> str:
    return option(
        "Platform API address.",
        kind="String",
        variable="SK_CORE_API_URL",
        file=None,
        default=PRD_API_URL,
    )


def _help_allow_insecure_http() -> str:
    return option(
        "Allow an address without HTTPS. Development only.",
        kind="Boolean",
        variable="SK_AUTH_ALLOW_INSECURE_HTTP=true",
        file=None,
        default="off",
    )


def _exit_on_configuration_error(error: Exception) -> NoReturn:
    ui.error("Invalid configuration", str(error), hint="Fix the given value and repeat.")
    raise typer.Exit(EXIT_USAGE_ERROR) from error


def init_command(
    issuer: Annotated[str | None, typer.Option(help=_help_issuer())] = None,
    client_id: Annotated[str | None, typer.Option(help=_help_client_id())] = None,
    api_url: Annotated[str | None, typer.Option(help=_help_api_url())] = None,
    allow_insecure_http: Annotated[
        bool,
        typer.Option("--allow-insecure-http", help=_help_allow_insecure_http()),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help=option(
                "Overwrite the existing configuration.",
                kind="Boolean",
                variable=None,
                file=None,
                default="off",
            ),
        ),
    ] = False,
) -> None:
    path = config_file_path()
    if path.exists() and not force:
        ui.error(
            "Configuration already exists",
            f"The file {path} was not changed.",
            hint="Use --force to overwrite it.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)

    # Um parâmetro de HTTP vale para as duas seções; sem ele, cada seção usa o seu valor.
    explicit_auth = _explicit({"issuer": issuer, "client_id": client_id}, allow_insecure_http)
    explicit_core = _explicit({"api_url": api_url}, allow_insecure_http)
    try:
        settings = SkSettingsWithoutConfigFile(
            auth=explicit_auth,  # pyright: ignore[reportArgumentType]
            core=explicit_core,  # pyright: ignore[reportArgumentType]
        )
    except (ValidationError, ConfigurationError) as error:
        _exit_on_configuration_error(error)

    auth = AuthSettings(
        issuer=settings.auth.issuer or PRD_ISSUER,
        client_id=settings.auth.client_id or PROVISIONAL_CLIENT_ID,
        allow_insecure_http=settings.auth.allow_insecure_http,
    )
    core = CoreSettings(
        api_url=settings.core.api_url or PRD_API_URL,
        allow_insecure_http=settings.core.allow_insecure_http,
    )

    try:
        ensure_secure_url(auth.issuer or "", allow_insecure_http=auth.allow_insecure_http)
        ensure_secure_url(core.api_url or "", allow_insecure_http=core.allow_insecure_http)
    except OidcError as error:
        ui.error(
            "Address refused",
            str(error),
            hint="Use HTTPS, or --allow-insecure-http in development.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR) from error

    content = render_section("auth", auth) + "\n" + render_section("core", core)
    try:
        write_private_file(path, content)
    except OSError as error:
        ui.error("Could not write the configuration", f"{path}: {error.strerror}")
        raise typer.Exit(EXIT_FAILURE) from error

    ui.panel(
        "Configuration written",
        [
            ("file", str(path)),
            ("issuer", auth.issuer or ""),
            ("apiUrl", core.api_url or ""),
            ("clientId", auth.client_id or ""),
        ],
    )
    if auth.client_id == PROVISIONAL_CLIENT_ID:
        ui.warning(
            "The production client ID is not defined yet: production login does not work "
            "until it is provided with --client-id or `sk config set auth.clientId`."
        )
    ui.note("Next step: `sk auth login`.")


def _explicit(values: dict[str, object], allow_insecure_http: bool) -> dict[str, object]:
    """Só os valores informados: parâmetro não informado (None ou False) não é repassado."""
    if allow_insecure_http:
        values["allow_insecure_http"] = True
    return {key: value for key, value in values.items() if value is not None}
