"""Comandos `sk ipm user`: usuários da Organization (decisão 0077).

O dono da Organization (o root) e os usuários dela com as permissões `ipm.user.*` criam, consultam,
alteram as permissões, protegem e removem usuários da Organization. Cada usuário nasce sem senha: a
pessoa define a senha pelo e-mail de ativação e entra com `sk auth login`. A Organization é a de
`--organization-id` ou, na falta dela, a ativa (`sk config set ipm.organizationId`). Criar, alterar
e remover são assíncronos: com `--wait`, o comando espera o usuário convergir.
"""

import time
import uuid
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError
from rich.text import Text

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
from sk.features.api_contract import OperationStatus, RequestAccepted, validate_identifier
from sk.features.core.account import validate_registration
from sk.features.ipm.user import (
    User,
    create_user,
    delete_user,
    get_operation,
    get_user,
    list_users,
    update_user,
    validate_permissions,
)
from sk.help import command, option
from sk.http import ApiError, ApiRejectedError
from sk.identity.oidc import OidcError
from sk.settings import ConfigurationError, SkSettings

ACTIVE_ORGANIZATION_KEY = "ipm.organizationId"

USER_HELP = command(
    "Create, inspect, change the permissions of, protect and delete the users of an Organization."
)

NOT_FOUND = "User not found in an Organization you act on."
CONFLICT_ON_CHANGE = "The user changed since it was last read. Inspect it and try again."
PROTECTED_HINT = "The user is protected against deletion. Run `sk ipm user unprotect` first."
REJECTION_HINTS = {
    "validation": (
        "The e-mail is already in use in the Organization, or a permission is not allowed."
    ),
    "conflict": CONFLICT_ON_CHANGE,
    "not_found": NOT_FOUND,
    "protected": PROTECTED_HINT,
}
ERROR_CODE_HINTS = {
    "DeletionProtected": PROTECTED_HINT,
    "QuotaExceeded": "The Organization reached its user limit. Delete a user or ask an operator.",
    "OrganizationUnavailable": "The Organization could not be checked now. Try again.",
}
NO_PERMISSION_HINT = (
    "You do not have permission for this operation. Without ipm.user.bind, you can only give or "
    "take permissions you have yourself."
)
PERMISSIONS_HINT = (
    "A permission is not allowed for the Organization. Use only the permissions of its grant."
)

PHASE_STYLES = {"Ready": "green", "Failed": "red"}  # as demais (em andamento) ficam em amarelo

user_app = typer.Typer(
    help=USER_HELP,
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)

WaitOption = Annotated[
    bool,
    typer.Option(
        "--wait",
        help=option(
            "Wait for the user to converge (phase Ready and Operation completed).",
            kind="Boolean",
            variable=None,
            file=None,
            default="off",
        ),
    ),
]
UserIdOption = Annotated[
    str | None,
    typer.Option(
        "--resource-id",
        help=option(
            "resourceId of the user (returned by `create` or `list`).",
            kind="String",
            variable=None,
            file=None,
            default="none",
        ),
    ),
]
OrganizationOption = Annotated[
    str | None,
    typer.Option(
        "--organization-id",
        help=option(
            "resourceId of the Organization. Without it, the active Organization is used "
            "(`sk config set ipm.organizationId`).",
            kind="String",
            variable=None,
            file=None,
            default="the active Organization",
        ),
    ),
]
PermissionOption = Annotated[
    list[str] | None,
    typer.Option(
        "--permission",
        help=option(
            "Platform permission of the user, for example ipm.user.get. Repeat it for more "
            "permissions.",
            kind="String",
            variable=None,
            file=None,
            default="no permissions",
        ),
    ),
]


def _fail_api(error: ApiError, *, not_found: str = NOT_FOUND) -> NoReturn:
    by_code = dict(ERROR_CODE_HINTS)
    if isinstance(error, ApiRejectedError):
        if error.status == 403:
            by_code["Forbidden"] = NO_PERMISSION_HINT
        if error.status == 400 and error.field == "permissions":
            by_code[error.error_code] = PERMISSIONS_HINT
    fail_api(error, not_found=not_found, conflict=CONFLICT_ON_CHANGE, by_error_code=by_code)


