"""Comandos de autenticação na plataforma (`sk auth`).

O login é da plataforma, e não de um módulo: o `sk` autentica o usuário diretamente no
provedor de identidade (Zitadel), pelo gateway, sem API própria de autenticação.
"""

import webbrowser
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from sk import ui
from sk.defaults import PRD_CLIENT_ID, PRD_ISSUER, PROVISIONAL
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
from sk.identity.session import SessionError, current_access_token, renew_session
from sk.settings import (
    AuthSettings,
    ConfigurationError,
    SkSettings,
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
    help="Authentication on the platform.",
    no_args_is_help=True,
    # Ajuda colorida pelo Rich. Colchetes literais nos textos são escapados com "\\[".
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)


def load_auth_settings(command_line_values: Mapping[str, object]) -> AuthSettings:
    """Carrega a seção `auth`, com os parâmetros informados acima das demais fontes.

    Um parâmetro não informado (`None`) ou flag não ativada (`False`) não é repassado, para
    que o valor venha do ambiente, do arquivo de configuração ou do default.
    """
    explicit_values = {
        key: value
        for key, value in command_line_values.items()
        if value is not None and value is not False
    }
    # Argumentos de inicialização são a fonte de maior precedência do pydantic-settings e
    # são mesclados campo a campo com as demais. O pydantic valida o dicionário como
    # AuthSettings; o pyright só conhece o tipo do campo, por isso a supressão.
    return SkSettings(auth=explicit_values).auth  # pyright: ignore[reportArgumentType]


