"""Comandos `sk sum service`: ligar, desligar e consultar os serviços do solicitante (decisão 0033).

Usam o token da sessão (`sk auth login`), renovado quando está para vencer. A API é a mesma do
`sk account create` (`[api] url`). Ligar e desligar são assíncronos: o comando garante o
mostra como acompanhar a Operation. Com `--wait`, ele espera a ligação convergir e renova a sessão:
o token só traz as permissões que existiam quando foi emitido, e as do serviço chegam depois do
aceite.
"""

import time
import uuid
from typing import Annotated, NoReturn

import typer
from rich.text import Text

from sk import output, ui
from sk.command_app import SkTyper
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
    renew_after_convergence,
    require,
    session_token,
)
from sk.features.sum.service import (
    OperationStatus,
    ServiceLink,
    ServiceRequestAccepted,
    disable_service,
    enable_service,
    get_operation,
    get_service,
    list_services,
    validate_identifier,
)
from sk.help import command, option
from sk.http import ApiError, ApiRejectedError
from sk.identity.oidc import OidcError

WaitOption = Annotated[
    bool,
    typer.Option(
        "--wait",
        help=option(
            "Wait for the service to converge (phase Ready and Operation completed) and renew "
            "the session, "
            "so the token reflects the new permissions.",
            kind="Boolean",
            variable=None,
            file=None,
            default="off",
        ),
    ),
]
SUM_HELP = command("Resources of the Service Usage Manager (SUM).")
SERVICE_HELP = command("Enable, disable and inspect the requester's services.")

