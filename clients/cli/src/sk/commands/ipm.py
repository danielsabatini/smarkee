"""Comandos `sk ipm organization`: criar, consultar, renomear e remover Organizations.

Usam o token da sessão (`sk auth login`), renovado quando está para vencer. A API é a mesma do
`sk account create` (`[api] url`). Criar, renomear e remover são assíncronos: o comando garante o
e mostra como acompanhar a Operation. Com `--wait`, ele espera a Organization convergir. O token
precisa trazer as roles `ipm.organization.*`, que vêm de `sk sum service enable --service ipm`
(com `--wait`, a sessão já é renovada).
"""

import time
import uuid
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError
from rich.text import Text

from sk import ui
from sk.commands.config import known_keys, store_value
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
from sk.http import ApiError, ApiRejectedError
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
}
NO_ROLE_HINT = (
    "Your account does not have permission for this operation. If the ipm service is not "
    "enabled yet, run `sk sum service enable --service ipm --wait`."
)

STATE_STYLES = {"active": "green", "inactive": "dim"}
PHASE_STYLES = {
    "Ready": "green",
    "Failed": "red",
}  # as demais fases (em andamento) ficam em amarelo

ipm_app = typer.Typer(
    help=IPM_HELP,
    no_args_is_help=True,
    # Ajuda colorida pelo Rich. Colchetes literais nos textos são escapados com "\\[".
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
organization_app = typer.Typer(
    help=ORGANIZATION_HELP,
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
ipm_app.add_typer(organization_app, name="organization")

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
    if isinstance(error, ApiRejectedError) and error.status == 403:
        by_code = {**ERROR_CODE_HINTS, "Forbidden": NO_ROLE_HINT}
    else:
        by_code = ERROR_CODE_HINTS
    fail_api(error, not_found=not_found, conflict=CONFLICT_ON_CHANGE, by_error_code=by_code)


def _identifier(value: str | None, option_name: str, *, what: str) -> str:
    """Opção obrigatória que é um identificador do contrato, recusada antes da chamada de rede."""
    try:
        return validate_identifier(require(value, option_name), what=what)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint=f"Fix {option_name} and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


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
    return _identifier(value, "--resource-id", what="resourceId")


def _name(value: str | None) -> str:
    """`--name` obrigatório e dentro do contrato, recusado antes da chamada de rede."""
    try:
        return validate_name(require(value, "--name"))
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix --name and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _state_label(organization: Organization) -> str:
    return organization.organization_state or "unknown"


def _styled_state(organization: Organization) -> Text:
    return Text(_state_label(organization), style=STATE_STYLES.get(_state_label(organization), ""))


def _styled_phase(organization: Organization) -> Text:
    return Text(organization.phase, style=PHASE_STYLES.get(organization.phase, "yellow"))


def _rows(organization: Organization) -> list[tuple[str, str]]:
    return [
        ("resourceId", organization.resource_id),
        ("name", organization.name),
        ("state", _state_label(organization)),
        ("phase", organization.phase),
        ("platformAccess", organization.platform_access),
        ("protected", "yes" if organization.deletion_protection else "no"),
    ]


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


def _timed_out(
    timeout: int, accepted: RequestAccepted, state: str = "is not visible yet"
) -> NoReturn:
    ui.error(
        "Timed out",
        f"{timeout} s passed and the Organization {state}.",
        hint=f"The request is still in progress: `{_get_command(accepted)}`.",
    )
    raise typer.Exit(EXIT_FAILURE)


def _wait_for_convergence(
    url: str,
    insecure: bool,
    accepted: RequestAccepted,
    *,
    expect_name: str | None,
    removal: bool,
    timeout: int,
) -> Organization | None:
    """Espera a Operation `completed` (e a Organization `Ready` com o nome pedido); se não der,
    sai dizendo por quê. Na remoção, devolve `None` quando a Organization já não existe.

    O token é pedido a cada leitura: o acesso dura 15 minutos, e uma espera longa (`--timeout`)
    pode atravessar o vencimento (a sessão se renova pelo refresh token).
    """
    ui.note(f"Waiting for convergence (up to {timeout} s)...")
    deadline = time.monotonic() + timeout
    while True:
        token = session_token()
        organization: Organization | None = None
        try:
            operation = get_operation(
                url,
                token=token,
                resource_id=accepted.resource_id,
                operation_id=accepted.operation_id,
                allow_insecure_http=insecure,
            )
            try:
                organization = get_organization(
                    url,
                    token=token,
                    resource_id=accepted.resource_id,
                    allow_insecure_http=insecure,
                )
            except ApiRejectedError as error:
                # Na remoção, o `404` da Organization é o resultado esperado (a linha foi apagada).
                if not (removal and error.status == HTTP_NOT_FOUND):
                    raise
        except OidcError as error:
            bad_address(error)
        except ApiRejectedError as error:
            if error.status != HTTP_NOT_FOUND:
                _fail_api(error)
            # Logo depois do `202`, o Manager ainda pode não ter gravado a Operation e o recurso
            # (`docs/RESOURCE-CONTROL-LOOP.md` §6.1.1): é espera, e não erro.
            if time.monotonic() >= deadline:
                _timed_out(timeout, accepted)
            time.sleep(WAIT_POLL_SECONDS)
            continue
        except ApiError as error:
            _fail_api(error)
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
        if operation.operation_status == "completed":
            if removal and organization is None:
                return None
            if (
                not removal
                and organization is not None
                and organization.phase == "Ready"
                and (expect_name is None or organization.name == expect_name)
            ):
                return organization
        if time.monotonic() >= deadline:
            where = (
                f"is in phase {organization.phase}" if organization is not None else "was removed"
            )
            _timed_out(timeout, accepted, f"{where} (Operation {operation.operation_status})")
        time.sleep(WAIT_POLL_SECONDS)


def _finish_request(
    url: str,
    insecure: bool,
    accepted: RequestAccepted,
    *,
    title: str,
    expect_name: str | None,
    removal: bool,
    wait: bool,
    timeout: int,
) -> Organization | None:
    """Fim de `create`, `update` e `delete`: orienta o acompanhamento ou, com `--wait`, espera.

    Devolve a Organization convergida, ou `None` sem `--wait` e quando ela foi removida.
    """
    if not wait:
        ui.note(f"Follow it with `{_get_command(accepted)}`.")
        return None
    organization = _wait_for_convergence(
        url, insecure, accepted, expect_name=expect_name, removal=removal, timeout=timeout
    )
    if organization is None:
        ui.panel(title, [("resourceId", accepted.resource_id), ("state", "removed")])
        return None
    ui.panel(title, _rows(organization))
    return organization


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


@organization_app.command(
    "create",
    help=command("Create an Organization. Follow it with `sk ipm organization get`."),
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
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    # Obrigatória por validação do próprio comando (não pelo Typer), para não exibir "[required]".
    name = _name(name)
    url, insecure = load_api()
    token = session_token()
    try:
        accepted = create_organization(
            url,
            token=token,
            name=name,
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
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
    )
    organization = _finish_request(
        url,
        insecure,
        accepted,
        title="Organization created",
        expect_name=name,
        removal=False,
        wait=wait,
        timeout=timeout,
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
    help=command("Rename an Organization, reading the current version before asking."),
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
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    resource_id = _organization_identifier(resource_id)
    name = _name(name)
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_organization(
            url, token=token, resource_id=resource_id, allow_insecure_http=insecure
        )
        if current.name == name:
            # Idempotente: renomear para o nome que já vale não é erro.
            ui.note(f"Organization {resource_id} already has this name. Nothing to do.")
            return
        accepted = update_organization(
            url,
            token=token,
            resource_id=resource_id,
            resource_version=current.resource_version,
            name=name,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    ui.panel(
        "Rename requested",
        [
            ("name", name),
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
    )
    _finish_request(
        url,
        insecure,
        accepted,
        title="Organization renamed",
        expect_name=name,
        removal=False,
        wait=wait,
        timeout=timeout,
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
            ui.note(f"Organization {resource_id} is already {state}. Nothing to do.")
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
    )
    _finish_request(
        url,
        insecure,
        accepted,
        title="Organization protected" if protected else "Organization unprotected",
        expect_name=None,
        removal=False,
        wait=wait,
        timeout=timeout,
    )


@organization_app.command(
    "protect",
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
    )
    if resource_id == _active_organization():
        ui.warning(
            "This is the active Organization. Once it is gone, point to another with "
            f"`sk config set {ACTIVE_ORGANIZATION_KEY} VALUE`."
        )
    _finish_request(
        url,
        insecure,
        accepted,
        title="Organization deleted",
        expect_name=None,
        removal=True,
        wait=wait,
        timeout=timeout,
    )


@organization_app.command(
    "get",
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
        operation_id = _identifier(operation_id, "--operation-id", what="operationId")
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
    ui.panel("Organization", rows)


@organization_app.command("list", help=command("List the requester's Organizations."))
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
        ui.note("No Organizations.")
        return
    active = _active_organization()
    ui.table(
        "Organizations",
        ["active", "resourceId", "name", "state", "phase"],
        [
            [
                "*" if organization.resource_id == active else "",
                organization.resource_id,
                organization.name,
                _styled_state(organization),
                _styled_phase(organization),
            ]
            for organization in organizations
        ],
    )
