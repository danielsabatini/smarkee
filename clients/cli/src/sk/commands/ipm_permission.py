"""Comandos `sk ipm permission`: permissões atômicas da plataforma (decisão 0083).

Operadores com a permissão `ipm.permission.admin` criam, consultam, alteram, protegem e removem
permissões atômicas reconciliadas no provedor de identidade. Usuários da plataforma consultam
(`ipm.permission.list` e `ipm.permission.get`). Criar, alterar e remover são assíncronos: com
`--wait`, o comando espera a permissão convergir.
"""

import time
import uuid
from typing import Annotated, NoReturn

import typer
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
from sk.features.ipm.permission import (
    Permission,
    create_permission,
    delete_permission,
    get_operation,
    get_permission,
    list_permissions,
    set_permission_protection,
    update_permission,
    validate_description,
    validate_permission_name,
)
from sk.help import command, option
from sk.http import ApiError, ApiRejectedError
from sk.identity.oidc import OidcError

PERMISSION_HELP = command(
    "List, inspect, create, update, protect and delete atomic platform permissions."
)

NOT_FOUND = "Permission not found."
CONFLICT_ON_CHANGE = "The permission changed since it was last read. Inspect it and try again."
PROTECTED_HINT = (
    "The permission is protected against deletion. Run `sk ipm permission unprotect` first."
)
REJECTION_HINTS = {
    "validation": "The permission name or description is invalid, or the name is already in use.",
    "conflict": CONFLICT_ON_CHANGE,
    "not_found": NOT_FOUND,
    "protected": PROTECTED_HINT,
}
ERROR_CODE_HINTS = {
    "DeletionProtected": PROTECTED_HINT,
    "NameAlreadyInUse": "A permission with this name already exists in the platform.",
}
NO_PERMISSION_HINT = (
    "You do not have permission for this operation. Modifying permissions requires "
    "ipm.permission.admin."
)

PHASE_STYLES = {"Ready": "green", "Failed": "red"}

permission_app = typer.Typer(
    help=PERMISSION_HELP,
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)

WaitOption = Annotated[
    bool,
    typer.Option(
        "--wait",
        help=option(
            "Wait for the permission to converge (phase Ready and Operation completed).",
            kind="Boolean",
            variable=None,
            file=None,
            default="off",
        ),
    ),
]
PermissionIdOption = Annotated[
    str | None,
    typer.Option(
        "--resource-id",
        help=option(
            "resourceId of the permission (returned by `create` or `list`).",
            kind="String",
            variable=None,
            file=None,
            default="none",
        ),
    ),
]


def _fail_api(error: ApiError, *, not_found: str = NOT_FOUND) -> NoReturn:
    by_code = dict(ERROR_CODE_HINTS)
    if isinstance(error, ApiRejectedError) and error.status == 403:
        by_code["Forbidden"] = NO_PERMISSION_HINT
    fail_api(error, not_found=not_found, conflict=CONFLICT_ON_CHANGE, by_error_code=by_code)


def _usage_error(message: str, option_name: str) -> NoReturn:
    ui.error("Value not accepted", message, hint=f"Fix {option_name} and repeat.")
    raise typer.Exit(EXIT_USAGE_ERROR)


def _identifier(value: str | None, option_name: str, *, what: str) -> str:
    try:
        return validate_identifier(require(value, option_name), what=what)
    except ValueError as error:
        _usage_error(str(error), option_name)


def _styled_phase(permission: Permission) -> Text:
    return Text(permission.phase, style=PHASE_STYLES.get(permission.phase, "yellow"))


def _rows(permission: Permission) -> list[tuple[str, str]]:
    return [
        ("resourceId", permission.resource_id),
        ("name", permission.name),
        ("description", permission.description),
        ("grantable", "yes" if permission.grantable else "no"),
        ("protected", "yes" if permission.deletion_protection else "no"),
        ("phase", permission.phase),
        ("status", permission.status or "-"),
    ]


def _get_command(accepted: RequestAccepted, *, with_operation: bool = False) -> str:
    parts = ["sk ipm permission get", f"--resource-id {accepted.resource_id}"]
    if with_operation:
        parts.append(f"--operation-id {accepted.operation_id}")
    return " ".join(parts)


def _timed_out(timeout: int, accepted: RequestAccepted, state: str) -> NoReturn:
    ui.error(
        "Timed out",
        f"{timeout} s passed and the permission {state}.",
        hint=f"The request is still in progress: `{_get_command(accepted)}`.",
    )
    raise typer.Exit(EXIT_FAILURE)


