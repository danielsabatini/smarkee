"""Comandos `sk bsm account`: criar, consultar, alterar, proteger e remover Billing Accounts.

Usam o token da sessão (`sk auth login`), renovado quando está para vencer. A API é a mesma do
`sk account create` (`[api] url`). Criar, alterar e remover são admitidos na hora pela API
(decisão 0098); a Billing Account é dado do SSOT e nasce convergida. Com `--wait`, o comando
espera `observedGeneration` alcançar a geração admitida. O token precisa trazer as permissões
`bsm.account.*`.
"""

import uuid
from typing import Annotated, NoReturn

import typer
from pydantic import ValidationError
from rich.text import Text

from sk import ui
from sk.command_app import SkTyper
from sk.commands.config import known_keys, store_value
from sk.commands.shared import (
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    EXIT_USAGE_ERROR,
    SyncResourceFlow,
    TimeoutOption,
    already_done,
    bad_address,
    fail_api_with_forbidden,
    identifier,
    load_api,
    require,
    session_token,
)
from sk.features.bsm.account import (
    BillingAccount,
    create_account,
    delete_account,
    get_account,
    list_accounts,
    set_account_protection,
    update_account,
    validate_billing_contacts,
    validate_billing_currency,
    validate_display_name,
)
from sk.help import command, option
from sk.http import ApiError
from sk.identity.oidc import OidcError
from sk.settings import (
    ConfigurationError,
    SkSettings,
    config_file_path,
    read_config_document,
)

ACTIVE_ACCOUNT_KEY = "bsm.accountId"

bsm_app = SkTyper(
    help=command(
        "Manage billing and payments in the Smarkee platform.",
        examples=[
            "sk bsm account list",
            "sk bsm account create --display-name Acme --currency BRL --contact finops@acme.com",
            "sk bsm account get",
            "sk bsm account protect",
            "sk bsm account delete",
        ],
    ),
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)

