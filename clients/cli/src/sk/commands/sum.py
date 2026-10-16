"""Comandos `sk sum service`: ligar, desligar e consultar os serviços do solicitante (decisão 0033).

Usam o token da sessão (`sk auth login`), renovado quando está para vencer. A API é a mesma do
`sk register` (`[core] apiUrl`). Ligar e desligar são assíncronos: o comando confirma o aceite e
mostra como acompanhar a Operation. Com `--wait`, ele espera a ligação convergir e renova a sessão:
o token só traz as roles que existiam quando foi emitido, e as do serviço chegam depois do aceite.
"""

import time
import uuid
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError
from rich.text import Text

from sk import ui
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
from sk.http import ApiError, ApiRejectedError, ApiUnavailableError
from sk.identity.credentials import default_credentials_path
from sk.identity.oidc import OidcError
from sk.identity.session import SessionError, current_access_token, renew_session
from sk.settings import ConfigurationError, SkSettings

ApiUrlOption = Annotated[
    str | None,
    typer.Option(
        "--api-url",
        help=option(
            "Platform API address.",
            kind="String",
            variable="SK_CORE_API_URL",
            file="[core] apiUrl",
            default="none",
        ),
    ),
]
AllowInsecureHttpOption = Annotated[
    bool,
    typer.Option(
        "--allow-insecure-http",
        help=option(
            "Allow an address without HTTPS. Development only.",
            kind="Boolean",
            variable="SK_CORE_ALLOW_INSECURE_HTTP=true",
            file="[core] allowInsecureHttp = true",
            default="off",
        ),
    ),
]

WaitOption = Annotated[
    bool,
    typer.Option(
        "--wait",
        help=option(
            "Wait for the service to converge (phase Ready and Operation completed) and renew "
            "the session, "
            "so the token reflects the new roles.",
            kind="Boolean",
            variable=None,
            file=None,
            default="off",
        ),
    ),
]
TimeoutOption = Annotated[
    int,
    typer.Option(
        "--timeout",
        min=1,
        help=option(
            "Seconds to wait with --wait.",
            kind="Integer",
            variable=None,
            file=None,
            default="60",
        ),
    ),
]
DEFAULT_WAIT_TIMEOUT_SECONDS = 60
WAIT_POLL_SECONDS = 1.0

EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2

SUM_HELP = command("Services of the Service Usage Manager (SUM).")
SERVICE_HELP = command("Enable, disable and inspect the requester's services.")

