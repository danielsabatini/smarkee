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
    # Sem marcação Rich nos textos de ajuda: "[auth]" deve aparecer literalmente.
    rich_markup_mode=None,
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
        typer.echo(f"Erro na configuração: {error}", err=True)
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _require_issuer_and_client_id(settings: AuthSettings) -> tuple[str, str]:
    if not settings.issuer:
        typer.echo(
            "Erro: informe o issuer por --issuer, SK_AUTH_ISSUER ou issuer na tabela [auth] "
            "do arquivo de configuração.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    if not settings.client_id:
        typer.echo(
            "Erro: informe o client ID por --client-id, SK_AUTH_CLIENT_ID ou clientId na "
            "tabela [auth] do arquivo de configuração.",
            err=True,
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return settings.issuer, settings.client_id


def _present_authorization_url(authorization_url: str) -> None:
    typer.echo("Abrindo o navegador para o login. Se ele não abrir, acesse:", err=True)
    typer.echo(authorization_url, err=True)
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
        typer.echo(f"Erro no login: {error}", err=True)
        raise typer.Exit(EXIT_FAILURE) from error

    typer.echo(f"Autenticado como {_display_name(userinfo)} em {metadata.issuer}.")
    if token_response.refresh_token is None:
        typer.echo(
            "Aviso: o provedor não emitiu refresh token; "
            "habilite o grant Refresh Token na aplicação.",
            err=True,
        )
    typer.echo(f"Credenciais gravadas em {credentials_path}.")


IssuerOption = Annotated[
    str | None,
    typer.Option(
        help=(
            "URL do issuer OIDC (provedor de identidade, acessado pelo gateway). "
            "Também por SK_AUTH_ISSUER ou issuer na tabela [auth]."
        ),
        show_default=False,
    ),
]
ClientIdOption = Annotated[
    str | None,
    typer.Option(
        help=(
            "Client ID da aplicação nativa do sk no provedor (um por ambiente). "
            "Também por SK_AUTH_CLIENT_ID ou clientId na tabela [auth]."
        ),
        show_default=False,
    ),
]
AllowInsecureHttpOption = Annotated[
    bool,
    typer.Option(
        "--allow-insecure-http",
        help=(
            "Aceita issuer sem TLS (http). Somente para desenvolvimento. "
            "Também por SK_AUTH_ALLOW_INSECURE_HTTP=true ou allowInsecureHttp na tabela [auth]."
        ),
        show_default=False,
    ),
]


@auth_app.command(
    "init",
    help=(
        "Cria o arquivo de configuração do sk (config.toml) com a tabela [auth]. Os valores "
        "vêm dos parâmetros ou das variáveis SK_AUTH_*; issuer e client ID são obrigatórios. "
        "Não sobrescreve um arquivo existente sem --force."
    ),
)
def init(
    issuer: IssuerOption = None,
    client_id: ClientIdOption = None,
    allow_insecure_http: AllowInsecureHttpOption = False,
    force: Annotated[
        bool,
        typer.Option("--force", help="Sobrescreve o arquivo de configuração existente."),
    ] = False,
) -> None:
    path = config_file_path()
    if path.exists() and not force:
        typer.echo(
            f"Erro: o arquivo de configuração já existe: {path}. Use --force para sobrescrevê-lo.",
            err=True,
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
        typer.echo(f"Erro: {error}", err=True)
        raise typer.Exit(EXIT_USAGE_ERROR) from error

    try:
        write_private_file(path, render_section("auth", settings))
    except OSError as error:
        typer.echo(f"Erro: não foi possível gravar {path}: {error.strerror}", err=True)
        raise typer.Exit(EXIT_FAILURE) from error
    typer.echo(f"Configuração gravada em {path}.")


@auth_app.command(
    "login",
    help=(
        "Autentica o usuário pelo navegador (OIDC Authorization Code com PKCE e retorno em "
        "127.0.0.1) e grava os tokens no arquivo de credenciais do sk. Um novo login substitui "
        "as credenciais anteriores."
    ),
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
