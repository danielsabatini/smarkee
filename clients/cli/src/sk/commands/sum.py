"""Comandos `sk sum service`: ligar, desligar e consultar os serviços do solicitante (decisão 0033).

Usam o token da sessão (`sk auth login`), renovado quando está para vencer. A API é a mesma do
`sk account create` (`[api] url`). Ligar e desligar são escritas síncronas (decisão 0098): a API
admite o pedido e devolve a ligação, e o Controller converge o Zitadel depois. Com `--wait`, o
comando espera a ligação convergir (`observedGeneration` alcança `desiredGeneration`, fase `Ready`)
e renova a sessão: o token só traz as permissões que existiam quando foi emitido, e as do serviço
chegam depois do aceite.
"""

import uuid
from typing import Annotated, NoReturn

import typer
from rich.text import Text

from sk import output, ui
from sk.command_app import SkTyper
from sk.commands.shared import (
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    EXIT_USAGE_ERROR,
    SyncResourceFlow,
    TimeoutOption,
    already_done,
    bad_address,
    fail_api,
    load_api,
    renew_after_convergence,
    require,
    session_token,
)
from sk.features.sum.service import (
    ServiceLink,
    disable_service,
    enable_service,
    get_service,
    list_available_services,
    list_services,
    validate_identifier,
)
from sk.help import command, option
from sk.http import ApiError
from sk.identity.oidc import OidcError

WaitOption = Annotated[
    bool,
    typer.Option(
        "--wait/--no-wait",
        help=option(
            "Wait for the service to converge (generation observed and phase Ready) and renew "
            "the session, so the token reflects the new permissions (default on).",
            kind="Boolean",
            variable=None,
            file=None,
            default="on",
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
            "AlreadyEnabled": "This service is already enabled. See it with `sk sum service list`.",
            "ServiceNotAvailable": "This service is not available. Check the name in the catalog.",
            "BillingAccountRequired": (
                "Enabling a service requires a Billing Account. "
                "Create one first (`sk bsm account create`) and repeat."
            ),
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


def _rows(link: ServiceLink) -> list[tuple[str, str]]:
    return [
        ("resourceId", link.resource_id),
        ("service", link.service),
        ("state", _phase_label(link)),
        ("phase", link.phase),
        ("observedPermissions", ", ".join(link.observed_permissions) or "none"),
    ]


def _get_command(resource_id: str) -> str:
    return f"sk sum service get --resource-id {resource_id}"


_flow = SyncResourceFlow(
    subject="service",
    get_command=_get_command,
    read_resource=get_service,
    fail_api=_fail_api,
    rows=_rows,
)


def _finish_request(
    url: str, insecure: bool, admitted: ServiceLink, *, enabled: bool, wait: bool, timeout: int
) -> None:
    """Fim de `enable` e `disable`: orienta o acompanhamento ou, com `--wait`, espera e renova."""
    if not wait:
        ui.note(
            f"Follow it with `{_get_command(admitted.resource_id)}`. Once the phase "
            "is Ready, run `sk auth refresh` so the token reflects the new permissions."
        )
        return
    link = _flow.wait_for_convergence(url, insecure, admitted, removal=False, timeout=timeout)
    if link is None:  # sem remoção a espera sempre devolve o recurso; protege o tipo
        return
    renewed = renew_after_convergence()
    ui.panel(
        "Service enabled" if enabled else "Service disabled",
        [*_rows(link), ("session", "renewed" if renewed else "not renewed")],
        data={**output.to_data(link), "sessionRenewed": renewed},
    )


@service_app.command(
    "enable",
    structured=True,
    help=command(
        "Enable a service for the requester. Follow it with `sk sum service get`.",
        examples=["sk sum service enable --service ipm --wait"],
    ),
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
    wait: WaitOption = True,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    # Obrigatória por validação do próprio comando (não pelo Typer), para não exibir "[required]".
    service = require(service, "--service")
    url, insecure = load_api()
    token = session_token()
    try:
        admitted = enable_service(
            url,
            token=token,
            service=service,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _flow.requested_panel("Enablement requested", admitted, ("service", service), wait=wait)
    _finish_request(url, insecure, admitted, enabled=True, wait=wait, timeout=timeout)


@service_app.command(
    "disable",
    structured=True,
    help=command(
        "Disable a requester's service, reading the current version before asking.",
        examples=["sk sum service disable --resource-id srv-123456 --wait"],
    ),
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
    wait: WaitOption = True,
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
            already_done(current, f"Service {resource_id} is already disabled. Nothing to do.")
            return
        admitted = disable_service(
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
    _flow.requested_panel(
        "Disablement requested", admitted, ("service", current.service), wait=wait
    )
    _finish_request(url, insecure, admitted, enabled=False, wait=wait, timeout=timeout)


@service_app.command(
    "get",
    structured=True,
    help=command(
        "Show the state of a service.",
        examples=[
            "sk sum service get --resource-id srv-123456",
            "sk --output json sum service get --resource-id srv-123456",
        ],
    ),
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
) -> None:
    resource_id = _identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        link = get_service(url, token=token, resource_id=resource_id, allow_insecure_http=insecure)
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    ui.panel("Service", _rows(link), data=link)


STATE_STYLES = {
    "enabled": "green",
    "available": "cyan",
}


def _styled_state(state: str) -> Text:
    return Text(state, style=STATE_STYLES.get(state, "white"))


@service_app.command(
    "list",
    structured=True,
    help=command(
        "List the requester's services or available services in the catalog.",
        examples=[
            "sk sum service list",
            "sk sum service list --available",
            "sk --output json sum service list --available",
        ],
    ),
)
def list_command(
    available: Annotated[
        bool,
        typer.Option(
            "--available",
            "-a",
            help=option(
                "List all available services in the platform catalog.",
                kind="Boolean",
                variable=None,
                file=None,
                default="off",
            ),
        ),
    ] = False,
    enabled: Annotated[
        bool,
        typer.Option(
            "--enabled",
            help=option(
                "List only enabled services for the requester (default).",
                kind="Boolean",
                variable=None,
                file=None,
                default="on",
            ),
        ),
    ] = False,
) -> None:
    del enabled  # o modo enabled é o padrão quando --available não for passado
    url, insecure = load_api()
    token = session_token()
    if available:
        try:
            catalog = list_available_services(url, token=token, allow_insecure_http=insecure)
        except OidcError as error:
            bad_address(error)
        except ApiError as error:
            _fail_api(error)
        if not catalog:
            ui.empty("No available services.")
            return
        ui.table(
            "Available Services",
            ["name", "title", "state", "description"],
            [
                [svc.name, svc.title, _styled_state(svc.state), svc.description or ""]
                for svc in catalog
            ],
            wrap=["description"],
            data=catalog,
        )
        return

    try:
        links = list_services(url, token=token, allow_insecure_http=insecure)
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    if not links:
        ui.empty(
            "No services enabled.",
            hint="Run `sk sum service list --available` to see services available to enable.",
        )
        return
    ui.table(
        "Services",
        ["name", "resourceId", "phase"],
        [[link.service, link.resource_id, _styled_phase(link)] for link in links],
        data=links,
    )
