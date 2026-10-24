"""Partes comuns dos comandos que falam com a API da plataforma (`sum`, `ipm` e `register`).

Reúnem o que os comandos repetiriam: as opções `--wait` e
`--timeout`, a leitura da configuração da API, o token da sessão e a tradução das falhas da API em
mensagens para a pessoa. O texto de cada comando (o que é "recurso", o que um `404` significa) fica
no próprio comando.
"""

from collections.abc import Mapping
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from sk import ui
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


def load_api() -> tuple[str, bool]:
    """Endereço da API e permissão de HTTP: ambiente → arquivo → padrão de produção.

    Sem opção de linha de comando (decisão 0041): `SK_API_URL` e `SK_API_ALLOW_INSECURE_HTTP`, ou
    `[api]` no arquivo de configuração.
    """
    try:
        api = SkSettings().api
    except (ValidationError, ConfigurationError) as error:
        ui.error("Invalid configuration", str(error), hint="Fix the indicated file and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    return api.url, api.allow_insecure_http


def session_insecure() -> bool:
    """HTTP sem TLS no provedor de identidade: seção `[auth]` (ambiente ou arquivo)."""
    return SkSettings().auth.allow_insecure_http


def session_token() -> str:
    """Access token da sessão, renovado pelo refresh token quando está para vencer."""
    try:
        return current_access_token(
            default_credentials_path(), allow_insecure_http=session_insecure()
        )
    except SessionError as error:
        ui.error("Session unavailable", str(error), hint="Run `sk auth login`.")
        raise typer.Exit(EXIT_FAILURE) from error


def renew_after_convergence() -> bool:
    """Renova a sessão para o token refletir as permissões novas; falha vira aviso."""
    try:
        renew_session(default_credentials_path(), allow_insecure_http=session_insecure())
    except SessionError as error:
        ui.warning(
            f"Session not renewed ({error}). The token may not reflect the new permissions: "
            "run `sk auth login`."
        )
        return False
    return True


def bad_address(error: OidcError) -> NoReturn:
    ui.error(
        "API address refused",
        str(error),
        hint="Use HTTPS, or set SK_API_ALLOW_INSECURE_HTTP=true in development.",
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
    significam no comando; `by_error_code` dá a mensagem de um `errorCode` específico da API.

    Quando a CLI tem a própria mensagem (código conhecido ou `401`, `403`, `404`, `409`), mostra só
    ela, em inglês (decisão 0035). O texto do servidor (pt-BR) só aparece sem mensagem própria."""
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
    message = (by_error_code or {}).get(error.error_code) or hints.get(error.status)
    if message is not None:
        ui.error("Request refused by the API", message)
    else:
        detail = f"{error.field}: {error}" if error.field else str(error)
        ui.error(
            "Request refused by the API", detail, hint=f"HTTP {error.status} ({error.error_code})."
        )
    raise typer.Exit(EXIT_USAGE_ERROR if error.status == 400 else EXIT_FAILURE) from error
