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

from sk import ui
from sk.help import command, option
from sk.identity.credentials import (
    CredentialsError,
    CredentialsMissingError,
    StoredCredentials,
    default_credentials_path,
    load_credentials,
    save_credentials,
)
from sk.identity.oidc import (
    OidcError,
    fetch_provider_metadata,
    fetch_userinfo,
    run_authorization_code_flow,
)
from sk.settings import (
    AuthSettings,
    ConfigurationError,
    SkSettings,
    SkSettingsWithoutConfigFile,
    config_file_path,
)

# offline_access solicita o refresh token (a aplicação no provedor precisa permiti-lo).
LOGIN_SCOPES = ("openid", "profile", "email", "offline_access")
# Roles no token e audience de um módulo: o Receiver de cada módulo exige a audience dele.
ROLES_SCOPE = "urn:zitadel:iam:org:projects:roles"
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
    settings_class = SkSettings if include_config_file else SkSettingsWithoutConfigFile
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
            hint="Rode `sk init` para criar a configuração.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    if not settings.client_id:
        ui.error(
            "Client ID não informado",
            "Informe-o por --client-id, SK_AUTH_CLIENT_ID ou clientId na tabela [auth].",
            hint="Rode `sk init` para criar a configuração.",
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


def login_scopes(sum_project_id: str | None) -> tuple[str, ...]:
    """Escopos do login. Com o projeto do SUM configurado, o token vale também no Receiver dele."""
    if sum_project_id is None:
        return LOGIN_SCOPES
    audience = f"urn:zitadel:iam:org:project:id:{sum_project_id}:aud"
    return (*LOGIN_SCOPES, audience, ROLES_SCOPE)


def run_login(
    settings: AuthSettings, credentials_path: Path, *, sum_project_id: str | None = None
) -> None:
    """Executa o login e grava as credenciais. Falhas encerram com código diferente de 0."""
    issuer, client_id = _require_issuer_and_client_id(settings)

    try:
        metadata = fetch_provider_metadata(issuer, allow_insecure_http=settings.allow_insecure_http)
        token_response = run_authorization_code_flow(
            metadata,
            client_id=client_id,
            scopes=login_scopes(sum_project_id),
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


def _help_issuer(file: str | None) -> str:
    return option(
        "Endereço do provedor de login.",
        kind="String",
        variable="SK_AUTH_ISSUER",
        file=file,
        default="nenhum",
    )


def _help_client_id(file: str | None) -> str:
    return option(
        "Identificador do sk no provedor de login.",
        kind="String",
        variable="SK_AUTH_CLIENT_ID",
        file=file,
        default="nenhum",
    )


def _help_allow_insecure_http(file: str | None) -> str:
    return option(
        "Permite endereço sem HTTPS. Somente para desenvolvimento.",
        kind="Booleano",
        variable="SK_AUTH_ALLOW_INSECURE_HTTP=true",
        file=file,
        default="desativado",
    )


# O login lê o arquivo de configuração; o init não lê o arquivo que cria, então a ajuda dele
# não lista a seção [auth] como fonte.
IssuerOption = Annotated[
    str | None,
    typer.Option(help=_help_issuer("[auth] issuer")),
]
ClientIdOption = Annotated[
    str | None,
    typer.Option(help=_help_client_id("[auth] clientId")),
]
AllowInsecureHttpOption = Annotated[
    bool,
    typer.Option(
        "--allow-insecure-http",
        help=_help_allow_insecure_http("[auth] allowInsecureHttp = true"),
    ),
]


def _sum_project_id() -> str | None:
    """`[sum] projectId` (ou `SK_SUM_PROJECT_ID`). Sem ele, o login não pede o audience do SUM."""
    try:
        return SkSettings().sum.project_id
    except (ValidationError, ConfigurationError) as error:
        ui.error("Configuração inválida", str(error), hint="Corrija o arquivo e repita.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


@auth_app.command(
    "login",
    help=command("Entra na plataforma pelo navegador. Um novo login substitui o anterior."),
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
    run_login(settings, default_credentials_path(), sum_project_id=_sum_project_id())


def run_whoami(allow_insecure_http: bool, credentials_path: Path) -> None:
    """Mostra o usuário da sessão gravada, confirmando com o provedor que ela ainda vale."""
    try:
        credentials = load_credentials(credentials_path)
    except CredentialsMissingError as error:
        ui.error("Não autenticado", str(error), hint="Rode `sk auth login` para entrar.")
        raise typer.Exit(EXIT_FAILURE) from error
    except CredentialsError as error:
        ui.error("Credenciais inválidas", str(error), hint="Rode `sk auth login` de novo.")
        raise typer.Exit(EXIT_FAILURE) from error

    # Checagem local primeiro: com o acesso vencido, nem vale consultar o provedor.
    if credentials.access_token_expires_at <= datetime.now(UTC):
        ui.error(
            "Sessão expirada",
            f"O acesso venceu em {ui.format_expiry(credentials.access_token_expires_at)}.",
            hint="Rode `sk auth login` para entrar de novo.",
        )
        raise typer.Exit(EXIT_FAILURE)

    try:
        metadata = fetch_provider_metadata(
            credentials.issuer, allow_insecure_http=allow_insecure_http
        )
        userinfo = fetch_userinfo(metadata, credentials.access_token)
    except OidcError as error:
        # Pode ser sessão recusada ou falha de rede: a mensagem do erro diz qual.
        ui.error(
            "Não foi possível confirmar a sessão",
            str(error),
            hint="Se o erro persistir, rode `sk auth login` de novo.",
        )
        raise typer.Exit(EXIT_FAILURE) from error

    ui.panel(
        "Sessão ativa",
        [
            ("Usuário", _display_name(userinfo)),
            ("Provedor", credentials.issuer),
            ("Válido até", ui.format_expiry(credentials.access_token_expires_at)),
        ],
    )


@auth_app.command(
    "whoami",
    help=command("Mostra o usuário da sessão atual e confirma que ela ainda vale."),
)
def whoami(allow_insecure_http: AllowInsecureHttpOption = False) -> None:
    settings = _load_or_exit(
        {"allow_insecure_http": allow_insecure_http},
        include_config_file=True,
    )
    run_whoami(settings.allow_insecure_http, default_credentials_path())
