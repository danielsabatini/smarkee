"""Comando `sk init`: cria o arquivo de configuração com os endereços de produção.

O arquivo passa a ser o ponto de partida da CLI. Depois, `sk config` altera valores. Parâmetros
e variáveis `SK_*` sobrescrevem o que for gravado, na ordem da decisão 0008; o padrão é o de
produção (`sk.defaults`).
"""

from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError

from sk import ui
from sk.defaults import CLIENT_ID_PROVISORIO, PRD_API_URL, PRD_ISSUER
from sk.files import write_private_file
from sk.help import ORDEM_SEM_ARQUIVO, comando, opcao
from sk.identity.oidc import OidcError, ensure_secure_url
from sk.settings import (
    AuthSettings,
    ConfigurationError,
    CoreSettings,
    SkSettingsWithoutConfigFile,
    config_file_path,
    render_section,
)

EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2

AJUDA_INIT = comando(
    "Cria o arquivo de configuração da plataforma, com os endereços de produção. "
    "Não sobrescreve um arquivo existente sem --force.",
    ordem=ORDEM_SEM_ARQUIVO,
)


def _ajuda_issuer() -> str:
    return opcao(
        "Endereço do provedor de login.",
        tipo="String",
        variavel="SK_AUTH_ISSUER",
        arquivo=None,
        padrao=PRD_ISSUER,
    )


def _ajuda_client_id() -> str:
    return opcao(
        "Identificador do sk no provedor de login. Provisório até o ambiente de produção existir.",
        tipo="String",
        variavel="SK_AUTH_CLIENT_ID",
        arquivo=None,
        padrao=CLIENT_ID_PROVISORIO,
    )


def _ajuda_api_url() -> str:
    return opcao(
        "Endereço da API da plataforma.",
        tipo="String",
        variavel="SK_CORE_API_URL",
        arquivo=None,
        padrao=PRD_API_URL,
    )


def _ajuda_allow_insecure_http() -> str:
    return opcao(
        "Permite endereço sem HTTPS. Somente para desenvolvimento.",
        tipo="Booleano",
        variavel="SK_AUTH_ALLOW_INSECURE_HTTP=true",
        arquivo=None,
        padrao="desativado",
    )


def _exit_on_configuration_error(error: Exception) -> NoReturn:
    ui.error("Configuração inválida", str(error), hint="Corrija o valor informado e repita.")
    raise typer.Exit(EXIT_USAGE_ERROR) from error


def init_command(
    issuer: Annotated[str | None, typer.Option(help=_ajuda_issuer())] = None,
    client_id: Annotated[str | None, typer.Option(help=_ajuda_client_id())] = None,
    api_url: Annotated[str | None, typer.Option(help=_ajuda_api_url())] = None,
    allow_insecure_http: Annotated[
        bool,
        typer.Option("--allow-insecure-http", help=_ajuda_allow_insecure_http()),
    ] = False,
    force: Annotated[
        bool,
        typer.Option(
            "--force",
            help=opcao(
                "Sobrescreve a configuração existente.",
                tipo="Booleano",
                variavel=None,
                arquivo=None,
                padrao="desativado",
            ),
        ),
    ] = False,
) -> None:
    path = config_file_path()
    if path.exists() and not force:
        ui.error(
            "Configuração já existe",
            f"O arquivo {path} não foi alterado.",
            hint="Use --force para sobrescrevê-lo.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)

    # Um parâmetro de HTTP vale para as duas seções; sem ele, cada seção usa o seu valor.
    explicit_auth = _explicit({"issuer": issuer, "client_id": client_id}, allow_insecure_http)
    explicit_core = _explicit({"api_url": api_url}, allow_insecure_http)
    try:
        settings = SkSettingsWithoutConfigFile(
            auth=explicit_auth,  # pyright: ignore[reportArgumentType]
            core=explicit_core,  # pyright: ignore[reportArgumentType]
        )
    except (ValidationError, ConfigurationError) as error:
        _exit_on_configuration_error(error)

    auth = AuthSettings(
        issuer=settings.auth.issuer or PRD_ISSUER,
        client_id=settings.auth.client_id or CLIENT_ID_PROVISORIO,
        allow_insecure_http=settings.auth.allow_insecure_http,
    )
    core = CoreSettings(
        api_url=settings.core.api_url or PRD_API_URL,
        allow_insecure_http=settings.core.allow_insecure_http,
    )

    try:
        ensure_secure_url(auth.issuer or "", allow_insecure_http=auth.allow_insecure_http)
        ensure_secure_url(core.api_url or "", allow_insecure_http=core.allow_insecure_http)
    except OidcError as error:
        ui.error(
            "Endereço recusado",
            str(error),
            hint="Use HTTPS, ou --allow-insecure-http em desenvolvimento.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR) from error

    content = render_section("auth", auth) + "\n" + render_section("core", core)
    try:
        write_private_file(path, content)
    except OSError as error:
        ui.error("Não foi possível gravar a configuração", f"{path}: {error.strerror}")
        raise typer.Exit(EXIT_FAILURE) from error

    ui.panel(
        "Configuração gravada",
        [
            ("Arquivo", str(path)),
            ("Provedor", auth.issuer or ""),
            ("API", core.api_url or ""),
            ("Client ID", auth.client_id or ""),
        ],
    )
    if auth.client_id == CLIENT_ID_PROVISORIO:
        ui.warning(
            "O client ID de produção ainda não foi definido: o login de produção não funciona "
            "até ele ser informado com --client-id ou `sk config set auth.clientId`."
        )
    ui.note("Próximo passo: `sk auth login`.")


def _explicit(values: dict[str, object], allow_insecure_http: bool) -> dict[str, object]:
    """Só os valores informados: parâmetro não informado (None ou False) não é repassado."""
    if allow_insecure_http:
        values["allow_insecure_http"] = True
    return {key: value for key, value in values.items() if value is not None}
