"""Comandos `sk ipm serviceaccount`: identidades de máquina da Organization (decisão 0094).

Service accounts são identidades de máquina (machine users) no Zitadel, sem senha e sem e-mail,
autenticadas exclusivamente por chave assimétrica (par RSA gerado no cliente). A Organization é
a de `--organization-id` ou, na falta dela, a ativa (`sk config set ipm.organizationId`). Criar,
alterar e remover são assíncronos: com `--wait`, o comando espera convergir.
"""

import contextlib
import hashlib
import json
import uuid
from collections.abc import Sequence
from pathlib import Path
from typing import Annotated, NoReturn

import typer
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from pydantic import ValidationError
from rich.text import Text

from sk import output, ui
from sk.command_app import SkTyper
from sk.commands.shared import (
    DEFAULT_WAIT_TIMEOUT_SECONDS,
    EXIT_USAGE_ERROR,
    ResourceFlow,
    TimeoutOption,
    already_done,
    bad_address,
    fail_api_with_forbidden,
    identifier,
    load_api,
    require,
    session_token,
    usage_error,
)
from sk.features.api_contract import OperationStatus, RequestAccepted
from sk.features.ipm.serviceaccount import (
    MAXIMUM_KEYS,
    ServiceAccount,
    create_serviceaccount,
    delete_serviceaccount,
    get_operation,
    get_serviceaccount,
    list_serviceaccounts,
    update_serviceaccount,
    validate_name,
    validate_roles,
)
from sk.help import command, option
from sk.http import ApiError
from sk.identity.keys import (
    DEFAULT_EXPIRES_IN_DAYS,
    KeyFileError,
    generate_key_pair,
    parse_public_key_file,
    update_key_file,
    write_key_file,
)
from sk.identity.oidc import OidcError
from sk.settings import ConfigurationError, SkSettings

ACTIVE_ORGANIZATION_KEY = "ipm.organizationId"

SERVICEACCOUNT_HELP = command(
    "Create, inspect, update roles and keys, protect and delete service accounts."
)

NOT_FOUND = "Service account not found in an Organization you act on."
CONFLICT_ON_CHANGE = "The service account changed since it was last read. Inspect it and try again."
PROTECTED_HINT = (
    "The service account is protected against deletion. "
    "Run `sk ipm serviceaccount unprotect` first."
)
REJECTION_HINTS = {
    "validation": (
        "The name is in use in the Organization, a role is not allowed, or a key is invalid."
    ),
    "conflict": CONFLICT_ON_CHANGE,
    "not_found": NOT_FOUND,
    "protected": PROTECTED_HINT,
}
ERROR_CODE_HINTS = {
    "DeletionProtected": PROTECTED_HINT,
    "QuotaExceeded": ("The Organization reached its service account limit. Delete an unused one."),
    "OrganizationUnavailable": "The Organization could not be checked now. Try again.",
    "ResourcesAttached": (
        "The Organization cannot be deleted while it still has service accounts."
    ),
}
NO_PERMISSION_HINT = (
    "You do not have permission for this operation. Managing service accounts requires "
    "ipm.serviceaccount.create, ipm.serviceaccount.update or ipm.serviceaccount.bind."
)
ROLES_HINT = "A role is not allowed for the Organization. Use only predefined roles in its catalog."

PHASE_STYLES = {"Ready": "green", "Failed": "red"}

serviceaccount_app = SkTyper(
    help=SERVICEACCOUNT_HELP,
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)

key_app = SkTyper(
    help=command("Manage service account public keys (teto 3 keys, client-side rotation)."),
    no_args_is_help=True,
    rich_markup_mode="rich",
    pretty_exceptions_show_locals=False,
)
serviceaccount_app.add_typer(key_app, name="key")

