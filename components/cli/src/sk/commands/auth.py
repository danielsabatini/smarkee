"""Comandos de autenticação na plataforma (`sk auth`).

O login é da plataforma, e não de um módulo: o `sk` autentica o usuário diretamente no
provedor de identidade (Zitadel), pelo gateway, sem API própria de autenticação.
"""

import webbrowser
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError
from pydantic_settings import BaseSettings, PydanticBaseSettingsSource

from sk import ui
from sk.ajuda import ORDEM_SEM_ARQUIVO, comando, opcao
from sk.credentials import (
    CredentialsError,
    StoredCredentials,
    default_credentials_path,
    save_credentials,
)
from sk.files import write_private_file
from sk.oidc import (
    OidcError,
    ensure_secure_url,
    fetch_provider_metadata,
    fetch_userinfo,
    run_authorization_code_flow,
)
from sk.settings import (
    AuthSettings,
    ConfigurationError,
    SkSettings,
    config_file_path,
    render_section,
)

# offline_access solicita o refresh token (a aplicação no provedor precisa permiti-lo).
LOGIN_SCOPES = ("openid", "profile", "email", "offline_access")
LOGIN_TIMEOUT_SECONDS = 300

EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2

auth_app = typer.Typer(
    help="Autenticação na plataforma.",
    no_args_is_help=True,
    # Ajuda colorida pelo Rich. Colchetes literais nos textos são escapados com "\\[".
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)


class _SkSettingsWithoutConfigFile(SkSettings):
    """Mesma configuração, sem a fonte do arquivo (usada pelo `init`, que o cria)."""

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, env_settings)


def load_auth_settings(
    command_line_values: Mapping[str, object], *, include_config_file: bool = True
) -> AuthSettings:
    """Carrega a seção `auth`, com os parâmetros informados acima das demais fontes.

    Um parâmetro não informado (`None`) ou flag não ativada (`False`) não é repassado, para
    que o valor venha do ambiente, do arquivo de configuração ou do default.
    """
    explicit_values = {
        key: value
        for key, value in command_line_values.items()
        if value is not None and value is not False
    }
    settings_class = SkSettings if include_config_file else _SkSettingsWithoutConfigFile
    # Argumentos de inicialização são a fonte de maior precedência do pydantic-settings e
    # são mesclados campo a campo com as demais. O pydantic valida o dicionário como
    # AuthSettings; o pyright só conhece o tipo do campo, por isso a supressão.
    return settings_class(auth=explicit_values).auth  # pyright: ignore[reportArgumentType]


