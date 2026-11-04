"""Comandos `sk bsm account` e `sk bsm payment`: criar, consultar, alterar, proteger e remover
Billing Accounts e métodos de pagamento.

Usam o token da sessão (`sk auth login`), renovado quando está para vencer. A API é a mesma do
`sk cam account create` (`[api] url`). Criar, alterar e remover são admitidos na hora pela API
(decisão 0098). A Billing Account (`bsm.account`) é `internal-state` e nasce convergida; o método
de pagamento (`bsm.payment`) é `external-reconciled` e converge após validação no gateway de
pagamento. Com `--wait`, o comando espera `observedGeneration` alcançar a geração admitida. O token
precisa trazer as permissões `bsm.account.*` ou `bsm.payment.*`.
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
    validate_account_type,
    validate_billing_contacts,
    validate_billing_currency,
    validate_customer_account_id,
    validate_display_name,
)
from sk.features.bsm.payment import (
    Payment,
    create_payment,
    delete_payment,
    get_payment,
    list_payments,
    set_payment_protection,
    update_payment,
    validate_method_type,
    validate_provider,
    validate_provider_token,
)
from sk.features.bsm.payment import (
    validate_display_name as validate_payment_display_name,
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
            "sk bsm account create --type free --customer-account 394397791373230085 \\\n"
            "      --display-name Acme --currency BRL --billing-contacts finops@acme.com",
            "sk bsm payment list",
            "sk bsm payment create --customer-account 394397791373230085 \\\n"
            "      --display-name 'Corporate Visa' --card-nonce sim_visa_4242",
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
            "sk bsm account create --type free --customer-account 394397791373230085 \\\n"
            "      --display-name Acme --currency BRL --billing-contacts finops@acme.com",
            "sk bsm account get",
            "sk bsm account protect",
            "sk bsm account delete",
        ],
    ),
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
bsm_app.add_typer(account_app, name="account")

payment_app = SkTyper(
    help=command(
        "Manage Payment Methods (tokenized credit cards registered with an external gateway).",
        examples=[
            "sk bsm payment list",
            "sk bsm payment create --customer-account 394397791373230085 \\\n"
            "      --display-name 'Corporate Visa' --card-nonce sim_visa_4242",
            "sk bsm payment get --resource-id pay-123456",
            "sk bsm payment unprotect --resource-id pay-123456",
            "sk bsm payment delete --resource-id pay-123456",
        ],
    ),
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
bsm_app.add_typer(payment_app, name="payment")

PHASE_STYLES = {
    "Ready": "green",
    "Provisioning": "cyan",
    "Pending": "cyan",
    "Reconciling": "cyan",
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
    "PaymentMethodRequired": (
        "The Customer Account does not have an active payment method for a paid Billing Account. "
        "Create and converge one with `sk bsm payment create` first."
    ),
    "QuotaExceeded": "Billing Account quota reached for your user.",
}
NO_PERMISSION_HINT = (
    "Your authenticated user does not have permission for this Billing Account operation. "
    "Enable the bsm service (`sk sum service enable --service bsm`) or ask an administrator "
    "for the corresponding bsm.account.* permission."
)

PAYMENT_CONFLICT_ON_CHANGE = (
    "The Payment Method was changed by someone else since it was read. Read it again with "
    "`sk bsm payment get` and repeat the command."
)
PAYMENT_NOT_FOUND = "Payment Method not found."
PAYMENT_ERROR_CODE_HINTS = {
    "DisplayNameInUse": "A Payment Method with this display name already exists for your account.",
    "EmailNotVerified": (
        "Your e-mail has not been verified yet. Check your inbox and follow the confirmation link."
    ),
    "DeletionProtected": (
        "The Payment Method is protected against deletion. Run `sk bsm payment unprotect` first."
    ),
    "ResourcesAttached": (
        "The Payment Method is attached to an active paid Billing Account. "
        "Update the Billing Account to another payment method or delete it first."
    ),
    "QuotaExceeded": "Payment Method quota reached for your Customer Account.",
}
PAYMENT_NO_PERMISSION_HINT = (
    "Your authenticated user does not have permission for this Payment Method operation. "
    "Enable the bsm service (`sk sum service enable --service bsm`) or ask an administrator "
    "for the corresponding bsm.payment.* permission."
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
PaymentWaitOption = Annotated[
    bool,
    typer.Option(
        "--wait/--no-wait",
        help=option(
            "Wait for the Payment Method to converge in the external gateway (phase Ready, "
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
PaymentResourceIdOption = Annotated[
    str | None,
    typer.Option(
        "--resource-id",
        help=option(
            "resourceId of the Payment Method (returned by `create` or `list`).",
            kind="String",
            variable=None,
            file=None,
            default="none",
        ),
    ),
]
BillingContactsOption = Annotated[
    list[str] | None,
    typer.Option(
        "--billing-contacts",
        help=option(
            "Billing contact e-mail(s) (1 to 10 unique e-mails, repeatable or comma-separated).",
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


def _fail_payment_api(error: ApiError, *, not_found: str = PAYMENT_NOT_FOUND) -> NoReturn:
    fail_api_with_forbidden(
        error,
        not_found=not_found,
        conflict=PAYMENT_CONFLICT_ON_CHANGE,
        by_error_code=PAYMENT_ERROR_CODE_HINTS,
        forbidden=PAYMENT_NO_PERMISSION_HINT,
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


def _account_type(value: str | None) -> str:
    required = require(value, "--type")
    try:
        return validate_account_type(required)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix --type and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _customer_account_id(value: str | None) -> str:
    required = require(value, "--customer-account")
    try:
        return validate_customer_account_id(required)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix --customer-account and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _display_name(value: str | None) -> str:
    required = require(value, "--display-name")
    try:
        return validate_display_name(required)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix --display-name and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _payment_display_name(value: str | None) -> str:
    required = require(value, "--display-name")
    try:
        return validate_payment_display_name(required)
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
        require(None, "--billing-contacts")
    expanded = [item.strip() for raw in (values or []) for item in raw.split(",") if item.strip()]
    try:
        return validate_billing_contacts(expanded)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix --billing-contacts and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _payment_id_for_create(account_type: str, payment_id: str | None) -> str | None:
    if account_type == "paid":
        if payment_id is None:
            ui.error(
                "Missing required option",
                "Option --payment-id is required when --type is paid.",
                hint=(
                    "Repeat with --payment-id VALUE "
                    "(create one first with `sk bsm payment create`)."
                ),
            )
            raise typer.Exit(EXIT_USAGE_ERROR)
        return identifier(payment_id, "--payment-id", what="paymentId")
    if payment_id is not None:
        ui.error(
            "Value not accepted",
            "Option --payment-id is only allowed when --type is paid.",
            hint="Omit --payment-id for free Billing Accounts or use --type paid.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    return None


def _provider(value: str) -> str:
    try:
        return validate_provider(value)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix --provider and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _method_type(value: str) -> str:
    try:
        return validate_method_type(value)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix --method-type and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _provider_token(value: str | None) -> str:
    required = require(value, "--provider-token")
    try:
        return validate_provider_token(required)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix --provider-token and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _presence_label(account: BillingAccount) -> str:
    return account.presence or "unknown"


def _styled_phase(account: BillingAccount | Payment) -> Text:
    return Text(account.phase, style=PHASE_STYLES.get(account.phase, "yellow"))


def _rows(account: BillingAccount) -> list[tuple[str, str]]:
    rows = [
        ("resourceId", account.resource_id),
        ("type", account.account_type),
    ]
    if account.customer_account_id:
        rows.append(("customerAccountId", account.customer_account_id))
    if account.payment_id:
        rows.append(("paymentId", account.payment_id))
    rows.extend(
        [
            ("displayName", account.display_name),
            ("billingCurrency", account.billing_currency),
            ("billingContacts", ", ".join(account.billing_contacts)),
            ("presence", _presence_label(account)),
            ("phase", account.phase),
            ("protected", "yes" if account.deletion_protection else "no"),
        ]
    )
    return rows


def _payment_rows(payment: Payment) -> list[tuple[str, str]]:
    rows = [
        ("resourceId", payment.resource_id),
        ("customerAccountId", payment.customer_account_id),
        ("displayName", payment.display_name),
        ("provider", payment.provider),
        ("methodType", payment.method_type),
    ]
    if payment.status:
        rows.append(("status", payment.status))
    if payment.brand:
        rows.append(("brand", payment.brand))
    if payment.last_four_digits:
        rows.append(("lastFourDigits", payment.last_four_digits))
    if payment.expiration_month is not None and payment.expiration_year is not None:
        rows.append(("expiration", f"{payment.expiration_month:02d}/{payment.expiration_year}"))
    rows.extend(
        [
            ("presence", payment.presence or "unknown"),
            ("phase", payment.phase),
            ("protected", "yes" if payment.deletion_protection else "no"),
        ]
    )
    return rows


def _get_command(resource_id: str) -> str:
    parts = ["sk bsm account get"]
    if resource_id != _active_account():
        parts.append(f"--resource-id {resource_id}")
    return " ".join(parts)


def _get_payment_command(resource_id: str) -> str:
    return f"sk bsm payment get --resource-id {resource_id}"


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

_payment_flow = SyncResourceFlow(
    subject="Payment Method",
    get_command=_get_payment_command,
    read_resource=get_payment,
    fail_api=_fail_payment_api,
    rows=_payment_rows,
    removed_key="presence",
)


@account_app.command(
    "create",
    structured=True,
    help=command(
        "Create a Billing Account.",
        examples=[
            "sk bsm account create --type free --customer-account 394397791373230085 \\\n"
            "      --display-name Acme --currency BRL --billing-contacts fin@acme.com --wait",
            "sk bsm account create --type paid --customer-account 394397791373230085 \\\n"
            "      --payment-id pay-123456 --display-name 'Acme Prod' \\\n"
            "      --currency BRL --billing-contacts fin@acme.com --wait",
        ],
    ),
)
def create_command(
    account_type: Annotated[
        str | None,
        typer.Option(
            "--type",
            help=option(
                "Billing Account type (immutable after creation): free or paid.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    customer_account: Annotated[
        str | None,
        typer.Option(
            "--customer-account",
            help=option(
                "Customer Account ID (cam.account resourceId) that owns this Billing Account.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    payment_id: Annotated[
        str | None,
        typer.Option(
            "--payment-id",
            help=option(
                "Payment Method resourceId (bsm.payment), required when --type is paid.",
                kind="String",
                variable=None,
                file=None,
                default="none (free) or required (paid)",
            ),
        ),
    ] = None,
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
    billing_contacts: BillingContactsOption = None,
    wait: WaitOption = True,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    account_type = _account_type(account_type)
    customer_account = _customer_account_id(customer_account)
    validated_payment_id = _payment_id_for_create(account_type, payment_id)
    display_name = _display_name(display_name)
    currency = _currency(currency)
    contacts = _contacts(billing_contacts)
    url, insecure = load_api()
    token = session_token()
    try:
        account = create_account(
            url,
            token=token,
            account_type=account_type,
            customer_account_id=customer_account,
            payment_id=validated_payment_id,
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
        "Update the display name, billing contacts or payment method of a Billing Account, "
        "reading the current version before asking."
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
    billing_contacts: Annotated[
        list[str] | None,
        typer.Option(
            "--billing-contacts",
            help=option(
                "New billing contact e-mail(s) (replaces the list, repeatable or comma-separated).",
                kind="String",
                variable=None,
                file=None,
                default="unchanged",
            ),
        ),
    ] = None,
    payment_id: Annotated[
        str | None,
        typer.Option(
            "--payment-id",
            help=option(
                "New Payment Method resourceId (bsm.payment) for a paid Billing Account.",
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
    if display_name is None and not billing_contacts and payment_id is None:
        ui.error(
            "Missing required option",
            "Provide --display-name, --billing-contacts and/or --payment-id.",
            hint=(
                "Repeat the command with --display-name VALUE, --billing-contacts EMAIL "
                "or --payment-id VALUE."
            ),
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    validated_name = _display_name(display_name) if display_name is not None else None
    validated_contacts = _contacts(billing_contacts) if billing_contacts else None
    validated_payment = (
        identifier(payment_id, "--payment-id", what="paymentId") if payment_id is not None else None
    )
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
        same_payment = validated_payment is None or current.payment_id == validated_payment
        if same_name and same_contacts and same_payment:
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
            payment_id=None if same_payment else validated_payment,
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


# -----------------------------------------------------------------------------
# Subcomandos `sk bsm payment`
# -----------------------------------------------------------------------------


@payment_app.command(
    "create",
    structured=True,
    help=command(
        "Register and validate a Payment Method in the external payment gateway.",
        examples=[
            "sk bsm payment create --customer-account 394397791373230085 \\\n"
            "      --display-name 'Corporate Visa' --card-nonce sim_visa_4242 --wait"
        ],
    ),
)
def payment_create_command(
    customer_account: Annotated[
        str | None,
        typer.Option(
            "--customer-account",
            help=option(
                "Customer Account ID (cam.account resourceId) that owns this Payment Method.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    display_name: Annotated[
        str | None,
        typer.Option(
            "--display-name",
            help=option(
                "Payment Method display name: 1 to 128 visible characters.",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    provider: Annotated[
        str,
        typer.Option(
            "--provider",
            help=option(
                "External payment gateway provider (immutable after creation): mercadopago.",
                kind="String",
                variable=None,
                file=None,
                default="mercadopago",
            ),
        ),
    ] = "mercadopago",
    method_type: Annotated[
        str,
        typer.Option(
            "--method-type",
            help=option(
                "Payment method modality (immutable after creation): credit_card.",
                kind="String",
                variable=None,
                file=None,
                default="credit_card",
            ),
        ),
    ] = "credit_card",
    provider_token: Annotated[
        str | None,
        typer.Option(
            "--provider-token",
            "--card-nonce",
            help=option(
                "Single-use card tokenization nonce emitted by the payment gateway SDK "
                "(never pass raw card numbers or CVV).",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    wait: PaymentWaitOption = True,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    validated_customer = _customer_account_id(customer_account)
    validated_name = _payment_display_name(display_name)
    validated_provider = _provider(provider)
    validated_method_type = _method_type(method_type)
    validated_token = _provider_token(provider_token)
    url, insecure = load_api()
    token = session_token()
    try:
        payment = create_payment(
            url,
            token=token,
            customer_account_id=validated_customer,
            display_name=validated_name,
            provider=validated_provider,
            method_type=validated_method_type,
            provider_token=validated_token,
            idempotency_key=str(uuid.uuid4()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_payment_api(error)
    _payment_flow.requested_panel("Creation requested", payment, wait=wait)
    _payment_flow.finish(
        url,
        insecure,
        payment,
        title="Payment Method created",
        removal=False,
        wait=wait,
        timeout=timeout,
    )


@payment_app.command(
    "update",
    structured=True,
    help=command(
        "Update the display name or replace the card nonce of a Payment Method, reading the "
        "current version before asking."
    ),
)
def payment_update_command(
    resource_id: PaymentResourceIdOption = None,
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
    provider_token: Annotated[
        str | None,
        typer.Option(
            "--provider-token",
            "--card-nonce",
            help=option(
                "New single-use card tokenization nonce to replace the stored card in the gateway.",
                kind="String",
                variable=None,
                file=None,
                default="unchanged",
            ),
        ),
    ] = None,
    wait: PaymentWaitOption = True,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    rid = identifier(resource_id, "--resource-id", what="resourceId")
    if display_name is None and provider_token is None:
        ui.error(
            "Missing required option",
            "Provide --display-name and/or --provider-token.",
            hint="Repeat the command with --display-name VALUE or --provider-token VALUE.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)
    validated_name = _payment_display_name(display_name) if display_name is not None else None
    validated_token = _provider_token(provider_token) if provider_token is not None else None
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_payment(url, token=token, resource_id=rid, allow_insecure_http=insecure)
        same_name = validated_name is None or current.display_name == validated_name
        if same_name and validated_token is None:
            already_done(current, f"Payment Method {rid} already has these values. Nothing to do.")
            return
        payment = update_payment(
            url,
            token=token,
            resource_id=rid,
            resource_version=current.resource_version,
            display_name=None if same_name else validated_name,
            provider_token=validated_token,
            idempotency_key=str(uuid.uuid4()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_payment_api(error)
    _payment_flow.requested_panel("Change requested", payment, wait=wait)
    _payment_flow.finish(
        url,
        insecure,
        payment,
        title="Payment Method updated",
        removal=False,
        wait=wait,
        timeout=timeout,
    )


def _set_payment_protection(
    resource_id: str | None, *, protected: bool, wait: bool, timeout: int
) -> None:
    rid = identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_payment(url, token=token, resource_id=rid, allow_insecure_http=insecure)
        if current.deletion_protection == protected:
            state = "protected" if protected else "unprotected"
            already_done(current, f"Payment Method {rid} is already {state}. Nothing to do.")
            return
        payment = set_payment_protection(
            url,
            token=token,
            resource_id=rid,
            resource_version=current.resource_version,
            protected=protected,
            idempotency_key=str(uuid.uuid4()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_payment_api(error)
    _payment_flow.requested_panel("Change requested", payment, wait=wait)
    _payment_flow.finish(
        url,
        insecure,
        payment,
        title="Payment Method protected" if protected else "Payment Method unprotected",
        removal=False,
        wait=wait,
        timeout=timeout,
    )


@payment_app.command(
    "protect",
    structured=True,
    help=command("Protect a Payment Method against deletion (the default for new ones)."),
)
def payment_protect_command(
    resource_id: PaymentResourceIdOption = None,
    wait: PaymentWaitOption = True,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    _set_payment_protection(resource_id, protected=True, wait=wait, timeout=timeout)


@payment_app.command(
    "unprotect",
    structured=True,
    help=command("Allow a Payment Method to be deleted. Required before `delete`."),
)
def payment_unprotect_command(
    resource_id: PaymentResourceIdOption = None,
    wait: PaymentWaitOption = True,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    _set_payment_protection(resource_id, protected=False, wait=wait, timeout=timeout)


@payment_app.command(
    "delete",
    structured=True,
    help=command("Delete a Payment Method, reading the current version before asking."),
)
def payment_delete_command(
    resource_id: PaymentResourceIdOption = None,
    wait: PaymentWaitOption = True,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    rid = identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_payment(url, token=token, resource_id=rid, allow_insecure_http=insecure)
        payment = delete_payment(
            url,
            token=token,
            resource_id=rid,
            resource_version=current.resource_version,
            idempotency_key=str(uuid.uuid4()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_payment_api(error)
    _payment_flow.requested_panel("Deletion requested", payment, wait=wait)
    _payment_flow.finish(
        url,
        insecure,
        payment,
        title="Payment Method deleted",
        removal=True,
        wait=wait,
        timeout=timeout,
    )


@payment_app.command(
    "get",
    structured=True,
    help=command("Show the state of a Payment Method."),
)
def payment_get_command(
    resource_id: PaymentResourceIdOption = None,
) -> None:
    rid = identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        payment = get_payment(url, token=token, resource_id=rid, allow_insecure_http=insecure)
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_payment_api(error)
    ui.panel("Payment Method", _payment_rows(payment), data=payment)


@payment_app.command("list", structured=True, help=command("List the requester's Payment Methods."))
def payment_list_command() -> None:
    url, insecure = load_api()
    token = session_token()
    try:
        payments = list_payments(url, token=token, allow_insecure_http=insecure)
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_payment_api(error)
    if not payments:
        ui.empty("No Payment Methods.")
        return
    ui.table(
        "Payment Methods",
        ["name", "resourceId", "phase"],
        [[p.display_name, p.resource_id, _styled_phase(p)] for p in payments],
        data=payments,
    )
