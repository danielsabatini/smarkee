"""Comandos `sk account`: consultar e excluir a própria conta.

Agem sobre a conta da sessão (`sk auth login`). A exclusão é segura (decisão 0040): a API recusa
enquanto houver Organizations ou serviços habilitados da conta, e a CLI diz o que remover antes.
O cadastro é `sk register`.
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
    session_token,
)
from sk.features.core.account import (
    Account,
    delete_account,
    get_account,
    get_operation,
    token_subject,
)
from sk.help import command, option
from sk.http import ApiError, ApiRejectedError
from sk.identity.credentials import default_credentials_path
from sk.identity.oidc import OidcError

ACCOUNT_HELP = command("Show or delete your own account.")

account_app = typer.Typer(
    help=ACCOUNT_HELP,
    no_args_is_help=True,
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


def _rows(account: Account) -> list[tuple[str, str]]:
    return [
        ("resourceId", account.resource_id),
        ("name", f"{account.given_name} {account.family_name}"),
        ("email", account.email),
        ("phase", account.phase),
        ("platformAccess", account.platform_access),
    ]


@account_app.command("get", help=command("Show the account of the current session."))
def get_command() -> None:
    url, insecure = load_api()
    token = session_token()
    try:
        account = get_account(
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
                    hint="Inspect your account with `sk account get`.",
                )
                raise typer.Exit(EXIT_FAILURE)
            if operation.operation_status == "completed":
                return
        if time.monotonic() >= deadline:
            ui.error(
                "Timed out",
                f"{timeout} s passed and the deletion is still in progress.",
                hint="Check it with `sk account get`.",
            )
            raise typer.Exit(EXIT_FAILURE)
        time.sleep(WAIT_POLL_SECONDS)


@account_app.command(
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
        account = get_account(
            url, token=token, resource_id=resource_id, allow_insecure_http=insecure
        )
        accepted = delete_account(
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
        ui.note("The account is removed shortly. Confirm it with `sk account get`.")
        return
    _wait_until_gone(url, insecure, resource_id, accepted.operation_id, timeout=timeout)
    default_credentials_path().unlink(missing_ok=True)  # a sessão não vale mais
    ui.panel("Account deleted", [("resourceId", resource_id), ("session", "forgotten")])
