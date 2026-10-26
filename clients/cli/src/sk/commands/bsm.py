"""Comandos `sk bsm account`: criar, consultar, alterar, proteger e remover Billing Accounts.

Usam o token da sessão (`sk auth login`), renovado quando está para vencer. A API é a mesma do
`sk account create` (`[api] url`). Criar, alterar e remover são assíncronos: o comando mostra como
acompanhar a Operation e, com `--wait`, espera a Billing Account convergir. O token precisa trazer
as permissões `bsm.account.*`.
"""

import time
import uuid
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError
from rich.text import Text

from sk import ui
from sk.commands.config import known_keys, store_value
from sk.commands.shared import (
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    EXIT_FAILURE,
    EXIT_USAGE_ERROR,
    HTTP_NOT_FOUND,
    WAIT_POLL_SECONDS,
    TimeoutOption,
    bad_address,
    fail_api,
    load_api,
    require,
    session_token,
)
from sk.features.api_contract import OperationStatus, RequestAccepted, validate_identifier
from sk.features.bsm.account import (
    BillingAccount,
    create_account,
    delete_account,
    get_account,
    get_operation,
    list_accounts,
    set_account_protection,
    update_account,
    validate_billing_contacts,
    validate_billing_currency,
    validate_display_name,
)
from sk.help import command, option
from sk.http import ApiError, ApiRejectedError
from sk.identity.oidc import OidcError
from sk.settings import ConfigurationError, SkSettings, config_file_path, read_config_document

ACTIVE_ACCOUNT_KEY = "bsm.accountId"

BSM_HELP = command("Resources of the Billing Service Manager (BSM).")
ACCOUNT_HELP = command(
    "Create, inspect, update, protect and delete the requester's Billing Accounts."
)

NOT_FOUND = "Billing Account not found for your account."
CONFLICT_ON_CHANGE = "The Billing Account changed since it was last read. Inspect it and try again."
PROTECTED_HINT = (
    "The Billing Account is protected against deletion. Run `sk bsm account unprotect` first."
)
REJECTION_HINTS = {
    "validation": "The displayName is already in use for your account, or the request is invalid.",
    "conflict": CONFLICT_ON_CHANGE,
    "not_found": NOT_FOUND,
    "protected": PROTECTED_HINT,
}
ERROR_CODE_HINTS = {
    "DeletionProtected": PROTECTED_HINT,
    "EmailNotVerified": (
        "Your e-mail is not verified yet. Open the link in the activation e-mail and repeat."
    ),
    "QuotaExceeded": "You reached the Billing Account limit. Delete one or ask an operator.",
}
NO_PERMISSION_HINT = (
    "Your account does not have permission for this operation. Ensure you have the required "
    "bsm.account.* permission and renew the session with `sk auth refresh`."
)

PRESENCE_STYLES = {"present": "green", "absent": "dim"}
PHASE_STYLES = {
    "Ready": "green",
    "Failed": "red",
}  # as demais fases (em andamento) ficam em amarelo

