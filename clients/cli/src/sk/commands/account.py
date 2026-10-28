"""Comandos `sk account`: criar, consultar, proteger e excluir a própria conta.

Agem sobre a conta da sessão (`sk auth login`), exceto a criação (anônima). A exclusão é segura
(decisão 0040): a API recusa enquanto houver Organizations ou serviços habilitados da conta, e a
CLI diz o que remover antes. A conta nasce protegida contra exclusão (decisão 0043):
`sk account unprotect` precede o `delete`.
"""

import uuid
from typing import Annotated, NoReturn

import typer

from sk import ui
from sk.command_app import SkTyper
from sk.commands.shared import (
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    EXIT_FAILURE,
    EXIT_USAGE_ERROR,
    PersonNameOption,
    PersonSurnameOption,
    SyncResourceFlow,
    TimeoutOption,
    already_done,
    bad_address,
    fail_api,
    load_api,
    require,
    session_token,
)
from sk.features.core.account import (
    Account,
    delete_account,
    get_account,
    set_account_protection,
    submit_registration,
    token_subject,
    validate_registration,
)
from sk.help import command, option
from sk.http import ApiError, ApiRejectedError, ApiUnavailableError
from sk.identity.credentials import default_credentials_path
from sk.identity.oidc import OidcError

ACCOUNT_HELP = command("Manage your personal account (create, show, protect, delete).")

account_app = SkTyper(
    help=ACCOUNT_HELP,
    no_args_is_help=True,
    # Ajuda colorida pelo Rich. Colchetes literais nos textos são escapados com "\\[".
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)

HTTP_UNAUTHORIZED = 401
HTTP_NOT_FOUND = 404
NOT_FOUND = "Your account was not found."
CONFLICT_ON_CHANGE = "The account changed since it was last read. Inspect it and try again."
ERROR_CODE_HINTS = {
    "DeletionProtected": (
        "The account is protected against deletion. Run `sk account unprotect` first."
    ),
    "ResourcesAttached": (
        "The account still has Organizations or enabled services. Delete the Organizations "
        "(`sk ipm organization delete`), disable the services (`sk sum service disable`) "
        "and repeat."
    ),
    "ResourcesNotVerifiable": (
        "The attached resources could not be verified. "
        "Renew the session with `sk auth refresh` and repeat."
    ),
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
        ("protected", "yes" if account.deletion_protection else "no"),
    ]


@account_app.command(
    "get",
    structured=True,
    help=command(
        "Show the account of the current session.",
        examples=["sk account get", "sk --output json account get"],
    ),
)
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
    ui.panel("Account", _rows(account), data=account)


def _get_command(_resource_id: str) -> str:
    return "sk account get"


_flow = SyncResourceFlow(
    subject="account",
    get_command=_get_command,
    read_resource=get_account,
    fail_api=_fail_api,
    rows=_rows,
)


def _read_until_gone(
    api_url: str, *, token: str, resource_id: str, allow_insecure_http: bool
) -> Account:
    """Leitura da espera da exclusão: o `401` também diz que a conta saiu.

    Quando o usuário é removido do provedor, o token da sessão deixa de valer: o fim da exclusão
    pode aparecer como a recusa do próprio token. Vira o `404` que o acompanhamento espera.
    """
    try:
        return get_account(
            api_url, token=token, resource_id=resource_id, allow_insecure_http=allow_insecure_http
        )
    except ApiRejectedError as error:
        if error.status == HTTP_UNAUTHORIZED:
            raise ApiRejectedError(
                HTTP_NOT_FOUND, "account removed", error_code=error.error_code
            ) from error
        raise


_deletion_flow = SyncResourceFlow(
    subject="account",
    get_command=_get_command,
    read_resource=_read_until_gone,
    fail_api=_fail_api,
    rows=_rows,
    removed_key="session",
)


def _set_protection(*, protected: bool, wait: bool, timeout: int) -> None:
    url, insecure = load_api()
    token = session_token()
    resource_id = _own_id(token)
    try:
        account = get_account(
            url, token=token, resource_id=resource_id, allow_insecure_http=insecure
        )
        if account.deletion_protection == protected:
            # Idempotente: pedir o estado que já vale não é erro.
            state = "protected" if protected else "unprotected"
            already_done(account, f"The account is already {state}. Nothing to do.")
            return
        changed = set_account_protection(
            url,
            token=token,
            resource_id=resource_id,
            resource_version=account.resource_version,
            protected=protected,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _flow.requested_panel("Protection change requested", changed, wait=wait)
    _flow.finish(
        url,
        insecure,
        changed,
        title="Account protected" if protected else "Account unprotected",
        removal=False,
        wait=wait,
        timeout=timeout,
    )


WaitOption = Annotated[
    bool,
    typer.Option(
        "--wait",
        help=option(
            "Wait for the change to complete.",
            kind="Boolean",
            variable=None,
            file=None,
            default="off",
        ),
    ),
]


@account_app.command(
    "protect",
    structured=True,
    help=command(
        "Protect your account against deletion (the default).",
        examples=["sk account protect", "sk account protect --wait"],
    ),
)
def protect_command(
    wait: WaitOption = False, timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS
) -> None:
    _set_protection(protected=True, wait=wait, timeout=timeout)


@account_app.command(
    "unprotect",
    structured=True,
    help=command(
        "Allow your account to be deleted. Required before `delete`.",
        examples=["sk account unprotect", "sk account unprotect --wait"],
    ),
)
def unprotect_command(
    wait: WaitOption = False, timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS
) -> None:
    _set_protection(protected=False, wait=wait, timeout=timeout)


@account_app.command(
    "delete",
    structured=True,
    help=command(
        "Delete your own account. It is refused while Organizations or enabled services remain.",
        examples=["sk account delete --yes", "sk account delete --yes --wait"],
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
        deleted = delete_account(
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
    _deletion_flow.requested_panel(
        "Deletion requested", deleted, ("email", account.email), wait=wait
    )
    if (
        _deletion_flow.finish(
            url,
            insecure,
            deleted,
            title="Account deleted",
            removal=True,
            wait=wait,
            timeout=timeout,
        )
        is None
        and wait
    ):
        default_credentials_path().unlink(missing_ok=True)  # a sessão não vale mais


@account_app.command(
    "create",
    structured=True,
    help=command(
        "Register a new account to get started on the platform. "
        "Afterwards, open the link in the e-mail sent to it to confirm the address and set the "
        "password."
    ),
)
def create_account(
    name: PersonNameOption = None,
    surname: PersonSurnameOption = None,
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
        ],
        data=accepted,
    )
    ui.note(
        "Next steps: open the link in the e-mail the provider sent to confirm the address and set "
        "the password. "
        "Then run `sk auth login`."
    )
