"""Comandos `sk ipm group`: grupos de usuários da Organization (decisões 0085 e 0088).

Agrupadores de Roles compostas por Organization. Criar, alterar e remover são admitidos na hora pela
API (decisão 0098); o Grupo é só dado do SSOT e nasce convergido. Com `--wait`, o comando espera
`observedGeneration` alcançar a geração admitida.
"""

import uuid
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError
from rich.text import Text

from sk import ui
from sk.command_app import SkTyper
from sk.commands.shared import (
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    EXIT_USAGE_ERROR,
    SyncResourceFlow,
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
from sk.features.ipm.group import (
    Group,
    create_group,
    delete_group,
    get_group,
    list_groups,
    update_group,
    validate_description,
    validate_group_name,
    validate_roles_list,
)
from sk.help import command, option
from sk.http import ApiError
from sk.identity.oidc import OidcError
from sk.settings import ConfigurationError, SkSettings

ACTIVE_ORGANIZATION_KEY = "ipm.organizationId"
GROUP_HELP = command("List, inspect, create, update, protect and delete Organization groups.")

NOT_FOUND = "Group not found in an Organization you act on."
CONFLICT_ON_CHANGE = "The group changed since it was last read. Inspect it and try again."
PROTECTED_HINT = "The group is protected against deletion. Run `sk ipm group unprotect` first."
ERROR_CODE_HINTS = {
    "DeletionProtected": PROTECTED_HINT,
    "NotPresent": "The group is being deleted and cannot be changed.",
    "IdempotencyKeyReused": "The idempotency key was already used for a different request.",
    "NameAlreadyInUse": "A group with this name already exists in the Organization.",
    "ResourcesAttached": "The group still has users attached. Detach them before deleting.",
}
NO_PERMISSION_HINT = (
    "You do not have permission for this operation. Modifying group roles requires ipm.group.bind."
)

PHASE_STYLES = {"Ready": "green", "Failed": "red"}

group_app = SkTyper(
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
            "Wait for the group to converge (its generation observed and phase Ready).",
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
    fail_api_with_forbidden(
        error,
        not_found=not_found,
        conflict=CONFLICT_ON_CHANGE,
        by_error_code=ERROR_CODE_HINTS,
        forbidden=NO_PERMISSION_HINT,
    )


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
    return identifier(value, "--organization-id", what="organizationId")


def _roles(values: list[str] | None) -> list[str]:
    try:
        return validate_roles_list(values or [])
    except ValueError as error:
        usage_error(str(error), "--role")


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


def _get_command(resource_id: str) -> str:
    return f"sk ipm group get --resource-id {resource_id}"


_flow = SyncResourceFlow(
    subject="group",
    get_command=_get_command,
    read_resource=get_group,
    fail_api=_fail_api,
    rows=_rows,
)


@group_app.command(
    "create",
    structured=True,
    help=command(
        "Create a user group in the Organization with assigned composite roles.",
        examples=[
            "sk ipm group create --name devops --description DevOps --role ipm.organizationViewer"
        ],
    ),
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
        ui.error("Value not admitted", str(error), hint="Fix the given value and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    roles = _roles(role) if role is not None else []
    url, insecure = load_api()
    token = session_token()
    try:
        admitted = create_group(
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
    _flow.requested_panel("Creation requested", admitted, ("name", valid_name), wait=wait)
    _flow.finish(
        url, insecure, admitted, title="Group created", removal=False, wait=wait, timeout=timeout
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
    group_id = identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_group(url, token=token, resource_id=group_id, allow_insecure_http=insecure)
        same_desc = description is None or description.strip() == current.description
        same_roles = roles is None or sorted(roles) == sorted(current.roles)
        same_protection = protected is None or protected == current.deletion_protection
        if same_desc and same_roles and same_protection:
            already_done(current, f"Group {group_id} already has it. Nothing to do.")
            return
        admitted = update_group(
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
    _flow.requested_panel("Change requested", admitted, wait=wait)
    _flow.finish(url, insecure, admitted, title=title, removal=False, wait=wait, timeout=timeout)


@group_app.command(
    "update",
    structured=True,
    help=command(
        "Update description or roles of a group: --role replaces roles (--no-roles clears them).",
        examples=[
            "sk ipm group update --resource-id grp-123456 --role ipm.organizationAdmin"
        ],
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
        usage_error("Give at least one --role, or --no-roles (not both).", "--role")
    if description is None and not has_role_change:
        usage_error("Give --description, at least one --role, or --no-roles.", "--description")
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


@group_app.command(
    "protect",
    structured=True,
    help=command(
        "Protect a group against deletion.",
        examples=["sk ipm group protect --resource-id grp-123456"],
    ),
)
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


@group_app.command(
    "unprotect",
    structured=True,
    help=command(
        "Allow a protected group to be deleted.",
        examples=["sk ipm group unprotect --resource-id grp-123456"],
    ),
)
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


@group_app.command(
    "delete",
    structured=True,
    help=command(
        "Delete a group of the Organization.",
        examples=["sk ipm group delete --resource-id grp-123456 --wait"],
    ),
)
def delete_command(
    resource_id: GroupIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    group_id = identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_group(url, token=token, resource_id=group_id, allow_insecure_http=insecure)
        admitted = delete_group(
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
    _flow.requested_panel("Deletion requested", admitted, ("name", current.name), wait=wait)
    _flow.finish(
        url, insecure, admitted, title="Group deleted", removal=True, wait=wait, timeout=timeout
    )


@group_app.command(
    "get",
    structured=True,
    help=command(
        "Show the state of a group.",
        examples=[
            "sk ipm group get --resource-id grp-123456",
            "sk --output json ipm group get --resource-id grp-123456",
        ],
    ),
)
def get_command(resource_id: GroupIdOption = None) -> None:
    group_id = identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        group = get_group(url, token=token, resource_id=group_id, allow_insecure_http=insecure)
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    ui.panel("Group", _rows(group), data=group)


@group_app.command(
    "list",
    structured=True,
    help=command(
        "List all groups of an Organization.",
        examples=["sk ipm group list", "sk --output json ipm group list"],
    ),
)
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
        ui.empty("No groups.")
        return
    ui.table(
        "Groups",
        ["name", "resourceId", "phase", "description"],
        [[g.name, g.resource_id, _styled_phase(g), g.description] for g in groups],
        wrap=["description"],
        data=groups,
    )