def _load_or_exit(
    command_line_values: Mapping[str, object], *, include_config_file: bool
) -> AuthSettings:
    try:
        return load_auth_settings(command_line_values, include_config_file=include_config_file)
    except (ValidationError, ConfigurationError) as error:
        ui.error(
            "Configuração inválida", str(error), hint=f"Corrija o arquivo {config_file_path()}."
        )
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _require_issuer_and_client_id(settings: AuthSettings) -> tuple[str, str]:
    if not settings.issuer:
        ui.error(
            "Issuer não informado",
            "Informe-o por --issuer, SK_AUTH_ISSUER ou issuer na tabela [auth].",
            hint="Rode `sk auth init --issuer <URL>` para criar a configuração.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    if not settings.client_id:
        ui.error(
            "Client ID não informado",
            "Informe-o por --client-id, SK_AUTH_CLIENT_ID ou clientId na tabela [auth].",
            hint="Rode `sk auth init --client-id <ID>` para criar a configuração.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return settings.issuer, settings.client_id


def _present_authorization_url(authorization_url: str) -> None:
    ui.url_panel("Entre no navegador para continuar (expira em 5 minutos)", authorization_url)
    ui.note("O navegador deve abrir sozinho. Se não abrir, copie o endereço acima.")
    webbrowser.open(authorization_url)


def _display_name(userinfo: Mapping[str, object]) -> str:
    for claim in ("preferred_username", "email", "sub"):
        value = userinfo.get(claim)
        if isinstance(value, str) and value:
            return value
    return "usuário sem identificação no userinfo"


def run_login(settings: AuthSettings, credentials_path: Path) -> None:
    """Executa o login e grava as credenciais. Falhas encerram com código diferente de 0."""
    issuer, client_id = _require_issuer_and_client_id(settings)

    try:
        metadata = fetch_provider_metadata(issuer, allow_insecure_http=settings.allow_insecure_http)
        token_response = run_authorization_code_flow(
            metadata,
            client_id=client_id,
            scopes=LOGIN_SCOPES,
            present_authorization_url=_present_authorization_url,
            timeout_seconds=LOGIN_TIMEOUT_SECONDS,
        )
        obtained_at = datetime.now(UTC)
        userinfo = fetch_userinfo(metadata, token_response.access_token)
        save_credentials(
            credentials_path,
            StoredCredentials(
                issuer=metadata.issuer,
                client_id=client_id,
                token_type=token_response.token_type,
                access_token=token_response.access_token,
                access_token_expires_at=obtained_at
                + timedelta(seconds=token_response.expires_in_seconds),
                refresh_token=token_response.refresh_token,
                id_token=token_response.id_token,
                scope=token_response.scope,
                obtained_at=obtained_at,
            ),
        )
    except (OidcError, CredentialsError) as error:
        ui.error("Login não concluído", str(error), hint="Rode `sk auth login` de novo.")
        raise typer.Exit(EXIT_FAILURE) from error

    ui.panel(
        "Login realizado",
        [
            ("Usuário", _display_name(userinfo)),
            ("Provedor", metadata.issuer),
            (
                "Válido até",
                ui.format_expiry(
                    obtained_at + timedelta(seconds=token_response.expires_in_seconds)
                ),
            ),
            ("Credenciais", str(credentials_path)),
        ],
    )
    if token_response.refresh_token is None:
        ui.warning(
            "O provedor não emitiu refresh token: habilite o grant Refresh Token na aplicação."
        )


def _ajuda_issuer(arquivo: str | None) -> str:
    return opcao(
        "Endereço do provedor de login.",
        tipo="String",
        variavel="SK_AUTH_ISSUER",
        arquivo=arquivo,
        padrao="nenhum",
    )


def _ajuda_client_id(arquivo: str | None) -> str:
    return opcao(
        "Identificador do sk no provedor de login.",
        tipo="String",
        variavel="SK_AUTH_CLIENT_ID",
        arquivo=arquivo,
        padrao="nenhum",
    )


def _ajuda_allow_insecure_http(arquivo: str | None) -> str:
    return opcao(
        "Permite endereço sem HTTPS. Somente para desenvolvimento.",
        tipo="Booleano",
        variavel="SK_AUTH_ALLOW_INSECURE_HTTP=true",
        arquivo=arquivo,
        padrao="desativado",
    )


# O login lê o arquivo de configuração; o init não lê o arquivo que cria, então a ajuda dele
# não lista a seção [auth] como fonte.
IssuerOption = Annotated[
    str | None,
    typer.Option(help=_ajuda_issuer("[auth] issuer")),
]
ClientIdOption = Annotated[
    str | None,
    typer.Option(help=_ajuda_client_id("[auth] clientId")),
]
AllowInsecureHttpOption = Annotated[
    bool,
    typer.Option(
        "--allow-insecure-http",
        help=_ajuda_allow_insecure_http("[auth] allowInsecureHttp = true"),
    ),
]
IssuerOptionInit = Annotated[
    str | None,
    typer.Option(help=_ajuda_issuer(None)),
]
ClientIdOptionInit = Annotated[
    str | None,
    typer.Option(help=_ajuda_client_id(None)),
]
AllowInsecureHttpOptionInit = Annotated[
    bool,
    typer.Option(
        "--allow-insecure-http",
        help=_ajuda_allow_insecure_http(None),
    ),
]


@auth_app.command(
    "init",
    help=comando(
        "Cria o arquivo de configuração do sk. Não sobrescreve um arquivo existente sem --force.",
        ordem=ORDEM_SEM_ARQUIVO,
    ),
)
def init(
    issuer: IssuerOptionInit = None,
    client_id: ClientIdOptionInit = None,
    allow_insecure_http: AllowInsecureHttpOptionInit = False,
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

    # O init não lê o arquivo que vai criar: parâmetro → variável de ambiente → default.
    settings = _load_or_exit(
        {
            "issuer": issuer,
            "client_id": client_id,
            "allow_insecure_http": allow_insecure_http,
        },
        include_config_file=False,
    )
    configured_issuer, _ = _require_issuer_and_client_id(settings)
    try:
        ensure_secure_url(configured_issuer, allow_insecure_http=settings.allow_insecure_http)
    except OidcError as error:
        ui.error(
            "Endereço do provedor recusado",
            str(error),
            hint="Use HTTPS ou --allow-insecure-http em desenvolvimento.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR) from error

    try:
        write_private_file(path, render_section("auth", settings))
    except OSError as error:
        ui.error("Não foi possível gravar a configuração", f"{path}: {error.strerror}")
        raise typer.Exit(EXIT_FAILURE) from error
    ui.panel(
        "Configuração gravada",
        [
            ("Arquivo", str(path)),
            ("Issuer", configured_issuer),
            ("Client ID", settings.client_id or ""),
        ],
    )
    ui.note("Próximo passo: `sk auth login`.")


@auth_app.command(
    "login",
    help=comando("Entra na plataforma pelo navegador. Um novo login substitui o anterior."),
)
def login(
    issuer: IssuerOption = None,
    client_id: ClientIdOption = None,
    allow_insecure_http: AllowInsecureHttpOption = False,
) -> None:
    settings = _load_or_exit(
        {
            "issuer": issuer,
            "client_id": client_id,
            "allow_insecure_http": allow_insecure_http,
        },
        include_config_file=True,
    )
    run_login(settings, default_credentials_path())