sum_app = SkTyper(
    help=SUM_HELP,
    no_args_is_help=True,
    # Ajuda colorida pelo Rich. Colchetes literais nos textos são escapados com "\\[".
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
service_app = SkTyper(
    help=SERVICE_HELP,
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
sum_app.add_typer(service_app, name="service")


def _identifier(value: str | None, option_name: str, *, what: str) -> str:
    """Opção obrigatória que é um identificador do contrato, recusada antes da chamada de rede."""
    try:
        return validate_identifier(require(value, option_name), what=what)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint=f"Fix {option_name} and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


CONFLICT_ON_CHANGE = "The service changed since it was last read. Inspect it and try again."


def _fail_api(
    error: ApiError,
    *,
    not_found: str = "Service not found for your account.",
    conflict: str = CONFLICT_ON_CHANGE,
) -> NoReturn:
    fail_api(
        error,
        not_found=not_found,
        conflict=conflict,
        by_error_code={
            "ResourcesAttached": (
                "The service still has Organizations. Delete them first "
                "(`sk ipm organization delete`) and repeat."
            ),
            "ResourcesNotVerifiable": (
                "The attached resources could not be verified. "
                "Renew the session with `sk auth refresh` and repeat."
            ),
        },
    )


PHASE_STYLES = {
    "Ready": "green",
    "Failed": "red",
}  # as demais fases (em andamento) ficam em amarelo


def _styled_phase(link: ServiceLink) -> Text:
    return Text(link.phase, style=PHASE_STYLES.get(link.phase, "yellow"))


def _phase_label(link: ServiceLink) -> str:
    return "disabled" if link.lifecycle == "absent" else "enabled"


def _timed_out(
    timeout: int, accepted: ServiceRequestAccepted, state: str = "is not visible yet"
) -> NoReturn:
    ui.error(
        "Timed out",
        f"{timeout} s passed and the service {state}.",
        hint=f"The request is still in progress: `sk sum service get --resource-id "
        f"{accepted.resource_id}`.",
    )
    raise typer.Exit(EXIT_FAILURE)


def _wait_for_convergence(
    url: str,
    insecure: bool,
    accepted: ServiceRequestAccepted,
    *,
    enabled: bool,
    timeout: int,
) -> ServiceLink:
    """Espera a ligação em `Ready` e a Operation `completed`; se não der, sai dizendo por quê.

    O token é pedido a cada leitura: o acesso dura 15 minutos, e uma espera longa (`--timeout`)
    pode atravessar o vencimento (a sessão se renova pelo refresh token).
    """
    with ui.waiting(timeout) as progress:
        progress.update("Operation submitted")
        deadline = time.monotonic() + timeout
        while True:
            token = session_token()
            try:
                operation = get_operation(
                    url,
                    token=token,
                    resource_id=accepted.resource_id,
                    operation_id=accepted.operation_id,
                    allow_insecure_http=insecure,
                )
                link = get_service(
                    url, token=token, resource_id=accepted.resource_id, allow_insecure_http=insecure
                )
            except OidcError as error:
                bad_address(error)
            except ApiRejectedError as error:
                if error.status != HTTP_NOT_FOUND:
                    _fail_api(error)
                # Logo depois do `202`, o Manager ainda pode não ter gravado a Operation e o recurso
                # (`docs/loop/RESOURCE-CONTROL-LOOP.md` §6.1.1): é espera, e não erro.
                if time.monotonic() >= deadline:
                    _timed_out(timeout, accepted)
                time.sleep(WAIT_POLL_SECONDS)
                continue
            except ApiError as error:
                _fail_api(error)
            progress.update(f"phase {link.phase}, Operation {operation.operation_status}")
            if operation.operation_status in ("rejected", "failed", "superseded"):
                ui.error(
                    "Request not completed",
                    f"The Operation ended as {operation.operation_status}"
                    + (f": {operation.reason}" if operation.reason else "."),
                    hint="Inspect it with `sk sum service get`.",
                )
                raise typer.Exit(EXIT_FAILURE)
            reached = (link.lifecycle != "absent") == enabled
            if operation.operation_status == "completed" and link.phase == "Ready" and reached:
                return link
            if time.monotonic() >= deadline:
                _timed_out(
                    timeout,
                    accepted,
                    f"is in phase {link.phase} (Operation {operation.operation_status})",
                )
            time.sleep(WAIT_POLL_SECONDS)


def _operation_rows(operation: OperationStatus) -> list[tuple[str, str]]:
    rows = [
        ("operationId", operation.operation_id),
        ("operationStatus", operation.operation_status),
    ]
    if operation.reason is not None:
        rows.append(("reason", operation.reason))
    return rows


def _finish_request(
    url: str,
    insecure: bool,
    accepted: ServiceRequestAccepted,
    *,
    enabled: bool,
    wait: bool,
    timeout: int,
) -> None:
    """Fim de `enable` e `disable`: orienta o acompanhamento ou, com `--wait`, espera e renova."""
    if not wait:
        ui.note(
            f"Follow it with `sk sum service get --resource-id {accepted.resource_id}`. "
            "Once the phase "
            "is Ready, run `sk auth refresh` so the token reflects the new permissions."
        )
        return
    link = _wait_for_convergence(url, insecure, accepted, enabled=enabled, timeout=timeout)
    renewed = renew_after_convergence()
    ui.panel(
        "Service enabled" if enabled else "Service disabled",
        [
            ("resourceId", link.resource_id),
            ("service", link.service),
            ("state", _phase_label(link)),
            ("phase", link.phase),
            ("observedPermissions", ", ".join(link.observed_permissions) or "none"),
            ("session", "renewed" if renewed else "not renewed"),
        ],
        data={**output.to_data(link), "sessionRenewed": renewed},
    )


@service_app.command(
    "enable",
    structured=True,
    help=command("Enable a service for the requester. Follow it with `sk sum service get`."),
)
def enable_command(
    service: Annotated[
        str | None,
        typer.Option(
            "--service",
            help=option(
                "Service name, as in the catalog (for example, ipm).",
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
    service = require(service, "--service")
    url, insecure = load_api()
    token = session_token()
    try:
        accepted = enable_service(
            url,
            token=token,
            service=service,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(
            error, conflict="This service is already enabled. See it with `sk sum service list`."
        )
    ui.panel(
        "Enablement requested",
        [
            ("service", service),
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
        data=accepted,
        interim=wait,
    )
    _finish_request(url, insecure, accepted, enabled=True, wait=wait, timeout=timeout)


@service_app.command(
    "disable",
    structured=True,
    help=command("Disable a requester's service, reading the current version before asking."),
)
def disable_command(
    resource_id: Annotated[
        str | None,
        typer.Option(
            "--resource-id",
            help=option(
                "resourceId of the service (returned by `enable` or `list`).",
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
    resource_id = _identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_service(
            url, token=token, resource_id=resource_id, allow_insecure_http=insecure
        )
        if current.lifecycle == "absent":
            # Idempotente: desligar o que já está desligado não é erro.
            ui.note(f"Service {resource_id} is already disabled. Nothing to do.")
            if output.is_json():
                output.emit(current)
            return
        accepted = disable_service(
            url,
            token=token,
            resource_id=resource_id,
            resource_version=current.resource_version,
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    ui.panel(
        "Disablement requested",
        [
            ("service", current.service),
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
        data=accepted,
        interim=wait,
    )
    _finish_request(url, insecure, accepted, enabled=False, wait=wait, timeout=timeout)


@service_app.command(
    "get",
    structured=True,
    help=command("Show the state of a service and, if given, of an Operation."),
)
def get_command(
    resource_id: Annotated[
        str | None,
        typer.Option(
            "--resource-id",
            help=option(
                "resourceId of the service.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    operation_id: Annotated[
        str | None,
        typer.Option(
            "--operation-id",
            help=option(
                "operationId of a request (returned by `enable` or `disable`).",
                kind="String",
                variable=None,
                file=None,
                default="no Operation lookup",
            ),
        ),
    ] = None,
) -> None:
    resource_id = _identifier(resource_id, "--resource-id", what="resourceId")
    if operation_id is not None:
        operation_id = _identifier(operation_id, "--operation-id", what="operationId")
    url, insecure = load_api()
    token = session_token()
    try:
        link = get_service(url, token=token, resource_id=resource_id, allow_insecure_http=insecure)
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
            _fail_api(error, not_found="Operation not found for this service.")
    rows = [
        ("resourceId", link.resource_id),
        ("service", link.service),
        ("state", _phase_label(link)),
        ("phase", link.phase),
        ("observedPermissions", ", ".join(link.observed_permissions) or "none"),
    ]
    if operation is not None:
        rows.extend(_operation_rows(operation))
    document = output.to_data(link)
    if operation is not None:
        document["operation"] = output.to_data(operation)
    ui.panel("Service", rows, data=document)


@service_app.command("list", structured=True, help=command("List the requester's services."))
def list_command() -> None:
    url, insecure = load_api()
    token = session_token()
    try:
        links = list_services(url, token=token, allow_insecure_http=insecure)
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    if not links:
        ui.empty("No services.")
        return
    ui.table(
        "Services",
        ["name", "resourceId", "phase"],
        [[link.service, link.resource_id, _styled_phase(link)] for link in links],
        data=links,
    )