WaitOption = Annotated[
    bool,
    typer.Option(
        "--wait",
        help=option(
            "Wait for the service account to converge (phase Ready and Operation completed).",
            kind="Boolean",
            variable=None,
            file=None,
            default="off",
        ),
    ),
]
ServiceAccountIdOption = Annotated[
    str | None,
    typer.Option(
        "--resource-id",
        help=option(
            "resourceId of the service account (returned by `create` or `list`).",
            kind="String",
            variable=None,
            file=None,
            default="none",
        ),
    ),
]
OrganizationOption = Annotated[
    str | None,
    typer.Option(
        "--organization-id",
        "-o",
        help=option(
            "Organization to act on. Defaults to the active Organization.",
            kind="String",
            variable="SK_IPM_ORGANIZATION_ID",
            file=ACTIVE_ORGANIZATION_KEY,
            default="none",
        ),
    ),
]
RoleOption = Annotated[
    list[str] | None,
    typer.Option(
        "--role",
        help=option(
            "Composite role in the Organization (repeatable; e.g. ipm.serviceaccountViewer).",
            kind="String",
            variable=None,
            file=None,
            default="no change",
        ),
    ),
]


def _organization(value: str | None) -> str:
    """`--organization-id` ou, na falta dele, a Organization ativa."""
    if value is None:
        try:
            value = SkSettings().ipm.organization_id
        except (ValidationError, ConfigurationError) as error:
            ui.error("Invalid configuration", str(error), hint="Fix the indicated file and repeat.")
            raise typer.Exit(EXIT_USAGE_ERROR) from error
        if not value:
            ui.error(
                "Missing Organization",
                "No --organization-id was given and no Organization is active.",
                hint=(
                    "Repeat with --organization-id VALUE, or make one active with "
                    f"`sk config set {ACTIVE_ORGANIZATION_KEY} VALUE`."
                ),
            )
            raise typer.Exit(EXIT_USAGE_ERROR)
    return identifier(value, "--organization-id", what="organizationId")


def _fail_api(error: ApiError, *, not_found: str = NOT_FOUND) -> NoReturn:
    fail_api_with_forbidden(
        error,
        not_found=not_found,
        conflict=CONFLICT_ON_CHANGE,
        by_error_code=ERROR_CODE_HINTS,
        forbidden=NO_PERMISSION_HINT,
    )


def _styled_phase(sa: ServiceAccount) -> Text:
    return Text(sa.phase, style=PHASE_STYLES.get(sa.phase, "yellow"))


def _rows(sa: ServiceAccount) -> list[tuple[str, str]]:
    keys_summary = f"{len(sa.keys)} key(s)"
    if sa.keys:
        active_count = sum(1 for k in sa.keys if k.status == "active")
        keys_summary = f"{len(sa.keys)} key(s) ({active_count} active)"
    return [
        ("resourceId", sa.resource_id),
        ("organizationId", sa.organization_id),
        ("name", sa.name),
        ("description", sa.description or "-"),
        ("phase", sa.phase),
        ("roles", ", ".join(sa.roles) or "-"),
        ("permissions", ", ".join(sa.permissions) or "-"),
        ("protected", "yes" if sa.deletion_protection else "no"),
        ("keys", keys_summary),
    ]


def _get_command(accepted: RequestAccepted, *, with_operation: bool = False) -> str:
    parts = ["sk ipm serviceaccount get", f"--resource-id {accepted.resource_id}"]
    if with_operation:
        parts.append(f"--operation-id {accepted.operation_id}")
    return " ".join(parts)


