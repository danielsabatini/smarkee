"""Comandos `sk register`: o cadastro, e a consulta e a exclusão da própria conta.

O cadastro (`sk register --name ...`) é anônimo: não exige login e não envia token. A senha não é
pedida nem aceita: ela é definida
pela própria pessoa, na página do provedor de identidade, a partir do e-mail de ativação
(`docs/RESOURCE-CONTROL-LOOP.md`, seção 46.1). O cadastro é assíncrono: o comando confirma que o
pedido foi aceito, e não que a conta já existe.

`get` e `delete` agem sobre a conta da sessão (`sk auth login`). A exclusão é segura (decisão 0040):
a API recusa enquanto houver Organizations ou serviços habilitados da conta, e a CLI diz o que
remover antes.
"""

import time
import uuid
from typing import Annotated, NoReturn

import typer

from sk import ui
from sk.commands.shared import (
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    EXIT_FAILURE,
    EXIT_USAGE_ERROR,
    HTTP_NOT_FOUND,
    WAIT_POLL_SECONDS,
    TimeoutOption,
    bad_address,
    fail_api,
    load_api,
    require,
    session_token,
)
from sk.features.core.user import (
    UserAccount,
    delete_user,
    get_operation,
    get_user,
    submit_registration,
    token_subject,
    validate_registration,
)
from sk.help import command, option
from sk.http import ApiError, ApiRejectedError, ApiUnavailableError
from sk.identity.credentials import default_credentials_path
from sk.identity.oidc import OidcError

REGISTER_HELP = command(
    "Register a new account to get started on the platform. "
    "Afterwards, open the link in the e-mail sent to it to confirm the address and set the "
    "password."
)


register_app = typer.Typer(
    help=REGISTER_HELP,
    invoke_without_command=True,
    # Ajuda colorida pelo Rich. Colchetes literais nos textos são escapados com "\\[".
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)

NOT_FOUND = "Your account was not found."
CONFLICT_ON_CHANGE = "The account changed since it was last read. Inspect it and try again."
ERROR_CODE_HINTS = {
    "ResourcesAttached": (
        "Remove them first (`sk ipm organization delete`, `sk sum service disable`) and repeat."
    ),
    "ResourcesNotVerifiable": "Renew the session with `sk auth refresh` and repeat.",
}


@register_app.callback(invoke_without_command=True)
def register_command(
    context: typer.Context,
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
) -> None:
    if context.invoked_subcommand is not None:
        return  # `get` ou `delete`: o cadastro só roda sem subcomando
    # Obrigatórias por validação do próprio comando (não pelo Typer), para não exibir "[required]".
    name = require(name, "--name")
    surname = require(surname, "--surname")
    email = require(email, "--email")
    url, insecure = load_api()
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
            hint="Use HTTPS, or set SK_API_ALLOW_INSECURE_HTTP=true in development.",
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
        "Next steps: open the link in the e-mail the provider sent to confirm the address and set "
        "the password. "
        "Then run `sk auth login`."
    )


def _own_id(token: str) -> str:
    try:
        return token_subject(token)
    except ValueError as error:
        ui.error("Session unavailable", str(error), hint="Run `sk auth login`.")
        raise typer.Exit(EXIT_FAILURE) from error


def _fail_api(error: ApiError) -> NoReturn:
    fail_api(
        error, not_found=NOT_FOUND, conflict=CONFLICT_ON_CHANGE, by_error_code=ERROR_CODE_HINTS
    )


def _rows(account: UserAccount) -> list[tuple[str, str]]:
    return [
        ("resourceId", account.resource_id),
        ("name", f"{account.given_name} {account.family_name}"),
        ("email", account.email),
        ("phase", account.phase),
        ("platformAccess", account.platform_access),
    ]


@register_app.command("get", help=command("Show the account of the current session."))
def get_command() -> None:
    url, insecure = load_api()
    token = session_token()
    try:
        account = get_user(
            url, token=token, resource_id=_own_id(token), allow_insecure_http=insecure
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    ui.panel("Account", _rows(account))


def _wait_until_gone(
    url: str, insecure: bool, resource_id: str, operation_id: str, *, timeout: int
) -> None:
    """Espera a exclusão terminar: Operation `completed`, ou a conta sumir (`401` ou `404`).

    Quando o usuário é removido do provedor, o token da sessão deixa de valer: o fim da exclusão
    pode aparecer como a recusa do próprio token.
    """
    ui.note(f"Waiting for the deletion (up to {timeout} s)...")
    deadline = time.monotonic() + timeout
    while True:
        try:
            operation = get_operation(
                url,
                token=session_token(),
                resource_id=resource_id,
                operation_id=operation_id,
                allow_insecure_http=insecure,
            )
        except OidcError as error:
            bad_address(error)
        except ApiRejectedError as error:
            if error.status == 401:
                return  # o token deixou de valer: a conta foi removida do provedor
            if error.status != HTTP_NOT_FOUND:
                _fail_api(error)
        except ApiError as error:
            _fail_api(error)
        else:
            if operation.operation_status in ("rejected", "failed"):
                ui.error(
                    "Request not completed",
                    f"The Operation ended as {operation.operation_status}.",
                    hint="Inspect your account with `sk register get`.",
                )
                raise typer.Exit(EXIT_FAILURE)
            if operation.operation_status == "completed":
                return
        if time.monotonic() >= deadline:
            ui.error(
                "Timed out",
                f"{timeout} s passed and the deletion is still in progress.",
                hint="Check it with `sk register get`.",
            )
            raise typer.Exit(EXIT_FAILURE)
        time.sleep(WAIT_POLL_SECONDS)


@register_app.command(
    "delete",
    help=command(
        "Delete your own account. It is refused while Organizations or enabled services remain."
    ),
)
def delete_command(
    yes: Annotated[
        bool,
        typer.Option(
            "--yes",
            help=option(
                "Confirm that the account is deleted for good.",
                kind="Boolean",
                variable=None,
                file=None,
                default="off",
            ),
        ),
    ] = False,
    wait: Annotated[
        bool,
        typer.Option(
            "--wait",
            help=option(
                "Wait for the deletion to finish and forget the local session.",
                kind="Boolean",
                variable=None,
                file=None,
                default="off",
            ),
        ),
    ] = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    if not yes:
        ui.error(
            "Confirmation required",
            "Deleting the account cannot be undone.",
            hint="Repeat the command with --yes.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    url, insecure = load_api()
    token = session_token()
    resource_id = _own_id(token)
    try:
        account = get_user(url, token=token, resource_id=resource_id, allow_insecure_http=insecure)
        accepted = delete_user(
            url,
            token=token,
            resource_id=resource_id,
            resource_version=account.resource_version,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    ui.panel(
        "Deletion requested",
        [
            ("email", account.email),
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
    )
    if not wait:
        ui.note("The account is removed shortly. Confirm it with `sk register get`.")
        return
    _wait_until_gone(url, insecure, resource_id, accepted.operation_id, timeout=timeout)
    default_credentials_path().unlink(missing_ok=True)  # a sessão não vale mais
    ui.panel("Account deleted", [("resourceId", resource_id), ("session", "forgotten")])