sum_app = typer.Typer(
    help=SUM_HELP,
    no_args_is_help=True,
    # Ajuda colorida pelo Rich. Colchetes literais nos textos são escapados com "\\[".
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
service_app = typer.Typer(
    help=SERVICE_HELP,
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
sum_app.add_typer(service_app, name="service")


def _require(value: str | None, option_name: str) -> str:
    if value is None:
        ui.error(
            "Missing required option",
            f"Provide {option_name}.",
            hint=f"Repeat the command with {option_name} VALUE.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return value


def _identifier(value: str | None, option_name: str, *, what: str) -> str:
    """Opção obrigatória que é um identificador do contrato, recusada antes da chamada de rede."""
    try:
        return validate_identifier(_require(value, option_name), what=what)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint=f"Fix {option_name} and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _load_core(api_url: str | None, allow_insecure_http: bool) -> tuple[str, bool]:
    explicit = {
        key: value
        for key, value in {
            "api_url": api_url,
            "allow_insecure_http": allow_insecure_http or None,
        }.items()
        if value is not None
    }
    try:
        # Mesmo mecanismo do `sk register`: parâmetro → ambiente → arquivo → default.
        core = SkSettings(core=explicit).core  # pyright: ignore[reportArgumentType]
    except (ValidationError, ConfigurationError) as error:
        ui.error("Invalid configuration", str(error), hint="Fix the indicated file and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    if not core.api_url:
        ui.error(
            "API not provided",
            "Provide it with --api-url, SK_CORE_API_URL or apiUrl in the [core] table.",
            hint="Run `sk init` to create the configuration, or provide --api-url.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return core.api_url, core.allow_insecure_http


def _session_insecure(allow_insecure_http: bool) -> bool:
    """O provedor de identidade segue a permissão de HTTP da seção `[auth]`, além da opção."""
    return allow_insecure_http or SkSettings().auth.allow_insecure_http


def _token(allow_insecure_http: bool) -> str:
    try:
        return current_access_token(
            default_credentials_path(), allow_insecure_http=_session_insecure(allow_insecure_http)
        )
    except SessionError as error:
        ui.error("Session unavailable", str(error), hint="Run `sk auth login`.")
        raise typer.Exit(EXIT_FAILURE) from error


CONFLICT_ON_CHANGE = "The service changed since it was last read. Inspect it and try again."


def _fail_api(
    error: ApiError,
    *,
    not_found: str = "Service not found for your account.",
    conflict: str = CONFLICT_ON_CHANGE,
) -> NoReturn:
    """Mostra a falha da API e sai. `not_found` e `conflict` dizem o que o `404` e o `409`
    significam no comando."""
    if isinstance(error, ApiUnavailableError):
        ui.error("Service unavailable", str(error), hint="Try again in a few minutes.")
        raise typer.Exit(EXIT_FAILURE) from error
    if not isinstance(error, ApiRejectedError):  # pragma: no cover (subclasse sem tratamento)
        ui.error("API call failed", str(error))
        raise typer.Exit(EXIT_FAILURE) from error
    if error.status == 429:
        wait = error.retry_after_seconds
        ui.error(
            "Too many requests",
            str(error),
            hint=f"Wait {wait} seconds and repeat." if wait else "Wait and try again.",
        )
        raise typer.Exit(EXIT_FAILURE) from error
    hints = {
        401: "The session was not accepted. Run `sk auth login`.",
        403: "Your account does not have permission for this operation.",
        404: not_found,
        409: conflict,
    }
    hint = hints.get(error.status, f"HTTP {error.status} ({error.error_code}).")
    detail = f"{error.field}: {error}" if error.field else str(error)
    ui.error("Request refused by the API", detail, hint=hint)
    raise typer.Exit(EXIT_USAGE_ERROR if error.status == 400 else EXIT_FAILURE) from error


def _bad_address(error: OidcError) -> NoReturn:
    ui.error(
        "API address refused",
        str(error),
        hint="Use HTTPS, or --allow-insecure-http in development.",
    )
    raise typer.Exit(EXIT_USAGE_ERROR) from error


STATE_STYLES = {"enabled": "green", "disabled": "dim"}
PHASE_STYLES = {
    "Ready": "green",
    "Failed": "red",
}  # as demais fases (em andamento) ficam em amarelo


def _styled_state(link: ServiceLink) -> Text:
    label = _phase_label(link)
    return Text(label, style=STATE_STYLES[label])


def _styled_phase(link: ServiceLink) -> Text:
    return Text(link.phase, style=PHASE_STYLES.get(link.phase, "yellow"))


def _phase_label(link: ServiceLink) -> str:
    return "disabled" if link.lifecycle == "absent" else "enabled"


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
    ui.note(f"Waiting for convergence (up to {timeout} s)...")
    deadline = time.monotonic() + timeout
    while True:
        token = _token(insecure)
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
            _bad_address(error)
        except ApiError as error:
            _fail_api(error)
        if operation.operation_status in ("rejected", "failed"):
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
            ui.error(
                "Timed out",
                f"{timeout} s passed and the service is in phase {link.phase} "
                f"(Operation {operation.operation_status}).",
                hint=f"The request is still in progress: `sk sum service get --resource-id "
                f"{accepted.resource_id}`.",
            )
            raise typer.Exit(EXIT_FAILURE)
        time.sleep(WAIT_POLL_SECONDS)


def _renew_after_convergence(insecure: bool) -> bool:
    """Renova a sessão para o token refletir as roles novas. Falha vira aviso: o pedido já valeu."""
    try:
        renew_session(default_credentials_path(), allow_insecure_http=_session_insecure(insecure))
    except SessionError as error:
        ui.warning(
            f"Session not renewed ({error}). The token may not reflect the new roles: "
            "run `sk auth login`."
        )
        return False
    return True


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
            "is Ready, run `sk auth refresh` so the token reflects the new roles."
        )
        return
    link = _wait_for_convergence(url, insecure, accepted, enabled=enabled, timeout=timeout)
    renewed = _renew_after_convergence(insecure)
    ui.panel(
        "Service enabled" if enabled else "Service disabled",
        [
            ("resourceId", link.resource_id),
            ("service", link.service),
            ("state", _phase_label(link)),
            ("phase", link.phase),
            ("observedRoles", ", ".join(link.observed_roles) or "none"),
            ("session", "renewed" if renewed else "not renewed"),
        ],
    )


@service_app.command(
    "enable",
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
    api_url: ApiUrlOption = None,
    allow_insecure_http: AllowInsecureHttpOption = False,
) -> None:
    # Obrigatória por validação do próprio comando (não pelo Typer), para não exibir "[required]".
    service = _require(service, "--service")
    url, insecure = _load_core(api_url, allow_insecure_http)
    token = _token(insecure)
    try:
        accepted = enable_service(
            url,
            token=token,
            service=service,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        _bad_address(error)
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
    )
    _finish_request(url, insecure, accepted, enabled=True, wait=wait, timeout=timeout)


@service_app.command(
    "disable",
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
    api_url: ApiUrlOption = None,
    allow_insecure_http: AllowInsecureHttpOption = False,
) -> None:
    resource_id = _identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = _load_core(api_url, allow_insecure_http)
    token = _token(insecure)
    try:
        current = get_service(
            url, token=token, resource_id=resource_id, allow_insecure_http=insecure
        )
        if current.lifecycle == "absent":
            # Idempotente: desligar o que já está desligado não é erro.
            ui.note(f"Service {resource_id} is already disabled. Nothing to do.")
            return
        accepted = disable_service(
            url,
            token=token,
            resource_id=resource_id,
            resource_version=current.resource_version,
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        _bad_address(error)
    except ApiError as error:
        _fail_api(error)
    ui.panel(
        "Disablement requested",
        [
            ("service", current.service),
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
    )
    _finish_request(url, insecure, accepted, enabled=False, wait=wait, timeout=timeout)


@service_app.command(
    "get",
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
    api_url: ApiUrlOption = None,
    allow_insecure_http: AllowInsecureHttpOption = False,
) -> None:
    resource_id = _identifier(resource_id, "--resource-id", what="resourceId")
    if operation_id is not None:
        operation_id = _identifier(operation_id, "--operation-id", what="operationId")
    url, insecure = _load_core(api_url, allow_insecure_http)
    token = _token(insecure)
    try:
        link = get_service(url, token=token, resource_id=resource_id, allow_insecure_http=insecure)
    except OidcError as error:
        _bad_address(error)
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
            _bad_address(error)
        except ApiError as error:
            _fail_api(error, not_found="Operation not found for this service.")
    rows = [
        ("resourceId", link.resource_id),
        ("service", link.service),
        ("state", _phase_label(link)),
        ("phase", link.phase),
        ("observedRoles", ", ".join(link.observed_roles) or "none"),
    ]
    if operation is not None:
        rows.extend(_operation_rows(operation))
    ui.panel("Service", rows)


@service_app.command("list", help=command("List the requester's services."))
def list_command(
    api_url: ApiUrlOption = None,
    allow_insecure_http: AllowInsecureHttpOption = False,
) -> None:
    url, insecure = _load_core(api_url, allow_insecure_http)
    token = _token(insecure)
    try:
        links = list_services(url, token=token, allow_insecure_http=insecure)
    except OidcError as error:
        _bad_address(error)
    except ApiError as error:
        _fail_api(error)
    if not links:
        ui.note("No services.")
        return
    ui.table(
        "Services",
        ["resourceId", "service", "state", "phase"],
        [
            [link.resource_id, link.service, _styled_state(link), _styled_phase(link)]
            for link in links
        ],
    )
