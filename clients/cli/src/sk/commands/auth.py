"""Comandos de autenticação na plataforma (`sk auth`).

O login é da plataforma, e não de um módulo: o `sk` autentica o usuário diretamente no
provedor de identidade (Zitadel), pelo gateway, sem API própria de autenticação.
"""

import contextlib
import webbrowser
from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Annotated

import typer
from pydantic import ValidationError

from sk import ui
from sk.command_app import SkTyper
from sk.defaults import PROVISIONAL
from sk.files import STANDARD_INPUT
from sk.help import command, option
from sk.identity.credentials import (
    CredentialsError,
    CredentialsMissingError,
    StoredCredentials,
    default_credentials_path,
    load_credentials,
    save_credentials,
)
from sk.identity.keys import KeyFileError, read_key_file, sign_jwt_assertion
from sk.identity.oidc import (
    OidcError,
    fetch_jwt_bearer_token,
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

auth_app = SkTyper(
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


def _refuse_provisional_module_projects() -> None:
    """Recusa o login de máquina quando os IDs dos projetos ainda não existem em produção."""
    try:
        settings = SkSettings()
    except (ValidationError, ConfigurationError) as error:
        ui.error("Invalid configuration", str(error), hint="Fix the file and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    values = {
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


def run_service_account_login(
    settings: AuthSettings,
    key_file: Path,
    credentials_path: Path,
    *,
    project_ids: Sequence[str] = (),
) -> None:
    """Executa o login de service account por assertion JWT e grava as credenciais."""
    try:
        key_data = read_key_file(key_file)
    except KeyFileError as error:
        ui.error("Invalid key file", str(error), hint="Check the key file path and its content.")
        raise typer.Exit(EXIT_FAILURE) from error

    try:
        metadata = fetch_provider_metadata(
            settings.issuer, allow_insecure_http=settings.allow_insecure_http
        )
        assertion = sign_jwt_assertion(
            key_data["key"],
            key_data["keyId"],
            key_data["userId"],
            metadata.issuer,
        )
        token_response = fetch_jwt_bearer_token(
            metadata,
            assertion=assertion,
            scopes=login_scopes(project_ids),
        )
        obtained_at = datetime.now(UTC)
        save_credentials(
            credentials_path,
            StoredCredentials(
                issuer=metadata.issuer,
                client_id="",
                token_type=token_response.token_type,
                access_token=token_response.access_token,
                access_token_expires_at=obtained_at
                + timedelta(seconds=token_response.expires_in_seconds),
                refresh_token=None,
                id_token=None,
                scope=token_response.scope,
                obtained_at=obtained_at,
                key_file=str(key_file.resolve()),
            ),
        )
    except (OidcError, KeyFileError, CredentialsError) as error:
        ui.error(
            "Service account login not completed",
            str(error),
            hint="Check the key status or rotate it if expired.",
        )
        raise typer.Exit(EXIT_FAILURE) from error

    ui.panel(
        "Login completed",
        [
            ("user", key_data["userId"]),
            ("issuer", metadata.issuer),
            (
                "expiresAt",
                ui.format_expiry(
                    obtained_at + timedelta(seconds=token_response.expires_in_seconds)
                ),
            ),
            ("keyFile", str(key_file.resolve())),
            ("credentialsFile", str(credentials_path)),
        ],
    )


def module_project_ids() -> tuple[str, ...]:
    """`projectId` de `[core]`, `[sum]`, `[ipm]`, `[bsm]` e `[operator]`: audiences do login."""
    try:
        settings = SkSettings()
    except (ValidationError, ConfigurationError) as error:
        ui.error("Invalid configuration", str(error), hint="Fix the file and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    projects = [settings.core.project_id, settings.sum.project_id, settings.ipm.project_id]
    if settings.bsm.project_id != PROVISIONAL:
        projects.append(settings.bsm.project_id)
    if settings.operator.project_id != PROVISIONAL:
        projects.append(settings.operator.project_id)
    return tuple(projects)


KeyFileOption = Annotated[
    Path | None,
    typer.Option(
        "--key-file",
        envvar="SK_AUTH_KEY_FILE",
        help=option(
            "Service account key file for machine authentication.",
            kind="String",
            variable="SK_AUTH_KEY_FILE",
            file=None,
            default="browser login",
        ),
    ),
]


@auth_app.command(
    "login",
    help=command(
        "Sign in to the platform. Interactive login opens the browser; "
        "with --key-file, authenticates a service account.",
        examples=["sk auth login", "sk auth login --key-file sa-ci-deploy.json"],
    ),
)
def login(key_file: KeyFileOption = None) -> None:
    settings = _load_or_exit({})
    if key_file is not None:
        if key_file == STANDARD_INPUT:
            # A sessão guarda o caminho e relê o arquivo a cada renovação (15 min): sem arquivo,
            # ela não se renovaria. Copiar a chave privada para outro lugar seria decisão à parte.
            ui.error(
                "Key file required",
                "The session renews itself from the key file, so it cannot come from stdin.",
                hint="Save the key to a file with restricted permissions and give its path.",
            )
            raise typer.Exit(EXIT_USAGE_ERROR)
        _refuse_provisional_module_projects()
        run_service_account_login(
            settings,
            key_file,
            default_credentials_path(),
            project_ids=module_project_ids(),
        )
        return
    _refuse_provisional_defaults(settings)
    run_login(settings, default_credentials_path(), project_ids=module_project_ids())


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

    user_name = "unknown"
    try:
        metadata = fetch_provider_metadata(
            credentials.issuer, allow_insecure_http=allow_insecure_http
        )
        userinfo = fetch_userinfo(metadata, access_token)
        user_name = _display_name(userinfo)
    except OidcError as error:
        if credentials.key_file is not None:
            with contextlib.suppress(KeyFileError):
                user_name = read_key_file(Path(credentials.key_file))["userId"]
        if user_name == "unknown":
            # Pode ser sessão recusada ou falha de rede: a mensagem do erro diz qual.
            ui.error(
                "Could not confirm the session",
                str(error),
                hint="If the error persists, run `sk auth login` again.",
            )
            raise typer.Exit(EXIT_FAILURE) from error

    fields: list[tuple[str, str]] = [
        ("user", user_name),
        ("issuer", credentials.issuer),
        ("expiresAt", ui.format_expiry(credentials.access_token_expires_at)),
    ]
    data: dict[str, str] = {
        "user": user_name,
        "issuer": credentials.issuer,
        "expiresAt": credentials.access_token_expires_at.isoformat(),
    }
    if credentials.key_file is not None:
        fields.append(("keyFile", credentials.key_file))
        data["keyFile"] = credentials.key_file

    ui.panel(
        "Active session",
        fields,
        # Só o que o painel já mostra: nunca o token nem as claims do provedor.
        data=data,
    )


@auth_app.command(
    "whoami",
    structured=True,
    help=command("Show the user of the current session and confirm it is still valid."),
)
def whoami() -> None:
    settings = _load_or_exit({})
    run_whoami(settings.allow_insecure_http, default_credentials_path())


@auth_app.command(
    "refresh",
    help=command(
        "Renew the session now, with the refresh token, so the token reflects the current "
        "permissions (for example, after enabling or disabling a service)."
    ),
)
def refresh() -> None:
    settings = _load_or_exit({})
    try:
        expires_at = renew_session(
            default_credentials_path(), allow_insecure_http=settings.allow_insecure_http
        )
    except SessionError as error:
        ui.error("Session not renewed", str(error), hint="Run `sk auth login`.")
        raise typer.Exit(EXIT_FAILURE) from error
    ui.panel("Session renewed", [("expiresAt", ui.format_expiry(expires_at))])
