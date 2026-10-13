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
from sk.ajuda import comando, opcao
from sk.api import (
    ApiError,
    ApiRejectedError,
    ApiUnavailableError,
    submit_registration,
    validate_registration,
)
from sk.oidc import OidcError
from sk.settings import ConfigurationError, SkSettings

AJUDA_REGISTRO = comando(
    "Cadastra uma nova conta para iniciar na plataforma. "
    "Depois, confirme o e-mail e defina a senha pelos links enviados para ele."
)

EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2


def _exige(valor: str | None, nome_opcao: str) -> str:
    if valor is None:
        ui.error(
            "Opção obrigatória ausente",
            f"Informe {nome_opcao}.",
            hint=f"Repita o comando com {nome_opcao} VALOR.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return valor


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
            hint="Rode `sk init` para criar a configuração, ou informe --api-url.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return core.api_url, core.allow_insecure_http


def register_command(
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            help=opcao(
                "Nome (até 256 caracteres).",
                tipo="String",
                variavel=None,
                arquivo=None,
                padrao="nenhum",
            ),
        ),
    ] = None,
    surname: Annotated[
        str | None,
        typer.Option(
            "--surname",
            help=opcao(
                "Sobrenome (até 256 caracteres).",
                tipo="String",
                variavel=None,
                arquivo=None,
                padrao="nenhum",
            ),
        ),
    ] = None,
    email: Annotated[
        str | None,
        typer.Option(
            "--email",
            help=opcao(
                "E-mail da conta. É também o nome de login.",
                tipo="String",
                variavel=None,
                arquivo=None,
                padrao="nenhum",
            ),
        ),
    ] = None,
    api_url: Annotated[
        str | None,
        typer.Option(
            "--api-url",
            help=opcao(
                "Endereço da API da plataforma.",
                tipo="String",
                variavel="SK_CORE_API_URL",
                arquivo="[core] apiUrl",
                padrao="nenhum",
            ),
        ),
    ] = None,
    allow_insecure_http: Annotated[
        bool,
        typer.Option(
            "--allow-insecure-http",
            help=opcao(
                "Permite endereço sem HTTPS. Somente para desenvolvimento.",
                tipo="Booleano",
                variavel="SK_CORE_ALLOW_INSECURE_HTTP=true",
                arquivo="[core] allowInsecureHttp = true",
                padrao="desativado",
            ),
        ),
    ] = False,
) -> None:
    # Obrigatórias por validação do próprio comando (não pelo Typer), para não exibir "[required]".
    name = _exige(name, "--name")
    surname = _exige(surname, "--surname")
    email = _exige(email, "--email")
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
