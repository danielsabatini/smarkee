"""Comandos `sk ipm group`: grupos de usuários da Organization (decisões 0085 e 0088).

Agrupadores de Roles compostas por Organization. Criar, alterar e remover são assíncronos:
com `--wait`, o comando espera o grupo convergir.
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
from sk.features.ipm.group import (
    Group,
    create_group,
    delete_group,
    get_group,
    get_operation,
    list_groups,
    update_group,
    validate_description,
    validate_group_name,
    validate_roles_list,
)
from sk.help import command, option
from sk.http import ApiError, ApiRejectedError
from sk.identity.oidc import OidcError
from sk.settings import ConfigurationError, SkSettings

ACTIVE_ORGANIZATION_KEY = "ipm.organizationId"
GROUP_HELP = command("List, inspect, create, update, protect and delete Organization groups.")

NOT_FOUND = "Group not found in an Organization you act on."
CONFLICT_ON_CHANGE = "The group changed since it was last read. Inspect it and try again."
PROTECTED_HINT = "The group is protected against deletion. Run `sk ipm group unprotect` first."
REJECTION_HINTS = {
    "validation": (
        "The group name, description or roles are invalid, or the name is already in use."
    ),
    "conflict": CONFLICT_ON_CHANGE,
    "not_found": NOT_FOUND,
    "protected": PROTECTED_HINT,
}
ERROR_CODE_HINTS = {
    "DeletionProtected": PROTECTED_HINT,
    "NameAlreadyInUse": "A group with this name already exists in the Organization.",
    "ResourcesAttached": "The group still has users attached. Detach them before deleting.",
}
NO_PERMISSION_HINT = (
    "You do not have permission for this operation. Modifying group roles requires ipm.group.bind."
)

PHASE_STYLES = {"Ready": "green", "Failed": "red"}

group_app = typer.Typer(
    help=GROUP_HELP,
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)

WaitOption = Annotated[
    bool,
    typer.Option(
        "--wait",
        help=option(
            "Wait for the group to converge (phase Ready and Operation completed).",
            kind="Boolean",
            variable=None,
            file=None,
            default="off",
        ),
    ),
]
GroupIdOption = Annotated[
    str | None,
    typer.Option(
        "--resource-id",
        help=option(
            "resourceId of the group (returned by `create` or `list`).",
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
RoleOption = Annotated[
    list[str] | None,
    typer.Option(
        "--role",
        help=option(
            "Role to grant to the group, for example ipm.userViewer. Repeat it for more roles.",
            kind="String",
            variable=None,
            file=None,
            default="no roles",
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


def _organization(value: str | None) -> str:
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


def _roles(values: list[str] | None) -> list[str]:
    try:
        return validate_roles_list(values or [])
    except ValueError as error:
        _usage_error(str(error), "--role")


def _styled_phase(group: Group) -> Text:
    return Text(group.phase, style=PHASE_STYLES.get(group.phase, "yellow"))


def _rows(group: Group) -> list[tuple[str, str]]:
    return [
        ("resourceId", group.resource_id),
        ("organizationId", group.organization_id),
        ("name", group.name),
        ("description", group.description),
        ("phase", group.phase),
        ("roles", ", ".join(group.roles) or "-"),
        ("protected", "yes" if group.deletion_protection else "no"),
    ]


def _get_command(accepted: RequestAccepted, *, with_operation: bool = False) -> str:
    parts = ["sk ipm group get", f"--resource-id {accepted.resource_id}"]
    if with_operation:
        parts.append(f"--operation-id {accepted.operation_id}")
    return " ".join(parts)


def _timed_out(timeout: int, accepted: RequestAccepted, state: str) -> NoReturn:
    ui.error(
        "Timed out",
        f"{timeout} s passed and the group {state}.",
        hint=f"The request is still in progress: `{_get_command(accepted)}`.",
    )
    raise typer.Exit(EXIT_FAILURE)


def _wait_for_convergence(
    url: str, insecure: bool, accepted: RequestAccepted, *, removal: bool, timeout: int
) -> Group | None:
    ui.note(f"Waiting for convergence (up to {timeout} s)...")
    deadline = time.monotonic() + timeout
    while True:
        token = session_token()
        group: Group | None = None
        try:
            operation = get_operation(
                url,
                token=token,
                resource_id=accepted.resource_id,
                operation_id=accepted.operation_id,
                allow_insecure_http=insecure,
            )
            if operation.operation_status in ("rejected", "failed", "superseded"):
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
                group = get_group(
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
        if operation.operation_status == "completed":
            if removal and group is None:
                return None
            if not removal and group is not None and group.phase == "Ready":
                return group
        if time.monotonic() >= deadline:
            where = f"is in phase {group.phase}" if group is not None else "was removed"
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
    group = _wait_for_convergence(url, insecure, accepted, removal=removal, timeout=timeout)
    if group is None:
        ui.panel(title, [("resourceId", accepted.resource_id), ("state", "removed")])
        return
    ui.panel(title, _rows(group))


def _accepted_panel(title: str, accepted: RequestAccepted, *extra: tuple[str, str]) -> None:
    ui.panel(
        title,
        [*extra, ("resourceId", accepted.resource_id), ("operationId", accepted.operation_id)],
    )


@group_app.command(
    "create",
    help=command("Create a user group in the Organization with assigned composite roles."),
)
def create_command(
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            help=option(
                "Group slug name (2-63 lowercase alphanumeric and hyphen).",
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
                "Description of the group in Brazilian Portuguese.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    organization_id: OrganizationOption = None,
    role: RoleOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    name_str = require(name, "--name")
    desc_str = require(description, "--description")
    org_id = _organization(organization_id)
    try:
        valid_name = validate_group_name(name_str)
        valid_desc = validate_description(desc_str, name=valid_name)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix the given value and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    roles = _roles(role) if role is not None else []
    url, insecure = load_api()
    token = session_token()
    try:
        accepted = create_group(
            url,
            token=token,
            organization_id=org_id,
            name=valid_name,
            description=valid_desc,
            roles=roles,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _accepted_panel("Creation requested", accepted, ("name", valid_name))
    _finish_request(
        url, insecure, accepted, title="Group created", removal=False, wait=wait, timeout=timeout
    )


def _change(
    resource_id: str | None,
    *,
    description: str | None,
    roles: list[str] | None,
    protected: bool | None,
    title: str,
    wait: bool,
    timeout: int,
) -> None:
    group_id = _identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_group(url, token=token, resource_id=group_id, allow_insecure_http=insecure)
        same_desc = description is None or description.strip() == current.description
        same_roles = roles is None or sorted(roles) == sorted(current.roles)
        same_protection = protected is None or protected == current.deletion_protection
        if same_desc and same_roles and same_protection:
            ui.note(f"Group {group_id} already has it. Nothing to do.")
            return
        accepted = update_group(
            url,
            token=token,
            resource_id=group_id,
            resource_version=current.resource_version,
            description=None if same_desc else description,
            roles=None if same_roles else roles,
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


@group_app.command(
    "update",
    help=command(
        "Update description or roles of a group: --role replaces roles (--no-roles clears them)."
    ),
)
def update_command(
    resource_id: GroupIdOption = None,
    description: Annotated[
        str | None,
        typer.Option(
            "--description",
            help=option(
                "New description of the group.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    role: RoleOption = None,
    no_roles: Annotated[
        bool,
        typer.Option(
            "--no-roles",
            help=option(
                "Remove every role of the group.",
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
    has_role_change = role is not None or no_roles
    if has_role_change and (bool(role) == no_roles):
        _usage_error("Give at least one --role, or --no-roles (not both).", "--role")
    if description is None and not has_role_change:
        _usage_error("Give --description, at least one --role, or --no-roles.", "--description")
    roles_list = [] if no_roles else (_roles(role) if role is not None else None)
    _change(
        resource_id,
        description=description,
        roles=roles_list,
        protected=None,
        title="Group updated",
        wait=wait,
        timeout=timeout,
    )


@group_app.command("protect", help=command("Protect a group against deletion."))
def protect_command(
    resource_id: GroupIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    _change(
        resource_id,
        description=None,
        roles=None,
        protected=True,
        title="Group protected",
        wait=wait,
        timeout=timeout,
    )


@group_app.command("unprotect", help=command("Allow a protected group to be deleted."))
def unprotect_command(
    resource_id: GroupIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    _change(
        resource_id,
        description=None,
        roles=None,
        protected=False,
        title="Group unprotected",
        wait=wait,
        timeout=timeout,
    )


@group_app.command("delete", help=command("Delete a group of the Organization."))
def delete_command(
    resource_id: GroupIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    group_id = _identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_group(url, token=token, resource_id=group_id, allow_insecure_http=insecure)
        accepted = delete_group(
            url,
            token=token,
            resource_id=group_id,
            resource_version=current.resource_version,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _accepted_panel("Deletion requested", accepted, ("name", current.name))
    _finish_request(
        url, insecure, accepted, title="Group deleted", removal=True, wait=wait, timeout=timeout
    )


@group_app.command("get", help=command("Show the state of a group and, if given, of an Operation."))
def get_command(
    resource_id: GroupIdOption = None,
    operation_id: Annotated[
        str | None,
        typer.Option(
            "--operation-id",
            help=option(
                "operationId of a request, to see why it was rejected or failed.",
                kind="String",
                variable=None,
                file=None,
                default="no Operation lookup",
            ),
        ),
    ] = None,
) -> None:
    group_id = _identifier(resource_id, "--resource-id", what="resourceId")
    if operation_id is not None:
        operation_id = _identifier(operation_id, "--operation-id", what="operationId")
    url, insecure = load_api()
    token = session_token()
    operation: OperationStatus | None = None
    try:
        group = get_group(url, token=token, resource_id=group_id, allow_insecure_http=insecure)
        if operation_id is not None:
            operation = get_operation(
                url,
                token=token,
                resource_id=group_id,
                operation_id=operation_id,
                allow_insecure_http=insecure,
            )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    rows = _rows(group)
    if operation is not None:
        rows.append(("operationStatus", operation.operation_status))
        if operation.reason is not None:
            rows.append(("reason", operation.reason))
    ui.panel("Group", rows)


@group_app.command("list", help=command("List all groups of an Organization."))
def list_command(organization_id: OrganizationOption = None) -> None:
    org_id = _organization(organization_id)
    url, insecure = load_api()
    token = session_token()
    try:
        groups = list_groups(url, token=token, organization_id=org_id, allow_insecure_http=insecure)
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    if not groups:
        ui.note("No groups.")
        return
    ui.table(
        "Groups",
        ["resourceId", "name", "phase", "roles", "description"],
        [
            [
                g.resource_id,
                g.name,
                _styled_phase(g),
                ", ".join(g.roles) or "-",
                g.description,
            ]
            for g in groups
        ],
        wrap=("description", "roles"),
    )
