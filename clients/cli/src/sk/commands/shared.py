"""Partes comuns dos comandos que falam com a API da plataforma (`sum`, `ipm` e `register`).

Reúnem o que os comandos repetiriam: as opções `--wait` e
`--timeout`, a leitura da configuração da API, o token da sessão e a tradução das falhas da API em
mensagens para a pessoa. O texto de cada comando (o que é "recurso", o que um `404` significa) fica
no próprio comando.
"""

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Annotated, NoReturn, Protocol

import typer
from pydantic import ValidationError

from sk import output, ui
from sk.features.api_contract import OperationStatus, RequestAccepted, validate_identifier
from sk.help import option
from sk.http import ApiError, ApiRejectedError, ApiUnavailableError
from sk.identity.credentials import default_credentials_path
from sk.identity.oidc import OidcError
from sk.identity.session import SessionError, current_access_token, renew_session
from sk.settings import ConfigurationError, SkSettings

EXIT_FAILURE = 1
EXIT_USAGE_ERROR = 2

HTTP_NOT_FOUND = 404
DEFAULT_WAIT_TIMEOUT_SECONDS = 60
WAIT_POLL_SECONDS = 1.0

TimeoutOption = Annotated[
    int,
    typer.Option(
        "--timeout",
        min=1,
        help=option(
            "Seconds to wait with --wait.",
            kind="Integer",
            variable=None,
            file=None,
            default="60",
        ),
    ),
]