def _wait_for_convergence(
    url: str, insecure: bool, accepted: RequestAccepted, *, removal: bool, timeout: int
) -> Permission | None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        token = session_token()
        permission: Permission | None = None
        try:
            op = get_operation(
                url,
                token=token,
                resource_id=accepted.resource_id,
                operation_id=accepted.operation_id,
                allow_insecure_http=insecure,
            )
            if op.operation_status in ("rejected", "failed", "superseded"):
                if op.operation_status == "rejected":
                    reason = op.reason or "validation"
                    title, text = "Request rejected", f"The request was rejected: {reason}."
                    hint = REJECTION_HINTS.get(reason, "Inspect the Operation for details.")
                else:
                    # `failed` (prazo ou limite esgotado) e `superseded` (trocada por outro
                    # pedido) não têm motivo de rejeição.
                    title = "Request not completed"
                    text = f"The Operation ended as {op.operation_status}."
                    hint = "Inspect the Operation for details."
                ui.error(
                    title,
                    text,
                    hint=f"{hint} `{_get_command(accepted, with_operation=True)}`.",
                )
                raise typer.Exit(EXIT_FAILURE)
            try:
                permission = get_permission(
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
            if time.monotonic() >= deadline:
                _timed_out(timeout, accepted, "is not visible yet")
            time.sleep(WAIT_POLL_SECONDS)
            continue
        except ApiError as error:
            _fail_api(error)
        if op.operation_status == "completed":
            if removal and permission is None:
                return None
            if not removal and permission is not None and permission.phase == "Ready":
                return permission
        if time.monotonic() >= deadline:
            where = f"is in phase {permission.phase}" if permission is not None else "was removed"
            _timed_out(timeout, accepted, f"{where} (Operation {op.operation_status})")
        time.sleep(WAIT_POLL_SECONDS)
    _timed_out(timeout, accepted, "was not removed" if removal else "did not become Ready")


def _accepted_panel(title: str, accepted: RequestAccepted) -> None:
    ui.panel(
        title,
        [
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
            ("inspect", _get_command(accepted, with_operation=True)),
        ],
    )


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
    result = _wait_for_convergence(url, insecure, accepted, removal=removal, timeout=timeout)
    if result is None:
        ui.panel(title, [("resourceId", accepted.resource_id), ("state", "removed")])
        return
    ui.panel(title, _rows(result))


@permission_app.command("create", help=command("Create an atomic platform permission."))
def create_command(
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            help=option(
                "Permission name in <module>.<type>.<action> format, for example bsm.account.get.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    description: Annotated[
        str | None,
        typer.Option(
            "--description",
            help=option(
                "Human-readable description of the authorized action.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    grantable: Annotated[
        bool,
        typer.Option(
            "--grantable/--not-grantable",
            help=option(
                "Whether this permission can be delegated to customer Organizations.",
                kind="Boolean",
                variable=None,
                file=None,
                default="grantable",
            ),
        ),
    ] = True,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    perm_name = require(name, "--name")
    perm_desc = require(description, "--description")
    try:
        valid_name = validate_permission_name(perm_name)
        valid_desc = validate_description(perm_desc, name=valid_name)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix the given value and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    url, insecure = load_api()
    token = session_token()
    try:
        accepted = create_permission(
            url,
            token=token,
            name=valid_name,
            description=valid_desc,
            grantable=grantable,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _accepted_panel("Creation requested", accepted)
    _finish_request(
        url,
        insecure,
        accepted,
        title="Permission created",
        removal=False,
        wait=wait,
        timeout=timeout,
    )


@permission_app.command(
    "update",
    help=command("Update the description or grantable status of a platform permission."),
)
def update_command(
    resource_id: PermissionIdOption = None,
    description: Annotated[
        str | None,
        typer.Option(
            "--description",
            help=option(
                "New description of the permission.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    grantable: Annotated[
        bool | None,
        typer.Option(
            "--grantable/--not-grantable",
            help=option(
                "Whether this permission can be delegated to customer Organizations.",
                kind="Boolean",
                variable=None,
                file=None,
                default="leave unchanged",
            ),
        ),
    ] = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    perm_id = _identifier(resource_id, "--resource-id", what="resourceId")
    if description is None and grantable is None:
        _usage_error("Give at least --description or --grantable/--not-grantable.", "--description")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_permission(
            url, token=token, resource_id=perm_id, allow_insecure_http=insecure
        )
        same_desc = description is None or description.strip() == current.description
        same_grantable = grantable is None or grantable == current.grantable
        if same_desc and same_grantable:
            ui.note(f"Permission {perm_id} already has it. Nothing to do.")
            return
        accepted = update_permission(
            url,
            token=token,
            resource_id=perm_id,
            resource_version=current.resource_version,
            description=None if same_desc else description,
            grantable=None if same_grantable else grantable,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _accepted_panel("Change requested", accepted)
    _finish_request(
        url,
        insecure,
        accepted,
        title="Permission updated",
        removal=False,
        wait=wait,
        timeout=timeout,
    )


@permission_app.command("protect", help=command("Protect a permission against deletion."))
def protect_command(
    resource_id: PermissionIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    perm_id = _identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_permission(
            url, token=token, resource_id=perm_id, allow_insecure_http=insecure
        )
        if current.deletion_protection:
            ui.note(f"Permission {perm_id} already has it. Nothing to do.")
            return
        accepted = set_permission_protection(
            url,
            token=token,
            resource_id=perm_id,
            resource_version=current.resource_version,
            protected=True,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _accepted_panel("Change requested", accepted)
    _finish_request(
        url,
        insecure,
        accepted,
        title="Permission protected",
        removal=False,
        wait=wait,
        timeout=timeout,
    )


@permission_app.command(
    "unprotect",
    help=command("Allow a protected permission to be deleted."),
)
def unprotect_command(
    resource_id: PermissionIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    perm_id = _identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_permission(
            url, token=token, resource_id=perm_id, allow_insecure_http=insecure
        )
        if not current.deletion_protection:
            ui.note(f"Permission {perm_id} already has it. Nothing to do.")
            return
        accepted = set_permission_protection(
            url,
            token=token,
            resource_id=perm_id,
            resource_version=current.resource_version,
            protected=False,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _accepted_panel("Change requested", accepted)
    _finish_request(
        url,
        insecure,
        accepted,
        title="Permission unprotected",
        removal=False,
        wait=wait,
        timeout=timeout,
    )


@permission_app.command(
    "delete",
    help=command(
        "Delete an atomic platform permission, reading the current version before asking."
    ),
)
def delete_command(
    resource_id: PermissionIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    perm_id = _identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_permission(
            url, token=token, resource_id=perm_id, allow_insecure_http=insecure
        )
        accepted = delete_permission(
            url,
            token=token,
            resource_id=perm_id,
            resource_version=current.resource_version,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _accepted_panel("Deletion requested", accepted)
    _finish_request(
        url,
        insecure,
        accepted,
        title="Permission deleted",
        removal=True,
        wait=wait,
        timeout=timeout,
    )


@permission_app.command("get", help=command("Inspect a platform permission."))
def get_command(
    resource_id: PermissionIdOption = None,
    operation_id: Annotated[
        str | None,
        typer.Option(
            "--operation-id",
            help=option(
                "operationId to inspect alongside the permission (returned by `create`).",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
) -> None:
    perm_id = _identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    operation: OperationStatus | None = None
    try:
        permission = get_permission(
            url, token=token, resource_id=perm_id, allow_insecure_http=insecure
        )
        if operation_id is not None:
            operation = get_operation(
                url,
                token=token,
                resource_id=perm_id,
                operation_id=operation_id,
                allow_insecure_http=insecure,
            )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    rows = _rows(permission)
    if operation is not None:
        rows.append(("operationStatus", operation.operation_status))
        if operation.reason is not None:
            rows.append(("reason", operation.reason))
    ui.panel("Permission", rows)


@permission_app.command("list", help=command("List platform permissions."))
def list_command() -> None:
    url, insecure = load_api()
    token = session_token()
    try:
        permissions = list_permissions(url, token=token, allow_insecure_http=insecure)
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    if not permissions:
        ui.note("No permissions found.")
        return
    ui.table(
        "Permissions",
        ["resourceId", "name", "grantable", "protected", "phase", "description"],
        [
            [
                p.resource_id,
                p.name,
                "yes" if p.grantable else "no",
                "yes" if p.deletion_protection else "no",
                _styled_phase(p),
                p.description,
            ]
            for p in permissions
        ],
        wrap=["description"],
    )
