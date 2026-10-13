"""Comando `sk register`: pede o cadastro de um usuário na plataforma.

É anônimo: não exige login e não envia token. A senha não é pedida nem aceita: ela é definida
pela própria pessoa, na página do provedor de identidade, a partir do e-mail de ativação
(`docs/RESOURCE-CONTROL-LOOP.md`, seção 46.1). O cadastro é assíncrono: o comando confirma que o
pedido foi aceito, e não que a conta já existe.
"""

from typing import Annotated

import typer
from pydantic import ValidationError

from sk import ui
from sk.api import (
    ApiError,
    ApiRejectedError,
    ApiUnavailableError,
    submit_registration,
    validate_registration,
)
from sk.oidc import OidcError
from sk.settings import ConfigurationError, SkSettings

EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2


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
        # Mesmo mecanismo do `sk auth`: parâmetro → ambiente → arquivo → default.
        core = SkSettings(core=explicit).core  # pyright: ignore[reportArgumentType]
    except (ValidationError, ConfigurationError) as error:
        ui.error("Configuração inválida", str(error), hint="Corrija o arquivo indicado e repita.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    if not core.api_url:
        ui.error(
            "API não informada",
            "Informe-a por --api-url, SK_CORE_API_URL ou apiUrl na tabela [core].",
            hint="Adicione [core] com apiUrl ao arquivo de configuração do sk.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return core.api_url, core.allow_insecure_http


def register_command(
    name: Annotated[str, typer.Option("--name", help="Nome próprio da pessoa.")],
    surname: Annotated[str, typer.Option("--surname", help="Sobrenome da pessoa.")],
    email: Annotated[
        str, typer.Option("--email", help="E-mail da pessoa; é também o nome de login.")
    ],
    api_url: Annotated[
        str | None,
        typer.Option(
            "--api-url",
            help=(
                "URL base da API do módulo core. Também por SK_CORE_API_URL ou apiUrl na "
                "tabela \\[core]. Padrão: nenhum."
            ),
        ),
    ] = None,
    allow_insecure_http: Annotated[
        bool,
        typer.Option(
            "--allow-insecure-http",
            help="Aceita a API em HTTP (somente em desenvolvimento). Booleano. Padrão: desativado.",
        ),
    ] = False,
) -> None:
    """Pede o cadastro de um usuário. Depois, a pessoa ativa a conta pelo e-mail do provedor."""
    url, insecure = _load_core(api_url, allow_insecure_http)
    try:
        # Validação local antes de qualquer chamada: o comando, e não só o cliente, a garante.
        validate_registration(name, surname, email)
        accepted = submit_registration(
            url,
            given_name=name,
            family_name=surname,
            email=email,
            allow_insecure_http=insecure,
        )
    except ValueError as error:
        ui.error("Dados não aceitos", str(error), hint="Corrija o valor informado e repita.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    except OidcError as error:
        ui.error(
            "Endereço da API recusado",
            str(error),
            hint="Use HTTPS ou --allow-insecure-http em desenvolvimento.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    except ApiRejectedError as error:
        if error.status == 429:
            wait = error.retry_after_seconds
            ui.error(
                "Muitas tentativas",
                "O cadastro tem limite de pedidos por origem.",
                hint=f"Aguarde {wait} segundos e repita." if wait else "Tente novamente depois.",
            )
            raise typer.Exit(EXIT_FAILURE) from error
        if error.field:
            ui.error(
                "Campo recusado pela API",
                f"{error.field}: {error}",
                hint="Corrija o campo e repita.",
            )
            raise typer.Exit(EXIT_USAGE_ERROR if error.status == 400 else EXIT_FAILURE) from error
        ui.error(
            "Pedido recusado pela API",
            str(error),
            hint=f"HTTP {error.status} ({error.error_code}).",
        )
        raise typer.Exit(EXIT_USAGE_ERROR if error.status == 400 else EXIT_FAILURE) from error
    except ApiUnavailableError as error:
        ui.error("Serviço indisponível", str(error), hint="Repita em alguns minutos.")
        raise typer.Exit(EXIT_FAILURE) from error
    except ApiError as error:  # pragma: no cover (nova subclasse sem tratamento explícito)
        ui.error("Falha no cadastro", str(error))
        raise typer.Exit(EXIT_FAILURE) from error

    ui.panel(
        "Cadastro solicitado",
        [
            ("Nome", f"{name.strip()} {surname.strip()}"),
            ("E-mail", email.strip()),
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
    )
    ui.note(
        "Próximos passos: confirme o e-mail e defina a senha pelos links que o provedor enviou. "
        "Depois, rode `sk auth login`."
    )
