"""Comandos `sk sum service`: ligar, desligar e consultar os serviços do solicitante (decisão 0033).

Usam o token da sessão (`sk auth login`), renovado quando está para vencer. A API é a mesma do
`sk register` (`[core] apiUrl`). Ligar e desligar são assíncronos: o comando confirma o aceite e
mostra como acompanhar a Operation.
"""

import uuid
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from sk import ui
from sk.ajuda import comando, opcao
from sk.api import ApiRejectedError, ApiUnavailableError
from sk.credentials import default_credentials_path
from sk.session import SessionError, current_access_token
from sk.settings import ConfigurationError, SkSettings
from sk.sum_service import (
    OperationStatus,
    ServiceLink,
    disable_service,
    enable_service,
    get_operation,
    get_service,
    list_services,
)

EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2

AJUDA_SUM = comando("Serviços do Service Usage Manager (SUM).")
AJUDA_SERVICE = comando("Liga, desliga e consulta os serviços do solicitante.")

sum_app = typer.Typer(
    help=AJUDA_SUM,
    no_args_is_help=True,
    # Ajuda colorida pelo Rich. Colchetes literais nos textos são escapados com "\\[".
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
service_app = typer.Typer(
    help=AJUDA_SERVICE,
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
sum_app.add_typer(service_app, name="service")


def _core() -> tuple[str, bool]:
    """Endereço da API e permissão de HTTP, da seção `[core]` (ou das variáveis `SK_CORE_*`)."""
    try:
        core = SkSettings().core
    except (ValidationError, ConfigurationError) as error:
        ui.error("Configuração inválida", str(error), hint="Corrija o arquivo e repita.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    if not core.api_url:
        ui.error(
            "API não informada",
            "Informe-a em [core] apiUrl ou na variável SK_CORE_API_URL.",
            hint="Rode `sk init` para criar a configuração.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return core.api_url, core.allow_insecure_http


def _token(allow_insecure_http: bool) -> str:
    try:
        return current_access_token(
            default_credentials_path(), allow_insecure_http=allow_insecure_http
        )
    except SessionError as error:
        ui.error("Sessão indisponível", str(error), hint="Rode `sk auth login`.")
        raise typer.Exit(EXIT_FAILURE) from error


def _fail_api(error: ApiRejectedError | ApiUnavailableError) -> NoReturn:
    if isinstance(error, ApiUnavailableError):
        ui.error("Serviço indisponível", str(error), hint="Repita em alguns minutos.")
        raise typer.Exit(EXIT_FAILURE) from error
    hints = {
        401: "A sessão não foi aceita. Rode `sk auth login`.",
        403: "Sua conta não tem a permissão para esta operação.",
        404: "Ligação não encontrada para a sua conta.",
        409: "A ligação mudou desde a última leitura. Consulte-a e tente de novo.",
        429: "Muitos pedidos. Aguarde e tente de novo.",
    }
    hint = hints.get(error.status, f"HTTP {error.status} ({error.error_code}).")
    ui.error("Pedido recusado pela API", str(error), hint=hint)
    raise typer.Exit(EXIT_USAGE_ERROR if error.status == 400 else EXIT_FAILURE) from error


def _phase_label(link: ServiceLink) -> str:
    return "desligado" if link.lifecycle == "absent" else "ligado"


def _operation_rows(operation: OperationStatus) -> list[tuple[str, str]]:
    rows = [("operationId", operation.operation_id), ("Situação", operation.operation_status)]
    if operation.reason is not None:
        rows.append(("Motivo", operation.reason))
    return rows


@service_app.command(
    "enable",
    help=comando("Liga um serviço para o solicitante. Acompanhe com `sk sum service get`."),
)
def enable_command(
    service: Annotated[
        str | None,
        typer.Option(
            "--service",
            help=opcao(
                "Nome do serviço, como no catálogo (por exemplo, ipm).",
                tipo="String",
                variavel=None,
                arquivo=None,
                padrao="nenhum",
            ),
        ),
    ] = None,
) -> None:
    if service is None:
        ui.error(
            "Opção obrigatória ausente",
            "Informe --service.",
            hint="Repita o comando com --service NOME.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    api_url, insecure = _core()
    token = _token(insecure)
    try:
        accepted = enable_service(
            api_url,
            token=token,
            service=service,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except (ApiRejectedError, ApiUnavailableError) as error:
        _fail_api(error)
    ui.panel(
        "Ligação solicitada",
        [
            ("Serviço", service),
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
    )
    ui.note(f"Acompanhe com `sk sum service get --resource-id {accepted.resource_id}`.")


@service_app.command(
    "disable",
    help=comando("Desliga uma ligação do solicitante, lendo a versão atual antes de pedir."),
)
def disable_command(
    resource_id: Annotated[
        str | None,
        typer.Option(
            "--resource-id",
            help=opcao(
                "resourceId da ligação (retornado por `enable` ou `list`).",
                tipo="String",
                variavel=None,
                arquivo=None,
                padrao="nenhum",
            ),
        ),
    ] = None,
) -> None:
    if resource_id is None:
        ui.error(
            "Opção obrigatória ausente",
            "Informe --resource-id.",
            hint="Repita o comando com --resource-id ID.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    api_url, insecure = _core()
    token = _token(insecure)
    try:
        current = get_service(
            api_url, token=token, resource_id=resource_id, allow_insecure_http=insecure
        )
        if current.lifecycle == "absent":
            ui.error(
                "Ligação já desligada",
                f"A ligação {resource_id} já está desligada.",
                hint="Consulte com `sk sum service get`.",
            )
            raise typer.Exit(EXIT_FAILURE)
        accepted = disable_service(
            api_url,
            token=token,
            resource_id=resource_id,
            resource_version=current.resource_version,
            allow_insecure_http=insecure,
        )
    except (ApiRejectedError, ApiUnavailableError) as error:
        _fail_api(error)
    ui.panel(
        "Desligamento solicitado",
        [
            ("Serviço", current.service),
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
    )
    ui.note(f"Acompanhe com `sk sum service get --resource-id {accepted.resource_id}`.")


@service_app.command(
    "get",
    help=comando("Mostra o estado de uma ligação e, se informado, de uma Operation."),
)
def get_command(
    resource_id: Annotated[
        str | None,
        typer.Option(
            "--resource-id",
            help=opcao(
                "resourceId da ligação.",
                tipo="String",
                variavel=None,
                arquivo=None,
                padrao="nenhum",
            ),
        ),
    ] = None,
    operation_id: Annotated[
        str | None,
        typer.Option(
            "--operation-id",
            help=opcao(
                "operationId de um pedido (retornado por `enable` ou `disable`).",
                tipo="String",
                variavel=None,
                arquivo=None,
                padrao="nenhum",
            ),
        ),
    ] = None,
) -> None:
    if resource_id is None:
        ui.error(
            "Opção obrigatória ausente",
            "Informe --resource-id.",
            hint="Repita o comando com --resource-id ID.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    api_url, insecure = _core()
    token = _token(insecure)
    try:
        link = get_service(
            api_url, token=token, resource_id=resource_id, allow_insecure_http=insecure
        )
        operation = (
            get_operation(
                api_url,
                token=token,
                resource_id=resource_id,
                operation_id=operation_id,
                allow_insecure_http=insecure,
            )
            if operation_id is not None
            else None
        )
    except (ApiRejectedError, ApiUnavailableError) as error:
        _fail_api(error)
    rows = [
        ("resourceId", link.resource_id),
        ("Serviço", link.service),
        ("Situação", _phase_label(link)),
        ("Fase", link.phase),
        ("Roles observadas", ", ".join(link.observed_roles) or "nenhuma"),
    ]
    if operation is not None:
        rows.extend(_operation_rows(operation))
    ui.panel("Ligação", rows)


@service_app.command("list", help=comando("Lista as ligações do solicitante."))
def list_command() -> None:
    api_url, insecure = _core()
    token = _token(insecure)
    try:
        links = list_services(api_url, token=token, allow_insecure_http=insecure)
    except (ApiRejectedError, ApiUnavailableError) as error:
        _fail_api(error)
    if not links:
        ui.note("Nenhuma ligação.")
        return
    ui.table(
        "Ligações",
        ["resourceId", "Serviço", "Situação", "Fase"],
        [[link.resource_id, link.service, _phase_label(link), link.phase] for link in links],
    )
