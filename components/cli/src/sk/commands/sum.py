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
from sk.features.sum.service import (
    OperationStatus,
    ServiceLink,
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
from sk.identity.session import SessionError, current_access_token
from sk.settings import ConfigurationError, SkSettings

ApiUrlOption = Annotated[
    str | None,
    typer.Option(
        "--api-url",
        help=option(
            "Endereço da API da plataforma.",
            kind="String",
            variable="SK_CORE_API_URL",
            file="[core] apiUrl",
            default="nenhum",
        ),
    ),
]
AllowInsecureHttpOption = Annotated[
    bool,
    typer.Option(
        "--allow-insecure-http",
        help=option(
            "Permite endereço sem HTTPS. Somente para desenvolvimento.",
            kind="Booleano",
            variable="SK_CORE_ALLOW_INSECURE_HTTP=true",
            file="[core] allowInsecureHttp = true",
            default="desativado",
        ),
    ),
]

EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2

SUM_HELP = command("Serviços do Service Usage Manager (SUM).")
SERVICE_HELP = command("Liga, desliga e consulta os serviços do solicitante.")

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
            "Opção obrigatória ausente",
            f"Informe {option_name}.",
            hint=f"Repita o comando com {option_name} VALOR.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return value


def _identifier(value: str | None, option_name: str, *, what: str) -> str:
    """Opção obrigatória que é um identificador do contrato, recusada antes da chamada de rede."""
    try:
        return validate_identifier(_require(value, option_name), what=what)
    except ValueError as error:
        ui.error("Dados não aceitos", str(error), hint=f"Corrija {option_name} e repita.")
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
        ui.error("Configuração inválida", str(error), hint="Corrija o arquivo indicado e repita.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    if not core.api_url:
        ui.error(
            "API não informada",
            "Informe-a por --api-url, SK_CORE_API_URL ou apiUrl na tabela [core].",
            hint="Rode `sk init` para criar a configuração, ou informe --api-url.",
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


def _fail_api(
    error: ApiError, *, not_found: str = "Ligação não encontrada para a sua conta."
) -> NoReturn:
    """Mostra a falha da API e sai. `not_found` diz o que o `404` significa no comando."""
    if isinstance(error, ApiUnavailableError):
        ui.error("Serviço indisponível", str(error), hint="Repita em alguns minutos.")
        raise typer.Exit(EXIT_FAILURE) from error
    if not isinstance(error, ApiRejectedError):  # pragma: no cover (subclasse sem tratamento)
        ui.error("Falha na chamada à API", str(error))
        raise typer.Exit(EXIT_FAILURE) from error
    if error.status == 429:
        wait = error.retry_after_seconds
        ui.error(
            "Muitas tentativas",
            str(error),
            hint=f"Aguarde {wait} segundos e repita." if wait else "Aguarde e tente de novo.",
        )
        raise typer.Exit(EXIT_FAILURE) from error
    hints = {
        401: "A sessão não foi aceita. Rode `sk auth login`.",
        403: "Sua conta não tem a permissão para esta operação.",
        404: not_found,
        409: "A ligação mudou desde a última leitura. Consulte-a e tente de novo.",
    }
    hint = hints.get(error.status, f"HTTP {error.status} ({error.error_code}).")
    detail = f"{error.field}: {error}" if error.field else str(error)
    ui.error("Pedido recusado pela API", detail, hint=hint)
    raise typer.Exit(EXIT_USAGE_ERROR if error.status == 400 else EXIT_FAILURE) from error


def _bad_address(error: OidcError) -> NoReturn:
    ui.error(
        "Endereço da API recusado",
        str(error),
        hint="Use HTTPS ou --allow-insecure-http em desenvolvimento.",
    )
    raise typer.Exit(EXIT_USAGE_ERROR) from error


def _phase_label(link: ServiceLink) -> str:
    return "desligado" if link.lifecycle == "absent" else "ligado"


def _operation_rows(operation: OperationStatus) -> list[tuple[str, str]]:
    rows = [("operationId", operation.operation_id), ("Situação", operation.operation_status)]
    if operation.reason is not None:
        rows.append(("Motivo", operation.reason))
    return rows


@service_app.command(
    "enable",
    help=command("Liga um serviço para o solicitante. Acompanhe com `sk sum service get`."),
)
def enable_command(
    service: Annotated[
        str | None,
        typer.Option(
            "--service",
            help=option(
                "Nome do serviço, como no catálogo (por exemplo, ipm).",
                kind="String",
                variable=None,
                file=None,
                default="nenhum",
            ),
        ),
    ] = None,
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
    help=command("Desliga uma ligação do solicitante, lendo a versão atual antes de pedir."),
)
def disable_command(
    resource_id: Annotated[
        str | None,
        typer.Option(
            "--resource-id",
            help=option(
                "resourceId da ligação (retornado por `enable` ou `list`).",
                kind="String",
                variable=None,
                file=None,
                default="nenhum",
            ),
        ),
    ] = None,
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
            ui.note(f"A ligação {resource_id} já está desligada. Nada a fazer.")
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
    help=command("Mostra o estado de uma ligação e, se informado, de uma Operation."),
)
def get_command(
    resource_id: Annotated[
        str | None,
        typer.Option(
            "--resource-id",
            help=option(
                "resourceId da ligação.",
                kind="String",
                variable=None,
                file=None,
                default="nenhum",
            ),
        ),
    ] = None,
    operation_id: Annotated[
        str | None,
        typer.Option(
            "--operation-id",
            help=option(
                "operationId de um pedido (retornado por `enable` ou `disable`).",
                kind="String",
                variable=None,
                file=None,
                default="sem consulta à Operation",
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
            _fail_api(error, not_found="Operation não encontrada para esta ligação.")
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


@service_app.command("list", help=command("Lista as ligações do solicitante."))
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
        ui.note("Nenhuma ligação.")
        return
    ui.table(
        "Ligações",
        ["resourceId", "Serviço", "Situação", "Fase"],
        [[link.resource_id, link.service, _phase_label(link), link.phase] for link in links],
    )