def _roles(values: list[str]) -> list[str]:
    try:
        return validate_roles(values)
    except ValueError as error:
        ui.error("Invalid role", str(error), hint="Use <module>.<roleName>.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error


def _key_specifications(desired_keys: Sequence[dict[str, str]]) -> list[dict[str, str]]:
    """Chaves do desired no formato do pedido: a API só aceita `publicKey` e `expiresAt`
    (o `fingerprint` existe apenas no estado desejado, calculado pelo servidor)."""
    return [{"publicKey": k["publicKey"], "expiresAt": k["expiresAt"]} for k in desired_keys]


def _fingerprint_from_private_pem(private_pem: str) -> str:
    """Calcula o fingerprint SHA-256 do DER SPKI a partir da chave privada PEM."""
    private_key = serialization.load_pem_private_key(private_pem.encode("utf-8"), password=None)
    if not isinstance(private_key, rsa.RSAPrivateKey):
        raise ValueError("not an RSA private key")
    spki_der = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return hashlib.sha256(spki_der).hexdigest()


_flow = ResourceFlow(
    subject="service account",
    get_command=_get_command,
    read_resource=get_serviceaccount,
    read_operation=get_operation,
    fail_api=_fail_api,
    rejection_hints=REJECTION_HINTS,
    rows=_rows,
)


@serviceaccount_app.command(
    "create",
    structured=True,
    help=command(
        "Create a service account with client-generated RSA key. Key private material stays local."
    ),
)
def create_command(
    name: Annotated[
        str | None,
        typer.Option(
            "--name",
            help=option(
                "Service account slug name (2-63 lowercase alphanumeric and hyphen).",
                kind="String",
                variable=None,
                file=None,
                default="none",
            ),
        ),
    ] = None,
    organization_id: OrganizationOption = None,
    description: Annotated[
        str | None,
        typer.Option(
            "--description",
            help=option(
                "Human description of what the service account is for.",
                kind="String",
                variable=None,
                file=None,
                default="no description",
            ),
        ),
    ] = None,
    role: RoleOption = None,
    key_file: Annotated[
        Path | None,
        typer.Option(
            "--key-file",
            help=option(
                "Path where the generated private key file will be stored (0600 exclusive).",
                kind="String",
                variable=None,
                file=None,
                default="sa-<name>.json",
            ),
        ),
    ] = None,
    public_key_file: Annotated[
        Path | None,
        typer.Option(
            "--public-key-file",
            help=option(
                "Path to an existing RSA public key in PEM format (BYO key).",
                kind="String",
                variable=None,
                file=None,
                default="none (generates local key)",
            ),
        ),
    ] = None,
    expires_in: Annotated[
        int,
        typer.Option(
            "--expires-in",
            min=1,
            max=365,
            help=option(
                "Validity of the key in days (at most 365).",
                kind="Integer",
                variable=None,
                file=None,
                default=str(DEFAULT_EXPIRES_IN_DAYS),
            ),
        ),
    ] = DEFAULT_EXPIRES_IN_DAYS,
    protected: Annotated[
        bool,
        typer.Option(
            "--protected/--unprotected",
            help=option(
                "Deletion protection. Service accounts are protected by default (0094).",
                kind="Boolean",
                variable=None,
                file=None,
                default="true",
            ),
        ),
    ] = True,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    raw_name = require(name, "--name")
    try:
        valid_name = validate_name(raw_name)
    except ValueError as error:
        ui.error("Value not accepted", str(error), hint="Fix the given name and repeat.")
        raise typer.Exit(EXIT_USAGE_ERROR) from error

    if key_file is not None and public_key_file is not None:
        usage_error("Give --key-file or --public-key-file (not both).", "--key-file")

    org_id = _organization(organization_id)
    roles = _roles(role) if role is not None else []
    target_key_file = key_file or Path(f"sa-{valid_name}.json") if public_key_file is None else None

    # Geração local ou leitura da pública
    if public_key_file is not None:
        try:
            public_pem, fingerprint, expires_at = parse_public_key_file(
                public_key_file, expires_in_days=expires_in
            )
        except (KeyFileError, ValueError) as error:
            ui.error("Invalid public key file", str(error), hint="Check the public key file.")
            raise typer.Exit(EXIT_USAGE_ERROR) from error
    elif target_key_file is not None:
        try:
            keypair = generate_key_pair(expires_in_days=expires_in)
            public_pem = keypair.public_pem
            fingerprint = keypair.fingerprint
            expires_at = keypair.expires_at
            write_key_file(target_key_file, private_pem=keypair.private_pem)
        except (KeyFileError, ValueError) as error:
            ui.error(
                "Key generation failed", str(error), hint="Check the destination key file path."
            )
            raise typer.Exit(EXIT_USAGE_ERROR) from error
    else:
        usage_error("Specify --key-file or --public-key-file.", "--key-file")

    url, insecure = load_api()
    token = session_token()
    try:
        accepted = create_serviceaccount(
            url,
            token=token,
            organization_id=org_id,
            name=valid_name,
            public_key=public_pem,
            expires_at=expires_at,
            description=description.strip() if description else None,
            roles=roles,
            deletion_protection=protected,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)

    extra_rows: list[tuple[str, str]] = [("name", valid_name), ("keyFingerprint", fingerprint[:16])]
    if target_key_file is not None:
        extra_rows.append(("keyFile", str(target_key_file)))

    _flow.accepted_panel("Creation requested", accepted, *extra_rows, wait=wait)

    if not wait and target_key_file is not None:
        with contextlib.suppress(KeyFileError):
            update_key_file(target_key_file, user_id=accepted.resource_id, key_id="")
        ui.note(
            f"Key file {target_key_file} created. When Ready, run:\n"
            f"  sk ipm serviceaccount key-file --resource-id {accepted.resource_id} "
            f"--key-file {target_key_file}"
        )
        return

    converged = _flow.finish(
        url,
        insecure,
        accepted,
        title="Service account created",
        removal=False,
        wait=wait,
        timeout=timeout,
    )
    if converged is not None and target_key_file is not None:
        matched_key = next((k for k in converged.keys if k.fingerprint == fingerprint), None)
        if matched_key and matched_key.key_id:
            try:
                update_key_file(
                    target_key_file, user_id=converged.resource_id, key_id=matched_key.key_id
                )
                ui.note(f"Key file {target_key_file} completed with keyId: {matched_key.key_id}")
            except KeyFileError as error:
                ui.warning(f"Could not complete key file {target_key_file}: {error}")


def _change(
    resource_id: str | None,
    *,
    description: str | None,
    roles: list[str] | None,
    protected: bool | None,
    keys: list[dict[str, str]] | None,
    title: str,
    wait: bool,
    timeout: int,
) -> None:
    sa_id = identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_serviceaccount(
            url, token=token, resource_id=sa_id, allow_insecure_http=insecure
        )
        same_desc = description is None or description.strip() == current.description
        same_roles = roles is None or sorted(roles) == sorted(current.roles)
        same_protection = protected is None or protected == current.deletion_protection
        same_keys = keys is None  # se keys for passado, atualiza
        if same_desc and same_roles and same_protection and same_keys:
            already_done(current, f"Service account {sa_id} already has it. Nothing to do.")
            return
        accepted = update_serviceaccount(
            url,
            token=token,
            resource_id=sa_id,
            resource_version=current.resource_version,
            description=None if same_desc else description,
            roles=None if same_roles else roles,
            deletion_protection=None if same_protection else protected,
            keys=keys,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _flow.accepted_panel("Update requested", accepted, ("name", current.name), wait=wait)
    _flow.finish(url, insecure, accepted, title=title, removal=False, wait=wait, timeout=timeout)


@serviceaccount_app.command(
    "update",
    structured=True,
    help=command("Update description or roles: --role replaces roles (--no-roles clears them)."),
)
def update_command(
    resource_id: ServiceAccountIdOption = None,
    description: Annotated[
        str | None,
        typer.Option(
            "--description",
            help=option(
                "New description of the service account.",
                kind="String",
                variable=None,
                file=None,
                default="no change",
            ),
        ),
    ] = None,
    role: RoleOption = None,
    no_roles: Annotated[
        bool,
        typer.Option(
            "--no-roles",
            help=option(
                "Remove every role of the service account.",
                kind="Boolean",
                variable=None,
                file=None,
                default="off",
            ),
        ),
    ] = False,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    has_role_change = role is not None or no_roles
    if has_role_change and (bool(role) == no_roles):
        usage_error("Give at least one --role, or --no-roles (not both).", "--role")
    if description is None and not has_role_change:
        usage_error("Give --description, at least one --role, or --no-roles.", "--description")
    roles_list = [] if no_roles else (_roles(role) if role is not None else None)
    _change(
        resource_id,
        description=description,
        roles=roles_list,
        protected=None,
        keys=None,
        title="Service account updated",
        wait=wait,
        timeout=timeout,
    )


@serviceaccount_app.command(
    "protect", structured=True, help=command("Protect a service account against deletion.")
)
def protect_command(
    resource_id: ServiceAccountIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    _change(
        resource_id,
        description=None,
        roles=None,
        protected=True,
        keys=None,
        title="Service account protected",
        wait=wait,
        timeout=timeout,
    )


@serviceaccount_app.command(
    "unprotect", structured=True, help=command("Allow a protected service account to be deleted.")
)
def unprotect_command(
    resource_id: ServiceAccountIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    _change(
        resource_id,
        description=None,
        roles=None,
        protected=False,
        keys=None,
        title="Service account unprotected",
        wait=wait,
        timeout=timeout,
    )


@serviceaccount_app.command(
    "delete", structured=True, help=command("Delete a service account of the Organization.")
)
def delete_command(
    resource_id: ServiceAccountIdOption = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    sa_id = identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        current = get_serviceaccount(
            url, token=token, resource_id=sa_id, allow_insecure_http=insecure
        )
        accepted = delete_serviceaccount(
            url,
            token=token,
            resource_id=sa_id,
            resource_version=current.resource_version,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    _flow.accepted_panel("Deletion requested", accepted, ("name", current.name), wait=wait)
    _flow.finish(
        url,
        insecure,
        accepted,
        title="Service account deleted",
        removal=True,
        wait=wait,
        timeout=timeout,
    )


@serviceaccount_app.command(
    "get",
    structured=True,
    help=command("Show the state of a service account and, if given, of an Operation."),
)
def get_command(
    resource_id: ServiceAccountIdOption = None,
    operation_id: Annotated[
        str | None,
        typer.Option(
            "--operation-id",
            help=option(
                "operationId of a request, to see why it was rejected or failed.",
                kind="String",
                variable=None,
                file=None,
                default="no Operation lookup",
            ),
        ),
    ] = None,
) -> None:
    sa_id = identifier(resource_id, "--resource-id", what="resourceId")
    if operation_id is not None:
        operation_id = identifier(operation_id, "--operation-id", what="operationId")
    url, insecure = load_api()
    token = session_token()
    operation: OperationStatus | None = None
    try:
        sa = get_serviceaccount(url, token=token, resource_id=sa_id, allow_insecure_http=insecure)
        if operation_id is not None:
            operation = get_operation(
                url,
                token=token,
                resource_id=sa_id,
                operation_id=operation_id,
                allow_insecure_http=insecure,
            )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    rows = _rows(sa)
    if operation is not None:
        rows.append(("operationStatus", operation.operation_status))
        if operation.reason is not None:
            rows.append(("reason", operation.reason))
    document = output.to_data(sa)
    if operation is not None:
        document["operation"] = output.to_data(operation)
    ui.panel("Service Account", rows, data=document)


@serviceaccount_app.command(
    "list", structured=True, help=command("List all service accounts of an Organization.")
)
def list_command(organization_id: OrganizationOption = None) -> None:
    org_id = _organization(organization_id)
    url, insecure = load_api()
    token = session_token()
    try:
        serviceaccounts = list_serviceaccounts(
            url, token=token, organization_id=org_id, allow_insecure_http=insecure
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    if not serviceaccounts:
        ui.empty("No service accounts.")
        return
    ui.table(
        "Service Accounts",
        ["name", "resourceId", "phase", "description"],
        [[s.name, s.resource_id, _styled_phase(s), s.description or "-"] for s in serviceaccounts],
        wrap=["description"],
        data=serviceaccounts,
    )


@serviceaccount_app.command(
    "key-file",
    structured=True,
    help=command(
        "Fill in keyId and userId in a locally generated key file using the observed state."
    ),
)
def key_file_command(
    resource_id: ServiceAccountIdOption = None,
    key_file: Annotated[
        Path | None,
        typer.Option(
            "--key-file",
            help=option(
                "Path to the key file to complete with keyId and userId.",
                kind="String",
                variable=None,
                file=None,
                default="key file path",
            ),
        ),
    ] = None,
) -> None:
    sa_id = identifier(resource_id, "--resource-id", what="resourceId")
    if key_file is None:
        usage_error("Specify --key-file.", "--key-file")
    file_path = key_file
    try:
        content = file_path.read_text(encoding="utf-8")
        raw = json.loads(content)
        if not isinstance(raw, dict) or "key" not in raw or not isinstance(raw["key"], str):
            raise ValueError("key file does not contain a private key")
        private_pem = raw["key"]
        fingerprint = _fingerprint_from_private_pem(private_pem)
    except Exception as error:
        ui.error(
            "Invalid key file", str(error), hint="Ensure the file is a valid service account key."
        )
        raise typer.Exit(EXIT_USAGE_ERROR) from error

    url, insecure = load_api()
    token = session_token()
    try:
        sa = get_serviceaccount(url, token=token, resource_id=sa_id, allow_insecure_http=insecure)
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)

    matched_key = next((k for k in sa.keys if k.fingerprint == fingerprint), None)
    if matched_key is None or not matched_key.key_id:
        ui.error(
            "Key not ready yet",
            f"No active key with fingerprint {fingerprint[:16]} found in service account {sa_id}.",
            hint="Wait for convergence (phase Ready) and try again.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)

    try:
        update_key_file(file_path, user_id=sa.resource_id, key_id=matched_key.key_id)
    except KeyFileError as error:
        ui.error("Could not update key file", str(error))
        raise typer.Exit(EXIT_USAGE_ERROR) from error

    ui.panel(
        "Key file completed",
        [
            ("resourceId", sa.resource_id),
            ("keyId", matched_key.key_id),
            ("fingerprint", matched_key.fingerprint[:16]),
            ("keyFile", str(file_path.resolve())),
        ],
    )


# -----------------------------------------------------------------------------
# Subcomandos de chaves: `sk ipm serviceaccount key ...`
# -----------------------------------------------------------------------------


@key_app.command("list", structured=True, help=command("List public keys of a service account."))
def key_list_command(resource_id: ServiceAccountIdOption = None) -> None:
    sa_id = identifier(resource_id, "--resource-id", what="resourceId")
    url, insecure = load_api()
    token = session_token()
    try:
        sa = get_serviceaccount(url, token=token, resource_id=sa_id, allow_insecure_http=insecure)
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)
    if not sa.keys:
        ui.empty("No keys registered.")
        return
    ui.table(
        "Service Account Keys",
        ["keyId", "fingerprint", "expiresAt", "status"],
        [[k.key_id or "-", k.fingerprint[:16], k.expires_at or "-", k.status] for k in sa.keys],
        data=sa.keys,
    )


@key_app.command(
    "add",
    structured=True,
    help=command("Add a public key to a service account (up to 3 keys, client-side rotation)."),
)
def key_add_command(
    resource_id: ServiceAccountIdOption = None,
    key_file: Annotated[
        Path | None,
        typer.Option(
            "--key-file",
            help=option(
                "Path where the generated private key file will be stored (0600 exclusive).",
                kind="String",
                variable=None,
                file=None,
                default="sa-<name>-<fingerprint>.json",
            ),
        ),
    ] = None,
    public_key_file: Annotated[
        Path | None,
        typer.Option(
            "--public-key-file",
            help=option(
                "Path to an existing RSA public key in PEM format (BYO key).",
                kind="String",
                variable=None,
                file=None,
                default="none (generates local key)",
            ),
        ),
    ] = None,
    expires_in: Annotated[
        int,
        typer.Option(
            "--expires-in",
            min=1,
            max=365,
            help=option(
                "Validity of the key in days (at most 365).",
                kind="Integer",
                variable=None,
                file=None,
                default=str(DEFAULT_EXPIRES_IN_DAYS),
            ),
        ),
    ] = DEFAULT_EXPIRES_IN_DAYS,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    sa_id = identifier(resource_id, "--resource-id", what="resourceId")
    if key_file is not None and public_key_file is not None:
        usage_error("Give --key-file or --public-key-file (not both).", "--key-file")

    url, insecure = load_api()
    token = session_token()
    try:
        current = get_serviceaccount(
            url, token=token, resource_id=sa_id, allow_insecure_http=insecure
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)

    if len(current.desired_keys) >= MAXIMUM_KEYS:
        ui.error(
            "Key limit reached",
            f"The service account already has the maximum of {MAXIMUM_KEYS} keys.",
            hint="Remove an expired or unused key with `sk ipm serviceaccount key remove` first.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)

    # Geração ou leitura da chave
    target_key_file: Path | None = None
    if public_key_file is not None:
        try:
            public_pem, fingerprint, expires_at = parse_public_key_file(
                public_key_file, expires_in_days=expires_in
            )
        except (KeyFileError, ValueError) as error:
            ui.error("Invalid public key file", str(error), hint="Check the public key file.")
            raise typer.Exit(EXIT_USAGE_ERROR) from error
    else:
        try:
            keypair = generate_key_pair(expires_in_days=expires_in)
            public_pem = keypair.public_pem
            fingerprint = keypair.fingerprint
            expires_at = keypair.expires_at
            default_path = Path(f"sa-{current.name}-{fingerprint[:8]}.json")
            target_key_file = key_file or default_path
            write_key_file(target_key_file, private_pem=keypair.private_pem)
        except (KeyFileError, ValueError) as error:
            ui.error(
                "Key generation failed", str(error), hint="Check the destination key file path."
            )
            raise typer.Exit(EXIT_USAGE_ERROR) from error

    new_key_entry = {"publicKey": public_pem, "expiresAt": expires_at}
    new_keys_list = [*_key_specifications(current.desired_keys), new_key_entry]

    try:
        accepted = update_serviceaccount(
            url,
            token=token,
            resource_id=sa_id,
            resource_version=current.resource_version,
            keys=new_keys_list,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)

    extra_rows: list[tuple[str, str]] = [("keyFingerprint", fingerprint[:16])]
    if target_key_file is not None:
        extra_rows.append(("keyFile", str(target_key_file)))

    _flow.accepted_panel("Key addition requested", accepted, *extra_rows, wait=wait)

    if not wait and target_key_file is not None:
        with contextlib.suppress(KeyFileError):
            update_key_file(target_key_file, user_id=current.resource_id, key_id="")
        ui.note(
            f"Key file {target_key_file} created. When Ready, run:\n"
            f"  sk ipm serviceaccount key-file --resource-id {current.resource_id} "
            f"--key-file {target_key_file}"
        )
        return

    converged = _flow.finish(
        url, insecure, accepted, title="Key added", removal=False, wait=wait, timeout=timeout
    )
    if converged is not None and target_key_file is not None:
        matched = next((k for k in converged.keys if k.fingerprint == fingerprint), None)
        if matched and matched.key_id:
            try:
                update_key_file(
                    target_key_file, user_id=converged.resource_id, key_id=matched.key_id
                )
                ui.note(f"Key file {target_key_file} completed with keyId: {matched.key_id}")
            except KeyFileError as error:
                ui.warning(f"Could not complete key file {target_key_file}: {error}")


@key_app.command(
    "remove",
    structured=True,
    help=command("Remove a public key from a service account by keyId or fingerprint."),
)
def key_remove_command(
    resource_id: ServiceAccountIdOption = None,
    key_id: Annotated[
        str | None,
        typer.Option(
            "--key-id",
            "-k",
            help=option(
                "keyId or fingerprint of the key to remove.",
                kind="String",
                variable=None,
                file=None,
                default="keyId or fingerprint",
            ),
        ),
    ] = None,
    wait: WaitOption = False,
    timeout: TimeoutOption = DEFAULT_WAIT_TIMEOUT_SECONDS,
) -> None:
    sa_id = identifier(resource_id, "--resource-id", what="resourceId")
    target_key = require(key_id, "--key-id")

    url, insecure = load_api()
    token = session_token()
    try:
        current = get_serviceaccount(
            url, token=token, resource_id=sa_id, allow_insecure_http=insecure
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)

    # Localiza a chave no observed (para pegar o fingerprint)
    fingerprint_to_remove: str | None = None
    for k in current.keys:
        if k.key_id == target_key or k.fingerprint.startswith(target_key):
            fingerprint_to_remove = k.fingerprint
            break

    # Se não achou no observed, busca pelo fingerprint no desired_keys
    if fingerprint_to_remove is None:
        for dk in current.desired_keys:
            fp = dk.get("fingerprint") or ""
            if fp.startswith(target_key):
                fingerprint_to_remove = fp
                break

    if fingerprint_to_remove is None:
        ui.error(
            "Key not found",
            f"No key with identifier {target_key} found in service account {sa_id}.",
            hint="Run `sk ipm serviceaccount key list` to see registered keys.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)

    if len(current.desired_keys) <= 1:
        ui.error(
            "Last key",
            "A service account must keep at least one key.",
            hint="Add another key with `sk ipm serviceaccount key add` before removing this one.",
        )
        raise typer.Exit(EXIT_USAGE_ERROR)

    remaining_keys = _key_specifications(
        [dk for dk in current.desired_keys if dk.get("fingerprint") != fingerprint_to_remove]
    )

    try:
        accepted = update_serviceaccount(
            url,
            token=token,
            resource_id=sa_id,
            resource_version=current.resource_version,
            keys=remaining_keys,
            idempotency_key=str(uuid.uuid7()),
            allow_insecure_http=insecure,
        )
    except OidcError as error:
        bad_address(error)
    except ApiError as error:
        _fail_api(error)

    _flow.accepted_panel(
        "Key removal requested",
        accepted,
        ("keyFingerprint", fingerprint_to_remove[:16]),
        wait=wait,
    )
    _flow.finish(
        url, insecure, accepted, title="Key removed", removal=False, wait=wait, timeout=timeout
    )
