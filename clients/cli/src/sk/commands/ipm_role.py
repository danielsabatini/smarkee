"""Comandos `sk ipm role`: agrupadores de permissões atômicas (decisões 0083 e 0092).

As roles predefinidas são da plataforma; as `custom` pertencem a uma Organization e são
criadas por quem tem `ipm.role.create` (e `update`, `delete`, `bind`) nela, ou pelo operador.
Criar, alterar e remover são assíncronos: com `--wait`, o comando espera a role convergir.
"""

import uuid
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from sk import output, ui
from sk.command_app import SkTyper
from sk.commands.shared import (
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    EXIT_USAGE_ERROR,
    ResourceFlow,
    TimeoutOption,
    already_done,
    bad_address,
    fail_api_with_forbidden,
    identifier,
    load_api,
    require,
    session_token,
    usage_error,
)
from sk.features.api_contract import OperationStatus, RequestAccepted
from sk.features.ipm.role import (
    Role,
    create_role,
    delete_role,
    get_operation,
    get_role,
    list_roles,
    set_role_protection,
    update_role,
    validate_description,
    validate_permissions_list,
    validate_role_name,
)
from sk.help import command, option
from sk.http import ApiError
from sk.identity.oidc import OidcError
from sk.settings import ConfigurationError, SkSettings

ACTIVE_ORGANIZATION_KEY = "ipm.organizationId"
ROLE_HELP = command(
    "List, inspect, create, update, protect and delete predefined and Organization roles."
)

NOT_FOUND = "Role not found."
CONFLICT_ON_CHANGE = "The role changed since it was last read. Inspect it and try again."
PROTECTED_HINT = "The role is protected against deletion. Run `sk ipm role unprotect` first."
REJECTION_HINTS = {
    "validation": (
        "The role name, description or permissions are invalid, the name is already in use, "
        "or a permission is not delegable to Organizations."
    ),
    "conflict": CONFLICT_ON_CHANGE,
    "not_found": NOT_FOUND,
    "protected": PROTECTED_HINT,
}
ERROR_CODE_HINTS = {
    "DeletionProtected": PROTECTED_HINT,
    "NameAlreadyInUse": (
        "A role with this name already exists in the Organization or is a predefined role."
    ),
    "ResourcesAttached": (
        "The role is still used by users or groups of the Organization. Detach it first."
    ),
    "QuotaExceeded": "The Organization reached its limit of custom roles. Delete one first.",
}
NO_PERMISSION_HINT = (
    "You do not have permission for this operation. Managing Organization roles requires "
    "ipm.role.create, ipm.role.update, ipm.role.delete or ipm.role.bind in the Organization."
)


role_app = SkTyper(
    help=ROLE_HELP,
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)

WaitOption = Annotated[
    bool,
    typer.Option(
        "--wait",
        help=option(
            "Wait for the role to converge (phase Ready and Operation completed).",
            kind="Boolean",
            variable=None,
            file=None,
            default="off",
        ),
    ),
]
RoleIdOption = Annotated[
    str | None,
    typer.Option(
        "--resource-id",
        help=option(
            "resourceId of the role (returned by `create` or `list`).",
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
            "Atomic permission to include in the role, for example bsm.account.get. "
            "Repeat it for more permissions.",
            kind="String",
            variable=None,
            file=None,
            default="none",
        ),
    ),
]


def _fail_api(error: ApiError, *, not_found: str = NOT_FOUND) -> NoReturn:
    fail_api_with_forbidden(
        error,
        not_found=not_found,
        conflict=CONFLICT_ON_CHANGE,
        by_error_code=ERROR_CODE_HINTS,
        forbidden=NO_PERMISSION_HINT,
    )


