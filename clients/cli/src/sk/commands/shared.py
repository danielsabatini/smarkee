"""Partes comuns dos comandos que falam com a API da plataforma (`sum`, `ipm` e `register`).

Reúnem o que os comandos repetiriam: as opções `--api-url`, `--allow-insecure-http`, `--wait` e
`--timeout`, a leitura da configuração da API, o token da sessão e a tradução das falhas da API em
mensagens para a pessoa. O texto de cada comando (o que é "recurso", o que um `404` significa) fica
no próprio comando.
"""

from collections.abc import Mapping
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from sk import ui
from sk.defaults import PRD_API_URL
from sk.help import option
from sk.http import ApiError, ApiRejectedError, ApiUnavailableError
from sk.identity.credentials import default_credentials_path
from sk.identity.oidc import OidcError
from sk.identity.session import SessionError, current_access_token, renew_session
from sk.settings import ConfigurationError, SkSettings

EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2

HTTP_NOT_FOUND = 404
DEFAULT_WAIT_TIMEOUT_SECONDS = 60
WAIT_POLL_SECONDS = 1.0

ApiUrlOption = Annotated[
    str | None,
    typer.Option(
        "--api-url",
        help=option(
            "Platform API address.",
            kind="String",
            variable="SK_API_URL",
            file="[api] url",
            default=PRD_API_URL,
        ),
    ),
]
AllowInsecureHttpOption = Annotated[
    bool,
    typer.Option(
        "--allow-insecure-http",
        help=option(
            "Allow an address without HTTPS. Development only.",
            kind="Boolean",
            variable="SK_API_ALLOW_INSECURE_HTTP=true",
            file="[api] allowInsecureHttp = true",
            default="off",
        ),
    ),
]
TimeoutOption = Annotated[
    int,
    typer.Option(
        "--timeout",
        min=1,
        help=option(
            "Seconds to wait with --wait.",
            kind="Integer",
            variable=None,
            file=None,
            default="60",
        ),
    ),
]


def require(value: str | None, option_name: str) -> str:
    """Opção obrigatória, validada pelo próprio comando (e não pelo Typer, que mostraria
    "[required]" na ajuda)."""
    if value is None:
        ui.error(
            "Missing required option",
            f"Provide {option_name}.",
            hint=f"Repeat the command with {option_name} VALUE.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return value


def load_api(api_url: str | None, allow_insecure_http: bool) -> tuple[str, bool]:
    """Endereço da API e permissão de HTTP: parâmetro → ambiente → arquivo → default."""
    explicit = {
        key: value
        for key, value in {
            "url": api_url,
            "allow_insecure_http": allow_insecure_http or None,
        }.items()
        if value is not None
    }
    try:
        api = SkSettings(api=explicit).api  # pyright: ignore[reportArgumentType]
    except (ValidationError, ConfigurationError) as error:
        ui.error("Invalid configuration", str(error), hint="Fix the indicated file and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    return api.url, api.allow_insecure_http


def session_insecure(allow_insecure_http: bool) -> bool:
    """O provedor de identidade segue a permissão de HTTP da seção `[auth]`, além da opção."""
    return allow_insecure_http or SkSettings().auth.allow_insecure_http


def session_token(allow_insecure_http: bool) -> str:
    """Access token da sessão, renovado pelo refresh token quando está para vencer."""
    try:
        return current_access_token(
            default_credentials_path(), allow_insecure_http=session_insecure(allow_insecure_http)
        )
    except SessionError as error:
        ui.error("Session unavailable", str(error), hint="Run `sk auth login`.")
        raise typer.Exit(EXIT_FAILURE) from error


def renew_after_convergence(insecure: bool) -> bool:
    """Renova a sessão para o token refletir as roles novas. Falha vira aviso: o pedido já valeu."""
    try:
        renew_session(default_credentials_path(), allow_insecure_http=session_insecure(insecure))
    except SessionError as error:
        ui.warning(
            f"Session not renewed ({error}). The token may not reflect the new roles: "
            "run `sk auth login`."
        )
        return False
    return True


def bad_address(error: OidcError) -> NoReturn:
    ui.error(
        "API address refused",
        str(error),
        hint="Use HTTPS, or --allow-insecure-http in development.",
    )
    raise typer.Exit(EXIT_USAGE_ERROR) from error


def fail_api(
    error: ApiError,
    *,
    not_found: str,
    conflict: str,
    by_error_code: Mapping[str, str] | None = None,
) -> NoReturn:
    """Mostra a falha da API e sai. `not_found` e `conflict` dizem o que o `404` e o `409`
    significam no comando; `by_error_code` dá a dica de um `errorCode` específico da API."""
    if isinstance(error, ApiUnavailableError):
        ui.error("Service unavailable", str(error), hint="Try again in a few minutes.")
        raise typer.Exit(EXIT_FAILURE) from error
    if not isinstance(error, ApiRejectedError):  # pragma: no cover (subclasse sem tratamento)
        ui.error("API call failed", str(error))
        raise typer.Exit(EXIT_FAILURE) from error
    if error.status == 429:
        wait = error.retry_after_seconds
        ui.error(
            "Too many requests",
            str(error),
            hint=f"Wait {wait} seconds and repeat." if wait else "Wait and try again.",
        )
        raise typer.Exit(EXIT_FAILURE) from error
    hints = {
        401: "The session was not accepted. Run `sk auth login`.",
        403: "Your account does not have permission for this operation.",
        404: not_found,
        409: conflict,
    }
    hint = (by_error_code or {}).get(error.error_code) or hints.get(
        error.status, f"HTTP {error.status} ({error.error_code})."
    )
    detail = f"{error.field}: {error}" if error.field else str(error)
    ui.error("Request refused by the API", detail, hint=hint)
    raise typer.Exit(EXIT_USAGE_ERROR if error.status == 400 else EXIT_FAILURE) from error