def _load_or_exit(command_line_values: Mapping[str, object]) -> AuthSettings:
    try:
        return load_auth_settings(command_line_values)
    except (ValidationError, ConfigurationError) as error:
        ui.error("Invalid configuration", str(error), hint=f"Fix the file {config_file_path()}.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _refuse_provisional_defaults(auth: AuthSettings) -> None:
    """Recusa o login enquanto algum valor ainda não existe em produção (decisão 0036).

    O padrão de produção do client ID e dos IDs dos projetos de roles só passa a valer quando o
    Zitadel de produção for provisionado. Seguir com o marcador falharia mais adiante, sem dizer por
    quê; aqui a mensagem diz qual valor falta.
    """
    try:
        settings = SkSettings()
    except (ValidationError, ConfigurationError) as error:
        ui.error("Invalid configuration", str(error), hint="Fix the file and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    values = {
        "auth.clientId": auth.client_id,
        "core.projectId": settings.core.project_id,
        "sum.projectId": settings.sum.project_id,
        "ipm.projectId": settings.ipm.project_id,
    }
    pending = [key for key, value in values.items() if value == PROVISIONAL]
    if pending:
        ui.error(
            "Production is not provisioned yet",
            f"These values have no production default yet: {', '.join(pending)}.",
            hint="Set each with `sk config set <key> <value>` or an SK_* variable (development).",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)


def _present_authorization_url(authorization_url: str) -> None:
    ui.url_panel("Open the browser to continue (expires in 5 minutes)", authorization_url)
    ui.note("The browser should open by itself. If it does not, copy the address above.")
    webbrowser.open(authorization_url)


def _display_name(userinfo: Mapping[str, object]) -> str:
    for claim in ("preferred_username", "email", "sub"):
        value = userinfo.get(claim)
        if isinstance(value, str) and value:
            return value
    return "unknown"


def login_scopes(project_ids: Sequence[str]) -> tuple[str, ...]:
    """Escopos do login. Cada projeto de roles informado entra na audience e nas roles do token.

    A aplicação do `sk` não mora num projeto de roles (projeto `clients`): o token só vale no
    Receiver de um módulo se o projeto de roles dele for pedido aqui.
    """
    if not project_ids:
        return LOGIN_SCOPES
    audiences = tuple(f"urn:zitadel:iam:org:project:id:{project}:aud" for project in project_ids)
    return (*LOGIN_SCOPES, *audiences, ROLES_SCOPE)


def run_login(
    settings: AuthSettings, credentials_path: Path, *, project_ids: Sequence[str] = ()
) -> None:
    """Executa o login e grava as credenciais. Falhas encerram com código diferente de 0."""
    try:
        metadata = fetch_provider_metadata(
            settings.issuer, allow_insecure_http=settings.allow_insecure_http
        )
        token_response = run_authorization_code_flow(
            metadata,
            client_id=settings.client_id,
            scopes=login_scopes(project_ids),
            present_authorization_url=_present_authorization_url,
            timeout_seconds=LOGIN_TIMEOUT_SECONDS,
        )
        obtained_at = datetime.now(UTC)
        userinfo = fetch_userinfo(metadata, token_response.access_token)
        save_credentials(
            credentials_path,
            StoredCredentials(
                issuer=metadata.issuer,
                client_id=settings.client_id,
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
        ui.error("Login not completed", str(error), hint="Run `sk auth login` again.")
        raise typer.Exit(EXIT_FAILURE) from error

    ui.panel(
        "Login completed",
        [
            ("user", _display_name(userinfo)),
            ("issuer", metadata.issuer),
            (
                "expiresAt",
                ui.format_expiry(
                    obtained_at + timedelta(seconds=token_response.expires_in_seconds)
                ),
            ),
            ("credentialsFile", str(credentials_path)),
        ],
    )
    if token_response.refresh_token is None:
        ui.warning(
            "The provider did not issue a refresh token: enable the Refresh Token grant on "
            "the application."
        )


def _help_issuer(file: str | None) -> str:
    return option(
        "Login provider address.",
        kind="String",
        variable="SK_AUTH_ISSUER",
        file=file,
        default=PRD_ISSUER,
    )


def _help_client_id(file: str | None) -> str:
    return option(
        "Identifier of sk at the login provider.",
        kind="String",
        variable="SK_AUTH_CLIENT_ID",
        file=file,
        default=PRD_CLIENT_ID,
    )


def _help_allow_insecure_http(file: str | None) -> str:
    return option(
        "Allow an address without HTTPS. Development only.",
        kind="Boolean",
        variable="SK_AUTH_ALLOW_INSECURE_HTTP=true",
        file=file,
        default="off",
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


def _module_project_ids() -> tuple[str, ...]:
    """`projectId` de `[core]`, `[sum]` e `[ipm]`: o login pede a audience de cada um."""
    try:
        settings = SkSettings()
    except (ValidationError, ConfigurationError) as error:
        ui.error("Invalid configuration", str(error), hint="Fix the file and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    return (settings.core.project_id, settings.sum.project_id, settings.ipm.project_id)


@auth_app.command(
    "login",
    help=command(
        "Sign in to the platform through the browser. A new login replaces the previous one."
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
    )
    _refuse_provisional_defaults(settings)
    run_login(settings, default_credentials_path(), project_ids=_module_project_ids())


def run_whoami(allow_insecure_http: bool, credentials_path: Path) -> None:
    """Mostra o usuário da sessão gravada, confirmando com o provedor que ela ainda vale."""
    try:
        credentials = load_credentials(credentials_path)
    except CredentialsMissingError as error:
        ui.error("Not authenticated", str(error), hint="Run `sk auth login` to sign in.")
        raise typer.Exit(EXIT_FAILURE) from error
    except CredentialsError as error:
        ui.error("Invalid credentials", str(error), hint="Run `sk auth login` again.")
        raise typer.Exit(EXIT_FAILURE) from error

    # O acesso dura 15 minutos (decisão 0033): vencido ou quase, a sessão se renova pelo refresh
    # token. Só sem como renovar (sem refresh token, ou recusado) a pessoa precisa entrar de novo.
    try:
        access_token = current_access_token(
            credentials_path, allow_insecure_http=allow_insecure_http
        )
    except SessionError as error:
        ui.error("Session expired", str(error), hint="Run `sk auth login` to sign in again.")
        raise typer.Exit(EXIT_FAILURE) from error
    credentials = load_credentials(credentials_path)  # pode ter sido renovada

    try:
        metadata = fetch_provider_metadata(
            credentials.issuer, allow_insecure_http=allow_insecure_http
        )
        userinfo = fetch_userinfo(metadata, access_token)
    except OidcError as error:
        # Pode ser sessão recusada ou falha de rede: a mensagem do erro diz qual.
        ui.error(
            "Could not confirm the session",
            str(error),
            hint="If the error persists, run `sk auth login` again.",
        )
        raise typer.Exit(EXIT_FAILURE) from error

    ui.panel(
        "Active session",
        [
            ("user", _display_name(userinfo)),
            ("issuer", credentials.issuer),
            ("expiresAt", ui.format_expiry(credentials.access_token_expires_at)),
        ],
    )


@auth_app.command(
    "whoami",
    help=command("Show the user of the current session and confirm it is still valid."),
)
def whoami(allow_insecure_http: AllowInsecureHttpOption = False) -> None:
    settings = _load_or_exit(
        {"allow_insecure_http": allow_insecure_http},
    )
    run_whoami(settings.allow_insecure_http, default_credentials_path())


@auth_app.command(
    "refresh",
    help=command(
        "Renew the session now, with the refresh token, so the token reflects the current roles "
        "(for example, after enabling or disabling a service)."
    ),
)
def refresh(allow_insecure_http: AllowInsecureHttpOption = False) -> None:
    settings = _load_or_exit({"allow_insecure_http": allow_insecure_http})
    try:
        expires_at = renew_session(
            default_credentials_path(), allow_insecure_http=settings.allow_insecure_http
        )
    except SessionError as error:
        ui.error("Session not renewed", str(error), hint="Run `sk auth login`.")
        raise typer.Exit(EXIT_FAILURE) from error
    ui.panel("Session renewed", [("expiresAt", ui.format_expiry(expires_at))])