def _usage_error(message: str, option_name: str) -> NoReturn:
    ui.error("Value not accepted", message, hint=f"Fix {option_name} and repeat.")
    raise typer.Exit(EXIT_USAGE_ERROR)


def _identifier(value: str | None, option_name: str, *, what: str) -> str:
    try:
        return validate_identifier(require(value, option_name), what=what)
    except ValueError as error:
        _usage_error(str(error), option_name)


def _permissions(values: list[str] | None) -> list[str]:
    try:
        return validate_permissions(values or [])
    except ValueError as error:
        _usage_error(str(error), "--permission")


def _organization(value: str | None) -> str:
    """`--organization-id` ou, na falta dele, a Organization ativa."""
    if value is None:
        try:
            value = SkSettings().ipm.organization_id
        except (ValidationError, ConfigurationError) as error:
            ui.error("Invalid configuration", str(error), hint="Fix the indicated file and repeat.")
            raise typer.Exit(EXIT_USAGE_ERROR) from error
        if not value:
            ui.error(
                "Missing Organization",
                "No --organization-id was given and no Organization is active.",
                hint=(
                    "Repeat with --organization-id VALUE, or make one active with "
                    f"`sk config set {ACTIVE_ORGANIZATION_KEY} VALUE`."
                ),
            )
            raise typer.Exit(EXIT_USAGE_ERROR)
    return _identifier(value, "--organization-id", what="organizationId")


def _styled_phase(user: User) -> Text:
    return Text(user.phase, style=PHASE_STYLES.get(user.phase, "yellow"))


def _rows(user: User) -> list[tuple[str, str]]:
    return [
        ("resourceId", user.resource_id),
        ("organizationId", user.organization_id),
        ("email", user.email or "-"),
        ("state", user.user_state or "unknown"),
        ("phase", user.phase),
        ("permissions", ", ".join(user.permissions) or "-"),
        ("protected", "yes" if user.deletion_protection else "no"),
    ]


def _get_command(accepted: RequestAccepted, *, with_operation: bool = False) -> str:
    parts = ["sk ipm user get", f"--resource-id {accepted.resource_id}"]
    if with_operation:
        parts.append(f"--operation-id {accepted.operation_id}")
    return " ".join(parts)


def _timed_out(timeout: int, accepted: RequestAccepted, state: str) -> NoReturn:
    ui.error(
        "Timed out",
        f"{timeout} s passed and the user {state}.",
        hint=f"The request is still in progress: `{_get_command(accepted)}`.",
    )
    raise typer.Exit(EXIT_FAILURE)


def _wait_for_convergence(
    url: str, insecure: bool, accepted: RequestAccepted, *, removal: bool, timeout: int
) -> User | None:
    """Espera a Operation `completed` (e o usuário `Ready`); na remoção, devolve `None`.

    O token é pedido a cada leitura: uma espera longa pode atravessar o vencimento do acesso.
    """
    ui.note(f"Waiting for convergence (up to {timeout} s)...")
    deadline = time.monotonic() + timeout
    while True:
        token = session_token()
        user: User | None = None
        try:
            operation = get_operation(
                url,
                token=token,
                resource_id=accepted.resource_id,
                operation_id=accepted.operation_id,
                allow_insecure_http=insecure,
            )
            # Recusa ou falha primeiro: num `create` recusado, o recurso nem existe (`404`).
            if operation.operation_status in ("rejected", "failed"):
                reason = operation.reason
                ui.error(
                    "Request not completed",
                    f"The Operation ended as {operation.operation_status}"
                    + (f": {reason}" if reason else "."),
                    hint=f"{REJECTION_HINTS.get(reason or '', 'Inspect the request.')} Details: "
                    f"`{_get_command(accepted, with_operation=True)}`.",
                )
                raise typer.Exit(EXIT_FAILURE)
            try:
                user = get_user(
                    url, token=token, resource_id=accepted.resource_id, allow_insecure_http=insecure
                )
            except ApiRejectedError as error:
                if not (removal and error.status == HTTP_NOT_FOUND):
                    raise
        except OidcError as error:
            bad_address(error)
        except ApiRejectedError as error:
            if error.status != HTTP_NOT_FOUND:
                _fail_api(error)
            # Logo depois do `202`, o Manager ainda pode não ter gravado a Operation: é espera.
            if time.monotonic() >= deadline:
                _timed_out(timeout, accepted, "is not visible yet")
            time.sleep(WAIT_POLL_SECONDS)
            continue
        except ApiError as error:
            _fail_api(error)
        if operation.operation_status == "completed":
            if removal and user is None:
                return None
            if not removal and user is not None and user.phase == "Ready":
                return user
        if time.monotonic() >= deadline:
            where = f"is in phase {user.phase}" if user is not None else "was removed"
            _timed_out(timeout, accepted, f"{where} (Operation {operation.operation_status})")
        time.sleep(WAIT_POLL_SECONDS)