def _active_organization() -> str | None:
    try:
        return SkSettings().ipm.organization_id or None
    except (ValidationError, ConfigurationError) as error:
        ui.error("Invalid configuration", str(error), hint="Fix the indicated file and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _organization(value: str | None) -> str:
    value = value if value is not None else _active_organization()
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
    return identifier(value, "--organization-id", what="organizationId")


def _rows(role: Role) -> list[tuple[str, str]]:
    return [
        ("resourceId", role.resource_id),
        ("organizationId", role.organization_id),
        ("name", role.name),
        ("type", role.role_type),
        ("description", role.description),
        ("permissions", ", ".join(role.permissions) or "-"),
        ("protected", "yes" if role.deletion_protection else "no"),
        ("phase", role.phase),
        ("status", role.status or "-"),
    ]


def _get_command(accepted: RequestAccepted, *, with_operation: bool = False) -> str:
    parts = ["sk ipm role get", f"--resource-id {accepted.resource_id}"]
    if with_operation:
        parts.append(f"--operation-id {accepted.operation_id}")
    return " ".join(parts)


_flow = ResourceFlow(
    subject="role",
    get_command=_get_command,
    read_resource=get_role,
    read_operation=get_operation,
    fail_api=_fail_api,
    rejection_hints=REJECTION_HINTS,
    rows=_rows,
    inspect_row=True,
)


@role_app.command(
    "create", structured=True, help=command("Create a custom role in the Organization.")
)
def create_command(
    organization_id: OrganizationOption = None,
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            help=option(
                "Role name in <module>.<roleName> format, for example acme.billingAdmin.",
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
                "Human-readable description of the role.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    permission: PermissionOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    org_id = _organization(organization_id)
    r_name = require(name, "--name")
    r_desc = require(description, "--description")
    if not permission:
        usage_error("Give at least one --permission for the role.", "--permission")
    try:
        valid_name = validate_role_name(r_name)
        valid_desc = validate_description(r_desc, name=valid_name)
        valid_perms = validate_permissions_list(permission)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix the given value and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    url, insecure = load_api()
    token = session_token()
    try:
        accepted = create_role(
            url,
            token=token,
            organization_id=org_id,
            name=valid_name,
            description=valid_desc,
            permissions=valid_perms,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _flow.accepted_panel("Creation requested", accepted, wait=wait)
    _flow.finish(
        url, insecure, accepted, title="Role created", removal=False, wait=wait, timeout=timeout
    )


@role_app.command(
    "update",
    structured=True,
    help=command("Update the description or atomic permissions of a composite role."),
)
def update_command(
    resource_id: RoleIdOption = None,
    description: Annotated[
        str | None,
        typer.Option(
            "--description",
            help=option(
                "New description of the role.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    permission: PermissionOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    role_id = identifier(resource_id, "--resource-id", what="resourceId")
    if description is None and permission is None:
        usage_error("Give at least --description or --permission.", "--description")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_role(url, token=token, resource_id=role_id, allow_insecure_http=insecure)
        same_desc = description is None or description.strip() == current.description
        same_perms = permission is None or sorted(set(permission)) == sorted(current.permissions)
        if same_desc and same_perms:
            already_done(current, f"Role {role_id} already has it. Nothing to do.")
            return
        accepted = update_role(
            url,
            token=token,
            resource_id=role_id,
            resource_version=current.resource_version,
            description=None if same_desc else description,
            permissions=None if same_perms else permission,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _flow.accepted_panel("Change requested", accepted, wait=wait)
    _flow.finish(
        url, insecure, accepted, title="Role updated", removal=False, wait=wait, timeout=timeout
    )


@role_app.command("protect", structured=True, help=command("Protect a role against deletion."))
def protect_command(
    resource_id: RoleIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    role_id = identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_role(url, token=token, resource_id=role_id, allow_insecure_http=insecure)
        if current.deletion_protection:
            already_done(current, f"Role {role_id} already has it. Nothing to do.")
            return
        accepted = set_role_protection(
            url,
            token=token,
            resource_id=role_id,
            resource_version=current.resource_version,
            protected=True,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _flow.accepted_panel("Change requested", accepted, wait=wait)
    _flow.finish(
        url, insecure, accepted, title="Role protected", removal=False, wait=wait, timeout=timeout
    )


@role_app.command(
    "unprotect",
    structured=True,
    help=command("Allow a protected role to be deleted."),
)
def unprotect_command(
    resource_id: RoleIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    role_id = identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_role(url, token=token, resource_id=role_id, allow_insecure_http=insecure)
        if not current.deletion_protection:
            already_done(current, f"Role {role_id} already has it. Nothing to do.")
            return
        accepted = set_role_protection(
            url,
            token=token,
            resource_id=role_id,
            resource_version=current.resource_version,
            protected=False,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _flow.accepted_panel("Change requested", accepted, wait=wait)
    _flow.finish(
        url, insecure, accepted, title="Role unprotected", removal=False, wait=wait, timeout=timeout
    )


@role_app.command(
    "delete",
    structured=True,
    help=command("Delete a composite role, reading the current version before asking."),
)
def delete_command(
    resource_id: RoleIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    role_id = identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_role(url, token=token, resource_id=role_id, allow_insecure_http=insecure)
        accepted = delete_role(
            url,
            token=token,
            resource_id=role_id,
            resource_version=current.resource_version,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _flow.accepted_panel("Deletion requested", accepted, wait=wait)
    _flow.finish(
        url, insecure, accepted, title="Role deleted", removal=True, wait=wait, timeout=timeout
    )


@role_app.command("get", structured=True, help=command("Inspect a composite role."))
def get_command(
    resource_id: RoleIdOption = None,
    operation_id: Annotated[
        str | None,
        typer.Option(
            "--operation-id",
            help=option(
                "operationId to inspect alongside the role (returned by `create`).",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
) -> None:
    role_id = identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    operation: OperationStatus | None = None
    try:
        role = get_role(url, token=token, resource_id=role_id, allow_insecure_http=insecure)
        if operation_id is not None:
            operation = get_operation(
                url,
                token=token,
                resource_id=role_id,
                operation_id=operation_id,
                allow_insecure_http=insecure,
            )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    rows = _rows(role)
    if operation is not None:
        rows.append(("operationStatus", operation.operation_status))
        if operation.reason is not None:
            rows.append(("reason", operation.reason))
    document = output.to_data(role)
    if operation is not None:
        document["operation"] = output.to_data(operation)
    ui.panel("Role", rows, data=document)


@role_app.command(
    "list",
    structured=True,
    help=command("List predefined roles and the custom roles of an Organization."),
)
def list_command(organization_id: OrganizationOption = None) -> None:
    org_id = (
        identifier(organization_id, "--organization-id", what="organizationId")
        if organization_id is not None
        else _active_organization()
    )
    url, insecure = load_api()
    token = session_token()
    try:
        roles = list_roles(url, token=token, organization_id=org_id, allow_insecure_http=insecure)
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    if not roles:
        ui.empty("No roles found.")
        return
    ui.table(
        "Roles",
        ["name", "resourceId", "type", "description"],
        [[r.name, r.resource_id, r.role_type, r.description] for r in roles],
        wrap=["description"],
        data=roles,
    )