def require(value: str | None, option_name: str) -> str:
    """Opção obrigatória, validada pelo próprio comando (e não pelo Typer, que mostraria
    "[required]" na ajuda)."""
    if value is None:
        ui.error(
            "Missing required option",
            f"Provide {option_name}.",
            hint=f"Repeat the command with {option_name} VALUE.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return value


def load_api() -> tuple[str, bool]:
    """Endereço da API e permissão de HTTP: ambiente → arquivo → padrão de produção.

    Sem opção de linha de comando (decisão 0041): `SK_API_URL` e `SK_API_ALLOW_INSECURE_HTTP`, ou
    `[api]` no arquivo de configuração.
    """
    try:
        api = SkSettings().api
    except (ValidationError, ConfigurationError) as error:
        ui.error("Invalid configuration", str(error), hint="Fix the indicated file and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error
    return api.url, api.allow_insecure_http


def session_insecure() -> bool:
    """HTTP sem TLS no provedor de identidade: seção `[auth]` (ambiente ou arquivo)."""
    return SkSettings().auth.allow_insecure_http


def session_token() -> str:
    """Access token da sessão, renovado pelo refresh token quando está para vencer."""
    try:
        return current_access_token(
            default_credentials_path(), allow_insecure_http=session_insecure()
        )
    except SessionError as error:
        ui.error("Session unavailable", str(error), hint="Run `sk auth login`.")
        raise typer.Exit(EXIT_FAILURE) from error


def renew_after_convergence() -> bool:
    """Renova a sessão para o token refletir as permissões novas; falha vira aviso."""
    try:
        renew_session(default_credentials_path(), allow_insecure_http=session_insecure())
    except SessionError as error:
        ui.warning(
            f"Session not renewed ({error}). The token may not reflect the new permissions: "
            "run `sk auth login`."
        )
        return False
    return True


def bad_address(error: OidcError) -> NoReturn:
    ui.error(
        "API address refused",
        str(error),
        hint="Use HTTPS, or set SK_API_ALLOW_INSECURE_HTTP=true in development.",
    )
    raise typer.Exit(EXIT_USAGE_ERROR) from error


def fail_api(
    error: ApiError,
    *,
    not_found: str,
    conflict: str,
    by_error_code: Mapping[str, str] | None = None,
) -> NoReturn:
    """Mostra a falha da API e sai. `not_found` e `conflict` dizem o que o `404` e o `409`
    significam no comando; `by_error_code` dá a mensagem de um `errorCode` específico da API.

    Quando a CLI tem a própria mensagem (código conhecido ou `401`, `403`, `404`, `409`), mostra só
    ela, em inglês (decisão 0035). O texto do servidor (pt-BR) só aparece sem mensagem própria."""
    if isinstance(error, ApiUnavailableError):
        ui.error("Service unavailable", str(error), hint="Try again in a few minutes.")
        raise typer.Exit(EXIT_FAILURE) from error
    if not isinstance(error, ApiRejectedError):  # pragma: no cover (subclasse sem tratamento)
        ui.error("API call failed", str(error))
        raise typer.Exit(EXIT_FAILURE) from error
    if error.status == 429:
        wait = error.retry_after_seconds
        ui.error(
            "Too many requests",
            str(error),
            hint=f"Wait {wait} seconds and repeat." if wait else "Wait and try again.",
        )
        raise typer.Exit(EXIT_FAILURE) from error
    hints = {
        401: "The session was not accepted. Run `sk auth login`.",
        403: "Your account does not have permission for this operation.",
        404: not_found,
        409: conflict,
    }
    message = (by_error_code or {}).get(error.error_code) or hints.get(error.status)
    if message is not None:
        ui.error("Request refused by the API", message)
    else:
        detail = f"{error.field}: {error}" if error.field else str(error)
        ui.error(
            "Request refused by the API", detail, hint=f"HTTP {error.status} ({error.error_code})."
        )
    raise typer.Exit(EXIT_USAGE_ERROR if error.status == 400 else EXIT_FAILURE) from error


def usage_error(message: str, option_name: str) -> NoReturn:
    """Valor de opção recusado antes de qualquer chamada de rede (código de saída 2)."""
    ui.error("Value not accepted", message, hint=f"Fix {option_name} and repeat.")
    raise typer.Exit(EXIT_USAGE_ERROR)


def identifier(value: str | None, option_name: str, *, what: str) -> str:
    """Opção obrigatória que é um identificador do contrato, recusada antes da chamada de rede."""
    try:
        return validate_identifier(require(value, option_name), what=what)
    except ValueError as error:
        usage_error(str(error), option_name)


def fail_api_with_forbidden(
    error: ApiError,
    *,
    not_found: str,
    conflict: str,
    by_error_code: Mapping[str, str],
    forbidden: str,
) -> NoReturn:
    """`fail_api` com a mensagem de `403` própria do comando (`Forbidden`)."""
    hints = dict(by_error_code)
    if isinstance(error, ApiRejectedError) and error.status == 403:
        hints["Forbidden"] = forbidden
    fail_api(error, not_found=not_found, conflict=conflict, by_error_code=hints)


def already_done(current: object, message: str) -> None:
    """Pedido idempotente que não muda nada: a nota e, em JSON, o recurso atual."""
    ui.note(message)
    if output.is_json():
        output.emit(current)


PersonNameOption = Annotated[
    str | None,
    typer.Option(
        "--name",
        help=option(
            "Name (up to 256 characters).",
            kind="String",
            variable=None,
            file=None,
            default="none",
        ),
    ),
]
PersonSurnameOption = Annotated[
    str | None,
    typer.Option(
        "--surname",
        help=option(
            "Surname (up to 256 characters).",
            kind="String",
            variable=None,
            file=None,
            default="none",
        ),
    ),
]


class Converging(Protocol):
    """Recurso do Resource Control Loop: a fase diz se ele convergiu (`Ready`)."""

    @property
    def phase(self) -> str: ...


class ReadResource[R](Protocol):
    def __call__(
        self, api_url: str, /, *, token: str, resource_id: str, allow_insecure_http: bool
    ) -> R: ...


class ReadOperation(Protocol):
    def __call__(
        self,
        api_url: str,
        /,
        *,
        token: str,
        resource_id: str,
        operation_id: str,
        allow_insecure_http: bool,
    ) -> OperationStatus: ...


class GetCommand(Protocol):
    def __call__(self, accepted: RequestAccepted, *, with_operation: bool = False) -> str: ...


@dataclass(frozen=True)
class ResourceFlow[R: Converging]:
    """Acompanhamento de um pedido assíncrono de um recurso (`--wait`), igual para todos os tipos.

    Cada comando declara só o que muda (o nome do recurso, as leituras, as linhas do painel e as
    mensagens); a espera, o prazo, a leitura do token a cada volta e os painéis são os mesmos.
    """

    subject: str  # como o recurso aparece nas mensagens ("role", "Billing Account")
    get_command: GetCommand
    read_resource: ReadResource[R]
    read_operation: ReadOperation
    fail_api: Callable[[ApiError], NoReturn]
    rejection_hints: Mapping[str, str]
    rows: Callable[[R], list[tuple[str, str]]]
    removed_key: str = "state"
    inspect_row: bool = False  # o painel de aceite traz o comando que inspeciona a Operation

    def accepted_panel(
        self, title: str, accepted: RequestAccepted, *extra: tuple[str, str], wait: bool
    ) -> None:
        # Em JSON, o aceite é o resultado sem --wait; com --wait, o resultado é o recurso.
        rows = [
            *extra,
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ]
        if self.inspect_row:
            rows.append(("inspect", self.get_command(accepted, with_operation=True)))
        ui.panel(title, rows, data=accepted, interim=wait)

    def timed_out(
        self, timeout: int, accepted: RequestAccepted, state: str = "is not visible yet"
    ) -> NoReturn:
        ui.error(
            "Timed out",
            f"{timeout} s passed and the {self.subject} {state}.",
            hint=f"The request is still in progress: `{self.get_command(accepted)}`.",
        )
        raise typer.Exit(EXIT_FAILURE)

    def wait_for_convergence(
        self,
        url: str,
        insecure: bool,
        accepted: RequestAccepted,
        *,
        removal: bool,
        timeout: int,
        matches: Callable[[R], bool] | None = None,
    ) -> R | None:
        """Espera a Operation `completed` e o recurso `Ready` (e, se pedido, com `matches`).

        Na remoção, devolve `None` quando o recurso já não existe. Se não der, sai dizendo por
        quê. O token é pedido a cada leitura: o acesso dura 15 minutos, e uma espera longa
        (`--timeout`) pode atravessar o vencimento (a sessão se renova pelo refresh token).
        """
        with ui.waiting(timeout) as progress:
            progress.update("Operation submitted")
            deadline = time.monotonic() + timeout
            while True:
                token = session_token()
                resource: R | None = None
                try:
                    operation = self.read_operation(
                        url,
                        token=token,
                        resource_id=accepted.resource_id,
                        operation_id=accepted.operation_id,
                        allow_insecure_http=insecure,
                    )
                    progress.update(f"Operation {operation.operation_status}")
                    # Recusa ou falha primeiro: num `create` recusado, o recurso nem existe (`404`).
                    if operation.operation_status in ("rejected", "failed", "superseded"):
                        reason = operation.reason
                        hint = self.rejection_hints.get(reason or "", "Inspect the request.")
                        ui.error(
                            "Request not completed",
                            f"The Operation ended as {operation.operation_status}"
                            + (f": {reason}" if reason else "."),
                            hint=f"{hint} Details: "
                            f"`{self.get_command(accepted, with_operation=True)}`.",
                        )
                        raise typer.Exit(EXIT_FAILURE)
                    try:
                        resource = self.read_resource(
                            url,
                            token=token,
                            resource_id=accepted.resource_id,
                            allow_insecure_http=insecure,
                        )
                    except ApiRejectedError as error:
                        # Na remoção, o `404` do recurso é o esperado (a linha foi apagada).
                        if not (removal and error.status == HTTP_NOT_FOUND):
                            raise
                except OidcError as error:
                    bad_address(error)
                except ApiRejectedError as error:
                    if error.status != HTTP_NOT_FOUND:
                        self.fail_api(error)
                    # Logo depois do `202`, o Manager ainda pode não ter gravado a Operation e o
                    # recurso (`docs/loop/RESOURCE-CONTROL-LOOP.md` §6.1.1): é espera, e não erro.
                    if time.monotonic() >= deadline:
                        self.timed_out(timeout, accepted)
                    time.sleep(WAIT_POLL_SECONDS)
                    continue
                except ApiError as error:
                    self.fail_api(error)
                if resource is not None:
                    progress.update(
                        f"phase {resource.phase}, Operation {operation.operation_status}"
                    )
                if operation.operation_status == "completed":
                    if removal and resource is None:
                        return None
                    if (
                        not removal
                        and resource is not None
                        and resource.phase == "Ready"
                        and (matches is None or matches(resource))
                    ):
                        return resource
                if time.monotonic() >= deadline:
                    where = (
                        f"is in phase {resource.phase}" if resource is not None else "was removed"
                    )
                    self.timed_out(
                        timeout, accepted, f"{where} (Operation {operation.operation_status})"
                    )
                time.sleep(WAIT_POLL_SECONDS)

    def finish(
        self,
        url: str,
        insecure: bool,
        accepted: RequestAccepted,
        *,
        title: str,
        removal: bool,
        wait: bool,
        timeout: int,
        matches: Callable[[R], bool] | None = None,
    ) -> R | None:
        """Fim de `create`, `update` e `delete`: orienta o acompanhamento ou, com `--wait`, espera.

        Devolve o recurso convergido, ou `None` sem `--wait` e quando ele foi removido.
        """
        if not wait:
            ui.note(f"Follow it with `{self.get_command(accepted)}`.")
            return None
        resource = self.wait_for_convergence(
            url, insecure, accepted, removal=removal, timeout=timeout, matches=matches
        )
        if resource is None:
            ui.panel(
                title,
                [("resourceId", accepted.resource_id), (self.removed_key, "removed")],
                data={"resourceId": accepted.resource_id, "state": "removed"},
            )
            return None
        ui.panel(title, self.rows(resource), data=resource)
        return resource


class Generational(Converging, Protocol):
    """Recurso de API síncrona (decisão 0098): a convergência se lê nas gerações e na fase."""

    @property
    def resource_id(self) -> str: ...

    @property
    def desired_generation(self) -> int: ...

    @property
    def observed_generation(self) -> int | None: ...

    @property
    def failure_reason(self) -> str | None: ...


@dataclass(frozen=True)
class SyncResourceFlow[R: Generational]:
    """Acompanhamento de uma escrita de API síncrona (`--wait`), sem Operation (decisão 0098).

    A API devolve o recurso já admitido (`201`, `200` ou `202`). A alteração terminou quando
    `observedGeneration` alcança a geração desejada devolvida e a fase é `Ready` (ou `Failed`,
    que é falha); na remoção, quando o recurso deixa de existir (`404`).
    """

    subject: str  # como o recurso aparece nas mensagens ("service account")
    get_command: Callable[[str], str]
    read_resource: ReadResource[R]
    fail_api: Callable[[ApiError], NoReturn]
    rows: Callable[[R], list[tuple[str, str]]]
    removed_key: str = "state"

    def requested_panel(self, title: str, resource: R, *extra: tuple[str, str], wait: bool) -> None:
        # Em JSON, o recurso admitido é o resultado sem --wait; com --wait, é o convergido.
        rows = [*extra, ("resourceId", resource.resource_id), ("phase", resource.phase)]
        ui.panel(title, rows, data=resource, interim=wait)

    def timed_out(self, timeout: int, resource_id: str, state: str) -> NoReturn:
        ui.error(
            "Timed out",
            f"{timeout} s passed and the {self.subject} {state}.",
            hint=f"The request is still in progress: `{self.get_command(resource_id)}`.",
        )
        raise typer.Exit(EXIT_FAILURE)

    def wait_for_convergence(
        self, url: str, insecure: bool, admitted: R, *, removal: bool, timeout: int
    ) -> R | None:
        """Espera a geração admitida ser observada. Na remoção, devolve `None` com o `404`.

        O token é pedido a cada leitura: o acesso dura 15 minutos, e uma espera longa
        (`--timeout`) pode atravessar o vencimento (a sessão se renova pelo refresh token).
        """
        target = admitted.desired_generation
        with ui.waiting(timeout) as progress:
            progress.update("request admitted")
            deadline = time.monotonic() + timeout
            while True:
                try:
                    current = self.read_resource(
                        url,
                        token=session_token(),
                        resource_id=admitted.resource_id,
                        allow_insecure_http=insecure,
                    )
                except OidcError as error:
                    bad_address(error)
                except ApiRejectedError as error:
                    # Na remoção, o `404` é o esperado (o Controller apagou o registro).
                    if removal and error.status == HTTP_NOT_FOUND:
                        return None
                    self.fail_api(error)
                except ApiError as error:
                    self.fail_api(error)
                observed = current.observed_generation
                progress.update(f"phase {current.phase}, generation {observed or 0} of {target}")
                if observed is not None and observed >= target:
                    if current.phase == "Failed":
                        reason = current.failure_reason
                        ui.error(
                            "Request not completed",
                            f"The {self.subject} ended in phase Failed"
                            + (f": {reason}" if reason else "."),
                            hint=f"Inspect it with `{self.get_command(admitted.resource_id)}`.",
                        )
                        raise typer.Exit(EXIT_FAILURE)
                    if not removal and current.phase == "Ready":
                        return current
                if time.monotonic() >= deadline:
                    self.timed_out(timeout, admitted.resource_id, f"is in phase {current.phase}")
                time.sleep(WAIT_POLL_SECONDS)

    def finish(
        self,
        url: str,
        insecure: bool,
        admitted: R,
        *,
        title: str,
        removal: bool,
        wait: bool,
        timeout: int,
    ) -> R | None:
        """Fim de `create`, `update` e `delete`: orienta o acompanhamento ou, com `--wait`, espera.

        Devolve o recurso convergido, ou `None` sem `--wait` e quando ele foi removido.
        """
        if not wait:
            ui.note(f"Follow it with `{self.get_command(admitted.resource_id)}`.")
            return None
        resource = self.wait_for_convergence(
            url, insecure, admitted, removal=removal, timeout=timeout
        )
        if resource is None:
            ui.panel(
                title,
                [("resourceId", admitted.resource_id), (self.removed_key, "removed")],
                data={"resourceId": admitted.resource_id, "state": "removed"},
            )
            return None
        ui.panel(title, self.rows(resource), data=resource)
        return resource