account_app = SkTyper(
    help=command(
        "Manage Billing Accounts (credit balance, invoices, payment methods).",
        examples=[
            "sk bsm account list",
            "sk bsm account create --display-name Acme --currency BRL --contact finops@acme.com",
            "sk bsm account get",
            "sk bsm account protect",
            "sk bsm account delete",
        ],
    ),
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
bsm_app.add_typer(account_app, name="account")

PHASE_STYLES = {
    "Ready": "green",
    "Provisioning": "cyan",
    "Deleting": "magenta",
    "Failed": "red",
}
CONFLICT_ON_CHANGE = (
    "The Billing Account was changed by someone else since it was read. Read it again with "
    "`sk bsm account get` and repeat the command."
)
NOT_FOUND = "Billing Account not found."
ERROR_CODE_HINTS = {
    "DisplayNameInUse": "A Billing Account with this display name already exists for your account.",
    "EmailNotVerified": (
        "Your e-mail has not been verified yet. Check your inbox and follow the confirmation link."
    ),
    "DeletionProtected": (
        "The Billing Account is protected against deletion. Run `sk bsm account unprotect` first."
    ),
    "ResourcesAttached": (
        "The Billing Account has active Organizations attached. Detach or delete them first."
    ),
    "QuotaExceeded": "Billing Account quota reached for your user.",
}
NO_PERMISSION_HINT = (
    "Your authenticated user does not have permission for this Billing Account operation. Ask an "
    "administrator for the corresponding bsm.account.* permission."
)

WaitOption = Annotated[
    bool,
    typer.Option(
        "--wait/--no-wait",
        help=option(
            "Wait for the Billing Account to converge (observed matches desired generation, "
            "default on).",
            kind="Boolean",
            variable=None,
            file=None,
            default="on",
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
    fail_api_with_forbidden(
        error,
        not_found=not_found,
        conflict=CONFLICT_ON_CHANGE,
        by_error_code=ERROR_CODE_HINTS,
        forbidden=NO_PERMISSION_HINT,
    )


def _active_account() -> str | None:
    try:
        return SkSettings().bsm.account_id or None
    except (ValidationError, ConfigurationError) as error:
        ui.error("Invalid configuration", str(error), hint="Fix the indicated file and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _account_identifier(value: str | None) -> str:
    value = value if value is not None else _active_account()
    if not value:
        ui.error(
            "Missing Billing Account",
            "No --resource-id was given and no Billing Account is active.",
            hint=(
                "Repeat with --resource-id VALUE, or make one active with "
                f"`sk config set {ACTIVE_ACCOUNT_KEY} VALUE`."
            ),
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return identifier(value, "--resource-id", what="resourceId")


def _display_name(value: str | None) -> str:
    required = require(value, "--display-name")
    try:
        return validate_display_name(required)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix --display-name and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _currency(value: str | None) -> str:
    required = require(value, "--currency")
    try:
        return validate_billing_currency(required)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix --currency and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _contacts(values: list[str] | None) -> list[str]:
    if not values:
        require(None, "--contact")
    try:
        return validate_billing_contacts(values or [])
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix --contact and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _presence_label(account: BillingAccount) -> str:
    return account.presence or "unknown"


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


def _get_command(resource_id: str) -> str:
    parts = ["sk bsm account get"]
    if resource_id != _active_account():
        parts.append(f"--resource-id {resource_id}")
    return " ".join(parts)


def _activate_if_none(resource_id: str) -> None:
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


_flow = SyncResourceFlow(
    subject="Billing Account",
    get_command=_get_command,
    read_resource=get_account,
    fail_api=_fail_api,
    rows=_rows,
    removed_key="presence",
)


@account_app.command(
    "create",
    structured=True,
    help=command(
        "Create a Billing Account.",
        examples=[
            "sk bsm account create --display-name Acme --currency BRL \\\n"
            "      --contact finance@example.com --wait"
        ],
    ),
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
    wait: WaitOption = True,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    display_name = _display_name(display_name)
    currency = _currency(currency)
    contacts = _contacts(contact)
    url, insecure = load_api()
    token = session_token()
    try:
        account = create_account(
            url,
            token=token,
            display_name=display_name,
            billing_currency=currency,
            billing_contacts=contacts,
            idempotency_key=str(uuid.uuid4()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _flow.requested_panel("Creation requested", account, wait=wait)
    converged = _flow.finish(
        url,
        insecure,
        account,
        title="Billing Account created",
        removal=False,
        wait=wait,
        timeout=timeout,
    )
    if converged is not None:
        _activate_if_none(converged.resource_id)
    elif not wait:
        ui.note(
            "To make it the active Billing Account, run "
            f"`sk config set {ACTIVE_ACCOUNT_KEY} {account.resource_id}`."
        )


@account_app.command(
    "update",
    structured=True,
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
    wait: WaitOption = True,
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
            already_done(
                current, f"Billing Account {resource_id} already has these values. Nothing to do."
            )
            return
        account = update_account(
            url,
            token=token,
            resource_id=resource_id,
            resource_version=current.resource_version,
            display_name=None if same_name else validated_name,
            billing_contacts=None if same_contacts else validated_contacts,
            idempotency_key=str(uuid.uuid4()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _flow.requested_panel("Change requested", account, wait=wait)
    _flow.finish(
        url,
        insecure,
        account,
        title="Billing Account updated",
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
            state = "protected" if protected else "unprotected"
            already_done(
                current, f"Billing Account {resource_id} is already {state}. Nothing to do."
            )
            return
        account = set_account_protection(
            url,
            token=token,
            resource_id=resource_id,
            resource_version=current.resource_version,
            protected=protected,
            idempotency_key=str(uuid.uuid4()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _flow.requested_panel(
        "Change requested",
        account,
        wait=wait,
    )
    _flow.finish(
        url,
        insecure,
        account,
        title="Billing Account protected" if protected else "Billing Account unprotected",
        removal=False,
        wait=wait,
        timeout=timeout,
    )


@account_app.command(
    "protect",
    structured=True,
    help=command("Protect a Billing Account against deletion (the default for new ones)."),
)
def protect_command(
    resource_id: ResourceIdOption = None,
    wait: WaitOption = True,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    _set_protection(resource_id, protected=True, wait=wait, timeout=timeout)


@account_app.command(
    "unprotect",
    structured=True,
    help=command("Allow a Billing Account to be deleted. Required before `delete`."),
)
def unprotect_command(
    resource_id: ResourceIdOption = None,
    wait: WaitOption = True,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    _set_protection(resource_id, protected=False, wait=wait, timeout=timeout)


@account_app.command(
    "delete",
    structured=True,
    help=command("Delete a Billing Account, reading the current version before asking."),
)
def delete_command(
    resource_id: ResourceIdOption = None,
    wait: WaitOption = True,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    resource_id = _account_identifier(resource_id)
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_account(
            url, token=token, resource_id=resource_id, allow_insecure_http=insecure
        )
        account = delete_account(
            url,
            token=token,
            resource_id=resource_id,
            resource_version=current.resource_version,
            idempotency_key=str(uuid.uuid4()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    if resource_id == _active_account():
        ui.warning(
            "This is the active Billing Account. Once it is gone, point to another with "
            f"`sk config set {ACTIVE_ACCOUNT_KEY} VALUE`."
        )
    _flow.requested_panel("Deletion requested", account, wait=wait)
    _flow.finish(
        url,
        insecure,
        account,
        title="Billing Account deleted",
        removal=True,
        wait=wait,
        timeout=timeout,
    )


@account_app.command(
    "get",
    structured=True,
    help=command("Show the state of a Billing Account."),
)
def get_command(
    resource_id: ResourceIdOption = None,
) -> None:
    resource_id = _account_identifier(resource_id)
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
    ui.panel("Billing Account", _rows(account), data=account)


@account_app.command(
    "list", structured=True, help=command("List the requester's Billing Accounts.")
)
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
        ui.empty("No Billing Accounts.")
        return
    ui.table(
        "Billing Accounts",
        ["name", "resourceId", "phase"],
        [[a.display_name, a.resource_id, _styled_phase(a)] for a in accounts],
        data=accounts,
    )
