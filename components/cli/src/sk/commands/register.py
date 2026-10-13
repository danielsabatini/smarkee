"""Comando `sk register`: pede o cadastro de um usuário na plataforma.

É anônimo: não exige login e não envia token. A senha não é pedida nem aceita: ela é definida
pela própria pessoa, na página do provedor de identidade, a partir do e-mail de ativação
(`docs/RESOURCE-CONTROL-LOOP.md`, seção 46.1). O cadastro é assíncrono: o comando confirma que o
pedido foi aceito, e não que a conta já existe.
"""

from typing import Annotated

import typer
from pydantic import ValidationError

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
        typer.echo(f"Erro na configuração: {error}", err=True)
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    if not core.api_url:
        typer.echo(
            "Erro: informe a API por --api-url, SK_CORE_API_URL ou apiUrl na tabela [core] "
            "do arquivo de configuração.",
            err=True,
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
            help="URL base da API do módulo core. [dim cyan](substitui SK_CORE_API_URL)[/]",
        ),
    ] = None,
    allow_insecure_http: Annotated[
        bool,
        typer.Option(
            "--allow-insecure-http",
            help="Aceita a API em HTTP (somente em desenvolvimento).",
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
        typer.echo(f"Erro: {error}", err=True)
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    except OidcError as error:
        typer.echo(f"Erro: {error}", err=True)
        raise typer.Exit(EXIT_FAILURE) from error
    except ApiRejectedError as error:
        if error.status == 429:
            wait = error.retry_after_seconds
            hint = f" Aguarde {wait} segundos e repita." if wait else " Tente novamente depois."
            typer.echo(f"Muitas tentativas.{hint}", err=True)
        elif error.field:
            typer.echo(f"Erro: campo inválido: {error.field}. {error}", err=True)
        else:
            typer.echo(f"Erro: {error}", err=True)
        raise typer.Exit(EXIT_USAGE_ERROR if error.status == 400 else EXIT_FAILURE) from error
    except ApiUnavailableError as error:
        typer.echo(f"Serviço indisponível: {error}. Repita em alguns minutos.", err=True)
        raise typer.Exit(EXIT_FAILURE) from error
    except ApiError as error:  # pragma: no cover (cobertura de segurança: nova subclasse)
        typer.echo(f"Erro: {error}", err=True)
        raise typer.Exit(EXIT_FAILURE) from error

    typer.echo("Cadastro solicitado.")
    typer.echo(f"resourceId: {accepted.resource_id}")
    typer.echo(f"operationId: {accepted.operation_id}")
    typer.echo(
        "Verifique o seu e-mail: o provedor envia a confirmação e o link para definir a senha."
    )
