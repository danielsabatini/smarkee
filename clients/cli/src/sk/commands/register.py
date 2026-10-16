"""Comando `sk register`: pede o cadastro de um usuário na plataforma.

É anônimo: não exige login e não envia token. A senha não é pedida nem aceita: ela é definida
pela própria pessoa, na página do provedor de identidade, a partir do e-mail de ativação
(`docs/RESOURCE-CONTROL-LOOP.md`, seção 46.1). O cadastro é assíncrono: o comando confirma que o
pedido foi aceito, e não que a conta já existe.
"""

from typing import Annotated

import typer
from pydantic import ValidationError

from sk import ui
from sk.features.core.user import submit_registration, validate_registration
from sk.help import command, option
from sk.http import ApiError, ApiRejectedError, ApiUnavailableError
from sk.identity.oidc import OidcError
from sk.settings import ConfigurationError, SkSettings

REGISTER_HELP = command(
    "Register a new account to get started on the platform. "
    "Afterwards, confirm the e-mail and set the password with the links sent to it."
)

EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2


def _require(value: str | None, option_name: str) -> str:
    if value is None:
        ui.error(
            "Missing required option",
            f"Provide {option_name}.",
            hint=f"Repeat the command with {option_name} VALUE.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return value


def _load_core(api_url: str | None, allow_insecure_http: bool) -> tuple[str, bool]:
    explicit = {
        key: value
        for key, value in {
            "api_url": api_url,
            "allow_insecure_http": allow_insecure_http or None,
        }.items()
        if value is not None
    }
    try:
        # Mesmo mecanismo do `sk auth`: parâmetro → ambiente → arquivo → default.
        core = SkSettings(core=explicit).core  # pyright: ignore[reportArgumentType]
    except (ValidationError, ConfigurationError) as error:
        ui.error("Invalid configuration", str(error), hint="Fix the indicated file and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    if not core.api_url:
        ui.error(
            "API not provided",
            "Provide it with --api-url, SK_CORE_API_URL or apiUrl in the [core] table.",
            hint="Run `sk init` to create the configuration, or provide --api-url.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return core.api_url, core.allow_insecure_http


def register_command(
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            help=option(
                "Name (up to 256 characters).",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    surname: Annotated[
        str | None,
        typer.Option(
            "--surname",
            help=option(
                "Surname (up to 256 characters).",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    email: Annotated[
        str | None,
        typer.Option(
            "--email",
            help=option(
                "Account e-mail. It is also the login name.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    api_url: Annotated[
        str | None,
        typer.Option(
            "--api-url",
            help=option(
                "Platform API address.",
                kind="String",
                variable="SK_CORE_API_URL",
                file="[core] apiUrl",
                default="none",
            ),
        ),
    ] = None,
    allow_insecure_http: Annotated[
        bool,
        typer.Option(
            "--allow-insecure-http",
            help=option(
                "Allow an address without HTTPS. Development only.",
                kind="Boolean",
                variable="SK_CORE_ALLOW_INSECURE_HTTP=true",
                file="[core] allowInsecureHttp = true",
                default="off",
            ),
        ),
    ] = False,
) -> None:
    # Obrigatórias por validação do próprio comando (não pelo Typer), para não exibir "[required]".
    name = _require(name, "--name")
    surname = _require(surname, "--surname")
    email = _require(email, "--email")
    url, insecure = _load_core(api_url, allow_insecure_http)
    try:
        # Validação local antes de qualquer chamada: o comando, e não só o cliente, a garante.
        validate_registration(name, surname, email)
        accepted = submit_registration(
            url,
            given_name=name,
            family_name=surname,
            email=email,
            allow_insecure_http=insecure,
        )
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix the given value and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    except OidcError as error:
        ui.error(
            "API address refused",
            str(error),
            hint="Use HTTPS, or --allow-insecure-http in development.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    except ApiRejectedError as error:
        if error.status == 429:
            wait = error.retry_after_seconds
            ui.error(
                "Too many requests",
                "Registration has a request limit per origin.",
                hint=f"Wait {wait} seconds and repeat." if wait else "Try again later.",
            )
            raise typer.Exit(EXIT_FAILURE) from error
        if error.field:
            ui.error(
                "Field refused by the API",
                f"{error.field}: {error}",
                hint="Fix the field and repeat.",
            )
            raise typer.Exit(EXIT_USAGE_ERROR if error.status == 400 else EXIT_FAILURE) from error
        ui.error(
            "Request refused by the API",
            str(error),
            hint=f"HTTP {error.status} ({error.error_code}).",
        )
        raise typer.Exit(EXIT_USAGE_ERROR if error.status == 400 else EXIT_FAILURE) from error
    except ApiUnavailableError as error:
        ui.error("Service unavailable", str(error), hint="Try again in a few minutes.")
        raise typer.Exit(EXIT_FAILURE) from error
    except ApiError as error:  # pragma: no cover (nova subclasse sem tratamento explícito)
        ui.error("Registration failed", str(error))
        raise typer.Exit(EXIT_FAILURE) from error

    ui.panel(
        "Registration requested",
        [
            ("name", f"{name.strip()} {surname.strip()}"),
            ("email", email.strip()),
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
    )
    ui.note(
        "Next steps: confirm the e-mail and set the password with the links the provider sent. "
        "Then run `sk auth login`."
    )
