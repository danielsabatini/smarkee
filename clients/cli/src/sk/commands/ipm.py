"""Comandos `sk ipm organization`: criar, consultar, renomear e remover Organizations.

Usam o token da sessão (`sk auth login`), renovado quando está para vencer. A API é a mesma do
`sk account create` (`[api] url`). Criar, renomear e remover são assíncronos: o comando garante o
e mostra como acompanhar a Operation. Com `--wait`, ele espera a Organization convergir. O token
precisa trazer as permissões `ipm.organization.*`, que vêm de `sk sum service enable --service ipm`
(com `--wait`, a sessão já é renovada).
"""

import uuid
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError
from rich.text import Text

from sk import output, ui
from sk.command_app import SkTyper
from sk.commands.config import known_keys, store_value
from sk.commands.ipm_group import group_app
from sk.commands.ipm_permission import permission_app
from sk.commands.ipm_role import role_app
from sk.commands.ipm_serviceaccount import serviceaccount_app
from sk.commands.ipm_user import user_app
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
)
from sk.features.api_contract import OperationStatus, RequestAccepted
from sk.features.ipm.organization import (
    Organization,
    create_organization,
    delete_organization,
    get_operation,
    get_organization,
    list_organizations,
    set_organization_protection,
    update_organization,
    validate_name,
)
from sk.help import command, option
from sk.http import ApiError
from sk.identity.oidc import OidcError
from sk.settings import ConfigurationError, SkSettings, config_file_path, read_config_document

ACTIVE_ORGANIZATION_KEY = "ipm.organizationId"

IPM_HELP = command("Resources of the Identity Provider Manager (IPM).")
ORGANIZATION_HELP = command(
    "Create, inspect, rename, protect and delete the requester's Organizations."
)

NOT_FOUND = "Organization not found for your account."
CONFLICT_ON_CHANGE = "The Organization changed since it was last read. Inspect it and try again."
PROTECTED_HINT = (
    "The Organization is protected against deletion. Run `sk ipm organization unprotect` first."
)
REJECTION_HINTS = {
    "validation": "The name is reserved or already in use, or your Organization quota is used.",
    "conflict": CONFLICT_ON_CHANGE,
    "not_found": NOT_FOUND,
    "protected": PROTECTED_HINT,
}
ERROR_CODE_HINTS = {
    "DeletionProtected": PROTECTED_HINT,
    "EmailNotVerified": (
        "Your e-mail is not verified yet. Open the link in the activation e-mail and repeat."
    ),
    "QuotaExceeded": "You reached the Organization limit. Delete one or ask an operator.",
    # Só vazia (decisão 0077): sem isso, o `409` cairia na mensagem de versão desatualizada.
    "ResourcesAttached": (
        "The Organization still has users. Delete them (`sk ipm user delete`) and repeat."
    ),
    "ResourcesNotVerifiable": (
        "The users of the Organization could not be verified. "
        "Renew the session with `sk auth refresh` and repeat."
    ),
}
NO_PERMISSION_HINT = (
    "Your account does not have permission for this operation. If the ipm service is not "
    "enabled yet, run `sk sum service enable --service ipm --wait`."
)

PHASE_STYLES = {
    "Ready": "green",
    "Failed": "red",
}  # as demais fases (em andamento) ficam em amarelo