def _finish_request(
    url: str,
    insecure: bool,
    accepted: RequestAccepted,
    *,
    title: str,
    removal: bool,
    wait: bool,
    timeout: int,
) -> None:
    if not wait:
        ui.note(f"Follow it with `{_get_command(accepted)}`.")
        return
    user = _wait_for_convergence(url, insecure, accepted, removal=removal, timeout=timeout)
    if user is None:
        ui.panel(title, [("resourceId", accepted.resource_id), ("state", "removed")])
        return
    ui.panel(title, _rows(user))


def _accepted_panel(title: str, accepted: RequestAccepted, *extra: tuple[str, str]) -> None:
    ui.panel(
        title,
        [*extra, ("resourceId", accepted.resource_id), ("operationId", accepted.operation_id)],
    )


@user_app.command(
    "create",
    help=command(
        "Create a user in the Organization, without a password: the person opens the link in the "
        "activation e-mail to set it, then runs `sk auth login`."
    ),
)
def create_command(
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
                "User e-mail. It is also the login name in the Organization.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    permission: PermissionOption = None,
    organization_id: OrganizationOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    # Obrigatórias por validação do próprio comando (não pelo Typer), para não exibir "[required]".
    name = require(name, "--name")
    surname = require(surname, "--surname")
    email = require(email, "--email")
    try:
        validate_registration(name, surname, email)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix the given value and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    permissions = _permissions(permission)
    organization = _organization(organization_id)
    url, insecure = load_api()
    token = session_token()
    try:
        accepted = create_user(
            url,
            token=token,
            organization_id=organization,
            given_name=name.strip(),
            family_name=surname.strip(),
            email=email.strip(),
            permissions=permissions,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error, not_found="Organization not found, or you do not act on it.")
    _accepted_panel("Creation requested", accepted, ("organizationId", organization))
    _finish_request(
        url, insecure, accepted, title="User created", removal=False, wait=wait, timeout=timeout
    )


def _change(
    resource_id: str | None,
    *,
    permissions: list[str] | None,
    protected: bool | None,
    title: str,
    wait: bool,
    timeout: int,
) -> None:
    """Lê a versão atual e pede a alteração; pedir o estado que já vale não é erro."""
    user_id = _identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_user(url, token=token, resource_id=user_id, allow_insecure_http=insecure)
        same_permissions = permissions is None or sorted(permissions) == sorted(current.permissions)
        same_protection = protected is None or protected == current.deletion_protection
        if same_permissions and same_protection:
            ui.note(f"User {user_id} already has it. Nothing to do.")
            return
        accepted = update_user(
            url,
            token=token,
            resource_id=user_id,
            resource_version=current.resource_version,
            permissions=None if same_permissions else permissions,
            protected=None if same_protection else protected,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _accepted_panel("Change requested", accepted)
    _finish_request(url, insecure, accepted, title=title, removal=False, wait=wait, timeout=timeout)


@user_app.command(
    "update",
    help=command(
        "Set the permissions of a user: the given --permission values replace the current ones "
        "(--no-permissions removes them all)."
    ),
)
def update_command(
    resource_id: UserIdOption = None,
    permission: PermissionOption = None,
    no_permissions: Annotated[
        bool,
        typer.Option(
            "--no-permissions",
            help=option(
                "Remove every permission of the user.",
                kind="Boolean",
                variable=None,
                file=None,
                default="off",
            ),
        ),
    ] = False,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    if bool(permission) == no_permissions:
        _usage_error(
            "Give at least one --permission, or --no-permissions (not both).", "--permission"
        )
    _change(
        resource_id,
        permissions=[] if no_permissions else _permissions(permission),
        protected=None,
        title="User permissions changed",
        wait=wait,
        timeout=timeout,
    )


@user_app.command("protect", help=command("Protect a user against deletion."))
def protect_command(
    resource_id: UserIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    _change(
        resource_id,
        permissions=None,
        protected=True,
        title="User protected",
        wait=wait,
        timeout=timeout,
    )


@user_app.command(
    "unprotect",
    help=command("Allow a protected user to be deleted (new users are not protected)."),
)
def unprotect_command(
    resource_id: UserIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    _change(
        resource_id,
        permissions=None,
        protected=False,
        title="User unprotected",
        wait=wait,
        timeout=timeout,
    )


@user_app.command(
    "delete",
    help=command("Delete a user of the Organization, reading the current version before asking."),
)
def delete_command(
    resource_id: UserIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    user_id = _identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_user(url, token=token, resource_id=user_id, allow_insecure_http=insecure)
        accepted = delete_user(
            url,
            token=token,
            resource_id=user_id,
            resource_version=current.resource_version,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _accepted_panel("Deletion requested", accepted, ("email", current.email or "-"))
    _finish_request(
        url, insecure, accepted, title="User deleted", removal=True, wait=wait, timeout=timeout
    )


@user_app.command("get", help=command("Show the state of a user and, if given, of an Operation."))
def get_command(
    resource_id: UserIdOption = None,
    operation_id: Annotated[
        str | None,
        typer.Option(
            "--operation-id",
            help=option(
                "operationId of a request, to see why it was rejected or failed (returned by "
                "`create`, `update` or `delete`).",
                kind="String",
                variable=None,
                file=None,
                default="no Operation lookup",
            ),
        ),
    ] = None,
) -> None:
    user_id = _identifier(resource_id, "--resource-id", what="resourceId")
    if operation_id is not None:
        operation_id = _identifier(operation_id, "--operation-id", what="operationId")
    url, insecure = load_api()
    token = session_token()
    operation: OperationStatus | None = None
    try:
        user = get_user(url, token=token, resource_id=user_id, allow_insecure_http=insecure)
        if operation_id is not None:
            operation = get_operation(
                url,
                token=token,
                resource_id=user_id,
                operation_id=operation_id,
                allow_insecure_http=insecure,
            )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    rows = _rows(user)
    if operation is not None:
        rows.append(("operationStatus", operation.operation_status))
        if operation.reason is not None:
            rows.append(("reason", operation.reason))
    ui.panel("User", rows)


@user_app.command("list", help=command("List the users of an Organization."))
def list_command(organization_id: OrganizationOption = None) -> None:
    organization = _organization(organization_id)
    url, insecure = load_api()
    token = session_token()
    try:
        users = list_users(
            url, token=token, organization_id=organization, allow_insecure_http=insecure
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error, not_found="Organization not found, or you do not act on it.")
    if not users:
        ui.note("No users.")
        return
    ui.table(
        "Users",
        ["resourceId", "email", "state", "phase", "permissions"],
        [
            [
                user.resource_id,
                user.email or "-",
                user.user_state or "unknown",
                _styled_phase(user),
                ", ".join(user.permissions) or "-",
            ]
            for user in users
        ],
        wrap=(
            "permissions",
        ),  # as permissões quebram linha; o resourceId e o e-mail ficam inteiros
    )