bsm_app = typer.Typer(
    help=BSM_HELP,
    no_args_is_help=True,
    # Ajuda colorida pelo Rich. Colchetes literais nos textos são escapados com "\\[".
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
account_app = typer.Typer(
    help=ACCOUNT_HELP,
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
bsm_app.add_typer(account_app, name="account")

WaitOption = Annotated[
    bool,
    typer.Option(
        "--wait",
        help=option(
            "Wait for the Billing Account to converge (phase Ready and Operation completed).",
            kind="Boolean",
            variable=None,
            file=None,
            default="off",
        ),
    ),
]
ResourceIdOption = Annotated[
    str | None,
    typer.Option(
        "--resource-id",
        help=option(
            "resourceId of the Billing Account (returned by `create` or `list`). Without it, the "
            "active Billing Account is used (`sk config set bsm.accountId`).",
            kind="String",
            variable=None,
            file=None,
            default="the active Billing Account",
        ),
    ),
]
ContactOption = Annotated[
    list[str] | None,
    typer.Option(
        "--contact",
        help=option(
            "Billing contact e-mail (1 to 10 unique e-mails). Repeat it for more contacts.",
            kind="String",
            variable=None,
            file=None,
            default="none",
        ),
    ),
]


def _fail_api(error: ApiError, *, not_found: str = NOT_FOUND) -> NoReturn:
    if isinstance(error, ApiRejectedError) and error.status == 403:
        by_code = {**ERROR_CODE_HINTS, "Forbidden": NO_PERMISSION_HINT}
    else:
        by_code = ERROR_CODE_HINTS
    fail_api(error, not_found=not_found, conflict=CONFLICT_ON_CHANGE, by_error_code=by_code)


def _identifier(value: str | None, option_name: str, *, what: str) -> str:
    """Opção obrigatória que é um identificador do contrato, recusada antes da chamada de rede."""
    try:
        return validate_identifier(require(value, option_name), what=what)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint=f"Fix {option_name} and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _active_account() -> str:
    """`resourceId` da Billing Account ativa (ambiente ou arquivo); vazio se nenhuma."""
    try:
        return SkSettings().bsm.account_id
    except (ValidationError, ConfigurationError) as error:
        ui.error("Invalid configuration", str(error), hint="Fix the indicated file and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _account_identifier(value: str | None) -> str:
    """`resourceId` da Billing Account: `--resource-id` ou, na falta dele, a ativa."""
    if value is None:
        value = _active_account()
        if not value:
            ui.error(
                "Missing Billing Account",
                "No --resource-id was given and no Billing Account is active.",
                hint=(
                    "Repeat with --resource-id VALUE, or make one active with "
                    f"`sk config set {ACTIVE_ACCOUNT_KEY} VALUE` "
                    "(or set SK_BSM_ACCOUNT_ID)."
                ),
            )
            raise typer.Exit(EXIT_USAGE_ERROR)
    return _identifier(value, "--resource-id", what="resourceId")


def _display_name(value: str | None) -> str:
    """`--display-name` obrigatório e dentro do contrato, recusado antes da chamada de rede."""
    try:
        return validate_display_name(require(value, "--display-name"))
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix --display-name and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _currency(value: str | None) -> str:
    """`--currency` obrigatório e dentro do contrato, recusado antes da chamada de rede."""
    try:
        return validate_billing_currency(require(value, "--currency"))
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix --currency and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _contacts(values: list[str] | None) -> list[str]:
    """`--contact` obrigatório e dentro do contrato, recusado antes da chamada de rede."""
    if not values:
        require(None, "--contact")
    try:
        return validate_billing_contacts(values or [])
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix --contact and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _presence_label(account: BillingAccount) -> str:
    return account.presence or "unknown"


def _styled_presence(account: BillingAccount) -> Text:
    return Text(_presence_label(account), style=PRESENCE_STYLES.get(_presence_label(account), ""))


def _styled_phase(account: BillingAccount) -> Text:
    return Text(account.phase, style=PHASE_STYLES.get(account.phase, "yellow"))


def _rows(account: BillingAccount) -> list[tuple[str, str]]:
    return [
        ("resourceId", account.resource_id),
        ("displayName", account.display_name),
        ("billingCurrency", account.billing_currency),
        ("billingContacts", ", ".join(account.billing_contacts)),
        ("presence", _presence_label(account)),
        ("phase", account.phase),
        ("protected", "yes" if account.deletion_protection else "no"),
    ]


def _operation_rows(operation: OperationStatus) -> list[tuple[str, str]]:
    rows = [
        ("operationId", operation.operation_id),
        ("operationStatus", operation.operation_status),
    ]
    if operation.reason is not None:
        rows.append(("reason", operation.reason))
    return rows


def _get_command(accepted: RequestAccepted, *, with_operation: bool = False) -> str:
    """Comando `get` que acompanha o pedido. `--resource-id` só aparece quando a Billing Account
    não é a ativa; `--operation-id` só no diagnóstico de um pedido que não concluiu."""
    parts = ["sk bsm account get"]
    if accepted.resource_id != _active_account():
        parts.append(f"--resource-id {accepted.resource_id}")
    if with_operation:
        parts.append(f"--operation-id {accepted.operation_id}")
    return " ".join(parts)


def _timed_out(
    timeout: int, accepted: RequestAccepted, state: str = "is not visible yet"
) -> NoReturn:
    ui.error(
        "Timed out",
        f"{timeout} s passed and the Billing Account {state}.",
        hint=f"The request is still in progress: `{_get_command(accepted)}`.",
    )
    raise typer.Exit(EXIT_FAILURE)


def _wait_for_convergence(
    url: str,
    insecure: bool,
    accepted: RequestAccepted,
    *,
    expect_display_name: str | None,
    removal: bool,
    timeout: int,
) -> BillingAccount | None:
    """Espera a Operation `completed` (e a Billing Account `Ready` com o nome pedido); se não der,
    sai dizendo por quê. Na remoção, devolve `None` quando a Billing Account já não existe.

    O token é pedido a cada leitura: o acesso dura 15 minutos, e uma espera longa (`--timeout`)
    pode atravessar o vencimento (a sessão se renova pelo refresh token).
    """
    ui.note(f"Waiting for convergence (up to {timeout} s)...")
    deadline = time.monotonic() + timeout
    while True:
        token = session_token()
        account: BillingAccount | None = None
        try:
            operation = get_operation(
                url,
                token=token,
                resource_id=accepted.resource_id,
                operation_id=accepted.operation_id,
                allow_insecure_http=insecure,
            )
            # Recusa ou falha primeiro: num `create` recusado, o recurso nem existe (`404`).
            if operation.operation_status in ("rejected", "failed", "superseded"):
                reason = operation.reason
                ui.error(
                    "Request not completed",
                    f"The Operation ended as {operation.operation_status}"
                    + (f": {reason}" if reason else "."),
                    hint=f"{REJECTION_HINTS.get(reason or '', 'Inspect the request.')} Details: "
                    f"`{_get_command(accepted, with_operation=True)}`.",
                )
                raise typer.Exit(EXIT_FAILURE)
            try:
                account = get_account(
                    url,
                    token=token,
                    resource_id=accepted.resource_id,
                    allow_insecure_http=insecure,
                )
            except ApiRejectedError as error:
                # Na remoção, o `404` da Billing Account é o esperado (a linha foi apagada).
                if not (removal and error.status == HTTP_NOT_FOUND):
                    raise
        except OidcError as error:
            bad_address(error)
        except ApiRejectedError as error:
            if error.status != HTTP_NOT_FOUND:
                _fail_api(error)
            # Logo depois do `202`, o Manager ainda pode não ter gravado a Operation e o recurso
            # (`docs/RESOURCE-CONTROL-LOOP.md` §6.1.1): é espera, e não erro.
            if time.monotonic() >= deadline:
                _timed_out(timeout, accepted)
            time.sleep(WAIT_POLL_SECONDS)
            continue
        except ApiError as error:
            _fail_api(error)
        if operation.operation_status == "completed":
            if removal and account is None:
                return None
            if (
                not removal
                and account is not None
                and account.phase == "Ready"
                and (expect_display_name is None or account.display_name == expect_display_name)
            ):
                return account
        if time.monotonic() >= deadline:
            where = f"is in phase {account.phase}" if account is not None else "was removed"
            _timed_out(timeout, accepted, f"{where} (Operation {operation.operation_status})")
        time.sleep(WAIT_POLL_SECONDS)


def _finish_request(
    url: str,
    insecure: bool,
    accepted: RequestAccepted,
    *,
    title: str,
    expect_display_name: str | None,
    removal: bool,
    wait: bool,
    timeout: int,
) -> BillingAccount | None:
    """Fim de `create`, `update` e `delete`: orienta o acompanhamento ou, com `--wait`, espera.

    Devolve a Billing Account convergida, ou `None` sem `--wait` e quando ela foi removida.
    """
    if not wait:
        ui.note(f"Follow it with `{_get_command(accepted)}`.")
        return None
    account = _wait_for_convergence(
        url,
        insecure,
        accepted,
        expect_display_name=expect_display_name,
        removal=removal,
        timeout=timeout,
    )
    if account is None:
        ui.panel(title, [("resourceId", accepted.resource_id), ("presence", "removed")])
        return None
    ui.panel(title, _rows(account))
    return account


def _activate_if_none(resource_id: str) -> None:
    """Grava a Billing Account recém-criada como a ativa (`[bsm] accountId`), se não há uma.

    Uma Billing Account já ativa, vinda do ambiente ou do arquivo, nunca é trocada: trocar é do
    `sk config set`. Falhar aqui não desfaz nada (a Billing Account já existe): vira aviso.
    """
    switch_hint = f"`sk config set {ACTIVE_ACCOUNT_KEY} {resource_id}`"
    try:
        if SkSettings().bsm.account_id:
            ui.note(
                f"The active Billing Account was kept. To switch to this one, run {switch_hint}."
            )
            return
        path = config_file_path()
        store_value(
            known_keys()[ACTIVE_ACCOUNT_KEY],
            resource_id,
            read_config_document(path),
            path=path,
        )
    except (ValidationError, ConfigurationError, OSError) as error:
        reason = getattr(error, "strerror", None) or str(error).splitlines()[0]
        ui.warning(
            f"Could not save the active Billing Account ({reason}). To do it, run {switch_hint}."
        )
        return
    ui.note(f"Saved as the active Billing Account in {path}.")


@account_app.command(
    "create",
    help=command("Create a Billing Account. Follow it with `sk bsm account get`."),
)
def create_command(
    display_name: Annotated[
        str | None,
        typer.Option(
            "--display-name",
            help=option(
                "Billing Account display name: 1 to 128 visible characters.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    currency: Annotated[
        str | None,
        typer.Option(
            "--currency",
            help=option(
                "Billing currency (immutable after creation): BRL, USD or EUR.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    contact: ContactOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    # Obrigatórias por validação do próprio comando (não pelo Typer), para não exibir "[required]".
    display_name = _display_name(display_name)
    currency = _currency(currency)
    contacts = _contacts(contact)
    url, insecure = load_api()
    token = session_token()
    try:
        accepted = create_account(
            url,
            token=token,
            display_name=display_name,
            billing_currency=currency,
            billing_contacts=contacts,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    ui.panel(
        "Creation requested",
        [
            ("displayName", display_name),
            ("billingCurrency", currency),
            ("billingContacts", ", ".join(contacts)),
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
    )
    account = _finish_request(
        url,
        insecure,
        accepted,
        title="Billing Account created",
        expect_display_name=display_name,
        removal=False,
        wait=wait,
        timeout=timeout,
    )
    if account is not None:
        _activate_if_none(account.resource_id)
    elif not wait:
        ui.note(
            "To make it the active Billing Account, run "
            f"`sk config set {ACTIVE_ACCOUNT_KEY} {accepted.resource_id}`."
        )


@account_app.command(
    "update",
    help=command(
        "Update the display name or billing contacts of a Billing Account, reading the current "
        "version before asking."
    ),
)
def update_command(
    resource_id: ResourceIdOption = None,
    display_name: Annotated[
        str | None,
        typer.Option(
            "--display-name",
            help=option(
                "New display name: 1 to 128 visible characters.",
                kind="String",
                variable=None,
                file=None,
                default="unchanged",
            ),
        ),
    ] = None,
    contact: Annotated[
        list[str] | None,
        typer.Option(
            "--contact",
            help=option(
                "New billing contact e-mail (replaces the list). Repeat it for more contacts.",
                kind="String",
                variable=None,
                file=None,
                default="unchanged",
            ),
        ),
    ] = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    resource_id = _account_identifier(resource_id)
    if display_name is None and not contact:
        ui.error(
            "Missing required option",
            "Provide --display-name and/or --contact.",
            hint="Repeat the command with --display-name VALUE or --contact EMAIL.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    validated_name = _display_name(display_name) if display_name is not None else None
    validated_contacts = _contacts(contact) if contact else None
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_account(
            url, token=token, resource_id=resource_id, allow_insecure_http=insecure
        )
        same_name = validated_name is None or current.display_name == validated_name
        same_contacts = (
            validated_contacts is None or list(current.billing_contacts) == validated_contacts
        )
        if same_name and same_contacts:
            ui.note(f"Billing Account {resource_id} already has these values. Nothing to do.")
            return
        accepted = update_account(
            url,
            token=token,
            resource_id=resource_id,
            resource_version=current.resource_version,
            display_name=None if same_name else validated_name,
            billing_contacts=None if same_contacts else validated_contacts,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    rows: list[tuple[str, str]] = []
    if validated_name is not None and not same_name:
        rows.append(("displayName", validated_name))
    if validated_contacts is not None and not same_contacts:
        rows.append(("billingContacts", ", ".join(validated_contacts)))
    rows.extend([("resourceId", accepted.resource_id), ("operationId", accepted.operation_id)])
    ui.panel("Update requested", rows)
    _finish_request(
        url,
        insecure,
        accepted,
        title="Billing Account updated",
        expect_display_name=validated_name if not same_name else None,
        removal=False,
        wait=wait,
        timeout=timeout,
    )


def _set_protection(resource_id: str | None, *, protected: bool, wait: bool, timeout: int) -> None:
    resource_id = _account_identifier(resource_id)
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_account(
            url, token=token, resource_id=resource_id, allow_insecure_http=insecure
        )
        if current.deletion_protection == protected:
            # Idempotente: pedir o estado que já vale não é erro.
            state = "protected" if protected else "unprotected"
            ui.note(f"Billing Account {resource_id} is already {state}. Nothing to do.")
            return
        accepted = set_account_protection(
            url,
            token=token,
            resource_id=resource_id,
            resource_version=current.resource_version,
            protected=protected,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    ui.panel(
        "Protection change requested",
        [
            ("displayName", current.display_name),
            ("protected", "yes" if protected else "no"),
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
    )
    _finish_request(
        url,
        insecure,
        accepted,
        title="Billing Account protected" if protected else "Billing Account unprotected",
        expect_display_name=None,
        removal=False,
        wait=wait,
        timeout=timeout,
    )


@account_app.command(
    "protect",
    help=command("Protect a Billing Account against deletion (the default for new ones)."),
)
def protect_command(
    resource_id: ResourceIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    _set_protection(resource_id, protected=True, wait=wait, timeout=timeout)


@account_app.command(
    "unprotect",
    help=command("Allow a Billing Account to be deleted. Required before `delete`."),
)
def unprotect_command(
    resource_id: ResourceIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    _set_protection(resource_id, protected=False, wait=wait, timeout=timeout)


@account_app.command(
    "delete",
    help=command("Delete a Billing Account, reading the current version before asking."),
)
def delete_command(
    resource_id: ResourceIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    resource_id = _account_identifier(resource_id)
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_account(
            url, token=token, resource_id=resource_id, allow_insecure_http=insecure
        )
        accepted = delete_account(
            url,
            token=token,
            resource_id=resource_id,
            resource_version=current.resource_version,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    ui.panel(
        "Deletion requested",
        [
            ("displayName", current.display_name),
            ("resourceId", accepted.resource_id),
            ("operationId", accepted.operation_id),
        ],
    )
    if resource_id == _active_account():
        ui.warning(
            "This is the active Billing Account. Once it is gone, point to another with "
            f"`sk config set {ACTIVE_ACCOUNT_KEY} VALUE`."
        )
    _finish_request(
        url,
        insecure,
        accepted,
        title="Billing Account deleted",
        expect_display_name=None,
        removal=True,
        wait=wait,
        timeout=timeout,
    )


@account_app.command(
    "get",
    help=command("Show the state of a Billing Account and, if given, of an Operation."),
)
def get_command(
    resource_id: ResourceIdOption = None,
    operation_id: Annotated[
        str | None,
        typer.Option(
            "--operation-id",
            help=option(
                "operationId of a request, to see why it was rejected or failed (returned by "
                "`create`, `update` or `delete`).",
                kind="String",
                variable=None,
                file=None,
                default="no Operation lookup",
            ),
        ),
    ] = None,
) -> None:
    resource_id = _account_identifier(resource_id)
    if operation_id is not None:
        operation_id = _identifier(operation_id, "--operation-id", what="operationId")
    url, insecure = load_api()
    token = session_token()
    try:
        account = get_account(
            url, token=token, resource_id=resource_id, allow_insecure_http=insecure
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    operation: OperationStatus | None = None
    if operation_id is not None:
        try:
            operation = get_operation(
                url,
                token=token,
                resource_id=resource_id,
                operation_id=operation_id,
                allow_insecure_http=insecure,
            )
        except OidcError as error:
            bad_address(error)
        except ApiError as error:
            _fail_api(error, not_found="Operation not found for this Billing Account.")
    rows = _rows(account)
    if operation is not None:
        rows.extend(_operation_rows(operation))
    ui.panel("Billing Account", rows)


@account_app.command("list", help=command("List the requester's Billing Accounts."))
def list_command() -> None:
    url, insecure = load_api()
    token = session_token()
    try:
        accounts = list_accounts(url, token=token, allow_insecure_http=insecure)
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    if not accounts:
        ui.note("No Billing Accounts.")
        return
    active = _active_account()
    ui.table(
        "Billing Accounts",
        ["active", "resourceId", "displayName", "currency", "presence", "phase"],
        [
            [
                "*" if account.resource_id == active else "",
                account.resource_id,
                account.display_name,
                account.billing_currency,
                _styled_presence(account),
                _styled_phase(account),
            ]
            for account in accounts
        ],
    )