ipm_app = SkTyper(
    help=IPM_HELP,
    no_args_is_help=True,
    # Ajuda colorida pelo Rich. Colchetes literais nos textos são escapados com "\\[".
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
organization_app = SkTyper(
    help=ORGANIZATION_HELP,
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
ipm_app.add_typer(organization_app, name="organization")
ipm_app.add_typer(user_app, name="user")
ipm_app.add_typer(serviceaccount_app, name="serviceaccount")
ipm_app.add_typer(serviceaccount_app, name="sa")
ipm_app.add_typer(group_app, name="group")
ipm_app.add_typer(permission_app, name="permission")
ipm_app.add_typer(role_app, name="role")

WaitOption = Annotated[
    bool,
    typer.Option(
        "--wait",
        help=option(
            "Wait for the Organization to converge (phase Ready and Operation completed).",
            kind="Boolean",
            variable=None,
            file=None,
            default="off",
        ),
    ),
]
ResourceIdOption = Annotated[
    str | None,
    typer.Option(
        "--resource-id",
        help=option(
            "resourceId of the Organization (returned by `create` or `list`). Without it, the "
            "active Organization is used (`sk config set ipm.organizationId`).",
            kind="String",
            variable=None,
            file=None,
            default="the active Organization",
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


def _active_organization() -> str:
    """`resourceId` da Organization ativa (ambiente ou arquivo); vazio se nenhuma foi escolhida."""
    try:
        return SkSettings().ipm.organization_id
    except (ValidationError, ConfigurationError) as error:
        ui.error("Invalid configuration", str(error), hint="Fix the indicated file and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _organization_identifier(value: str | None) -> str:
    """`resourceId` da Organization: `--resource-id` ou, na falta dele, a Organization ativa."""
    if value is None:
        value = _active_organization()
        if not value:
            ui.error(
                "Missing Organization",
                "No --resource-id was given and no Organization is active.",
                hint=(
                    "Repeat with --resource-id VALUE, or make one active with "
                    f"`sk config set {ACTIVE_ORGANIZATION_KEY} VALUE` "
                    "(or set SK_IPM_ORGANIZATION_ID)."
                ),
            )
            raise typer.Exit(EXIT_USAGE_ERROR)
    return identifier(value, "--resource-id", what="resourceId")


def _name(value: str | None) -> str:
    """`--name` obrigatório e dentro do contrato, recusado antes da chamada de rede."""
    try:
        return validate_name(require(value, "--name"))
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix --name and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _state_label(organization: Organization) -> str:
    return organization.organization_state or "unknown"


def _styled_phase(organization: Organization) -> Text:
    return Text(organization.phase, style=PHASE_STYLES.get(organization.phase, "yellow"))


def _rows(organization: Organization) -> list[tuple[str, str]]:
    rows = [
        ("resourceId", organization.resource_id),
        ("name", organization.name),
        ("state", _state_label(organization)),
        ("phase", organization.phase),
        ("platformAccess", organization.platform_access),
        ("protected", "yes" if organization.deletion_protection else "no"),
    ]
    if organization.billing_account_id is not None:
        rows.append(("billingAccountId", organization.billing_account_id))
    return rows


def _operation_rows(operation: OperationStatus) -> list[tuple[str, str]]:
    rows = [
        ("operationId", operation.operation_id),
        ("operationStatus", operation.operation_status),
    ]
    if operation.reason is not None:
        rows.append(("reason", operation.reason))
    return rows


def _get_command(accepted: RequestAccepted, *, with_operation: bool = False) -> str:
    """Comando `get` que acompanha o pedido. `--resource-id` só aparece quando a Organization
    não é a ativa; `--operation-id` só no diagnóstico de um pedido que não concluiu."""
    parts = ["sk ipm organization get"]
    if accepted.resource_id != _active_organization():
        parts.append(f"--resource-id {accepted.resource_id}")
    if with_operation:
        parts.append(f"--operation-id {accepted.operation_id}")
    return " ".join(parts)


def _activate_if_none(resource_id: str) -> None:
    """Grava a Organization recém-criada como a ativa (`[ipm] organizationId`), se não há uma.

    Uma Organization já ativa, vinda do ambiente ou do arquivo, nunca é trocada: trocar é do
    `sk config set`. Falhar aqui não desfaz nada (a Organization já existe): vira aviso.
    """
    switch_hint = f"`sk config set {ACTIVE_ORGANIZATION_KEY} {resource_id}`"
    try:
        if SkSettings().ipm.organization_id:
            ui.note(f"The active Organization was kept. To switch to this one, run {switch_hint}.")
            return
        path = config_file_path()
        store_value(
            known_keys()[ACTIVE_ORGANIZATION_KEY],
            resource_id,
            read_config_document(path),
            path=path,
        )
    except (ValidationError, ConfigurationError, OSError) as error:
        reason = getattr(error, "strerror", None) or str(error).splitlines()[0]
        ui.warning(
            f"Could not save the active Organization ({reason}). To do it, run {switch_hint}."
        )
        return
    ui.note(f"Saved as the active Organization in {path}.")


_flow = ResourceFlow(
    subject="Organization",
    get_command=_get_command,
    read_resource=get_organization,
    read_operation=get_operation,
    fail_api=_fail_api,
    rejection_hints=REJECTION_HINTS,
    rows=_rows,
    removed_key="state",
)


@organization_app.command(
    "create",
    structured=True,
    help=command(
        "Create an Organization. Follow it with `sk ipm organization get`.",
        examples=["sk ipm organization create --name acme --wait"],
    ),
)
def create_command(
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            help=option(
                "Organization name: lowercase letters, digits and hyphen, 1 to 63 characters.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    billing_account_id: Annotated[
        str | None,
        typer.Option(
            "--billing-account-id",
            help=option(
                "resourceId of the Billing Account (bsm.account) linked to this Organization.",
                kind="String",
                variable=None,
                file=None,
                default="unlinked",
            ),
        ),
    ] = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    # Obrigatória por validação do próprio comando (não pelo Typer), para não exibir "[required]".
    name = _name(name)
    if billing_account_id is not None:
        billing_account_id = identifier(
            billing_account_id, "--billing-account-id", what="billingAccountId"
        )
    url, insecure = load_api()
    token = session_token()
    try:
        accepted = create_organization(
            url,
            token=token,
            name=name,
            billing_account_id=billing_account_id,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    ui.panel(
        "Creation requested",
        [
            ("name", name),
            *([("billingAccountId", billing_account_id)] if billing_account_id is not None else []),
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
        data=accepted,
        interim=wait,
    )
    organization = _flow.finish(
        url,
        insecure,
        accepted,
        title="Organization created",
        removal=False,
        wait=wait,
        timeout=timeout,
        matches=lambda r: r.name == name,
    )
    if organization is not None:
        _activate_if_none(organization.resource_id)
    elif not wait:
        ui.note(
            "To make it the active Organization, run "
            f"`sk config set {ACTIVE_ORGANIZATION_KEY} {accepted.resource_id}`."
        )


@organization_app.command(
    "update",
    structured=True,
    help=command(
        "Rename an Organization or update its Billing Account, reading the current version first."
    ),
)
def update_command(
    resource_id: ResourceIdOption = None,
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            help=option(
                "New name: lowercase letters, digits and hyphen, 1 to 63 characters.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    billing_account_id: Annotated[
        str | None,
        typer.Option(
            "--billing-account-id",
            help=option(
                "resourceId of the Billing Account (bsm.account) linked to this Organization.",
                kind="String",
                variable=None,
                file=None,
                default="unchanged",
            ),
        ),
    ] = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    resource_id = _organization_identifier(resource_id)
    if name is None and billing_account_id is None:
        _name(name)
    validated_name = _name(name) if name is not None else None
    validated_billing = (
        identifier(billing_account_id, "--billing-account-id", what="billingAccountId")
        if billing_account_id is not None
        else None
    )
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_organization(
            url, token=token, resource_id=resource_id, allow_insecure_http=insecure
        )
        same_name = validated_name is None or current.name == validated_name
        same_billing = validated_billing is None or current.billing_account_id == validated_billing
        if same_name and same_billing:
            # Idempotente: atualizar para o que já vale não é erro.
            if validated_billing is None:
                already_done(
                    current, f"Organization {resource_id} already has this name. Nothing to do."
                )
            else:
                already_done(
                    current, f"Organization {resource_id} already has these values. Nothing to do."
                )
            return
        accepted = update_organization(
            url,
            token=token,
            resource_id=resource_id,
            resource_version=current.resource_version,
            name=validated_name,
            billing_account_id=validated_billing,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    ui.panel(
        "Rename requested" if validated_billing is None else "Update requested",
        [
            ("name", validated_name or current.name),
            *([("billingAccountId", validated_billing)] if validated_billing is not None else []),
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
        data=accepted,
        interim=wait,
    )
    _flow.finish(
        url,
        insecure,
        accepted,
        title="Organization renamed" if validated_billing is None else "Organization updated",
        removal=False,
        wait=wait,
        timeout=timeout,
        matches=(lambda r: r.name == validated_name) if validated_name is not None else None,
    )


def _set_protection(resource_id: str | None, *, protected: bool, wait: bool, timeout: int) -> None:
    resource_id = _organization_identifier(resource_id)
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_organization(
            url, token=token, resource_id=resource_id, allow_insecure_http=insecure
        )
        if current.deletion_protection == protected:
            # Idempotente: pedir o estado que já vale não é erro.
            state = "protected" if protected else "unprotected"
            already_done(current, f"Organization {resource_id} is already {state}. Nothing to do.")
            return
        accepted = set_organization_protection(
            url,
            token=token,
            resource_id=resource_id,
            resource_version=current.resource_version,
            protected=protected,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    ui.panel(
        "Protection change requested",
        [
            ("name", current.name),
            ("protected", "yes" if protected else "no"),
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
        data=accepted,
        interim=wait,
    )
    _flow.finish(
        url,
        insecure,
        accepted,
        title="Organization protected" if protected else "Organization unprotected",
        removal=False,
        wait=wait,
        timeout=timeout,
    )


@organization_app.command(
    "protect",
    structured=True,
    help=command("Protect an Organization against deletion (the default for new ones)."),
)
def protect_command(
    resource_id: ResourceIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    _set_protection(resource_id, protected=True, wait=wait, timeout=timeout)


@organization_app.command(
    "unprotect",
    structured=True,
    help=command("Allow an Organization to be deleted. Required before `delete`."),
)
def unprotect_command(
    resource_id: ResourceIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    _set_protection(resource_id, protected=False, wait=wait, timeout=timeout)


@organization_app.command(
    "delete",
    structured=True,
    help=command("Delete an Organization, reading the current version before asking."),
)
def delete_command(
    resource_id: ResourceIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    resource_id = _organization_identifier(resource_id)
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_organization(
            url, token=token, resource_id=resource_id, allow_insecure_http=insecure
        )
        accepted = delete_organization(
            url,
            token=token,
            resource_id=resource_id,
            resource_version=current.resource_version,
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
            ("name", current.name),
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
        data=accepted,
        interim=wait,
    )
    if resource_id == _active_organization():
        ui.warning(
            "This is the active Organization. Once it is gone, point to another with "
            f"`sk config set {ACTIVE_ORGANIZATION_KEY} VALUE`."
        )
    _flow.finish(
        url,
        insecure,
        accepted,
        title="Organization deleted",
        removal=True,
        wait=wait,
        timeout=timeout,
    )


@organization_app.command(
    "get",
    structured=True,
    help=command("Show the state of an Organization and, if given, of an Operation."),
)
def get_command(
    resource_id: ResourceIdOption = None,
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
    resource_id = _organization_identifier(resource_id)
    if operation_id is not None:
        operation_id = identifier(operation_id, "--operation-id", what="operationId")
    url, insecure = load_api()
    token = session_token()
    try:
        organization = get_organization(
            url, token=token, resource_id=resource_id, allow_insecure_http=insecure
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    operation: OperationStatus | None = None
    if operation_id is not None:
        try:
            operation = get_operation(
                url,
                token=token,
                resource_id=resource_id,
                operation_id=operation_id,
                allow_insecure_http=insecure,
            )
        except OidcError as error:
            bad_address(error)
        except ApiError as error:
            _fail_api(error, not_found="Operation not found for this Organization.")
    rows = _rows(organization)
    if operation is not None:
        rows.extend(_operation_rows(operation))
    document = output.to_data(organization)
    if operation is not None:
        document["operation"] = output.to_data(operation)
    ui.panel("Organization", rows, data=document)


@organization_app.command(
    "list", structured=True, help=command("List the requester's Organizations.")
)
def list_command() -> None:
    url, insecure = load_api()
    token = session_token()
    try:
        organizations = list_organizations(url, token=token, allow_insecure_http=insecure)
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    if not organizations:
        ui.empty("No Organizations.")
        return
    ui.table(
        "Organizations",
        ["name", "resourceId", "phase"],
        [[o.name, o.resource_id, _styled_phase(o)] for o in organizations],
        data=organizations,
    )
