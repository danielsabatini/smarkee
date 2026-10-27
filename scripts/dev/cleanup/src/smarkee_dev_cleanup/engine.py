"""Achar o resíduo de teste, removê-lo (loop primeiro, direto depois) e verificar o resultado."""

from collections.abc import Callable

from smarkee_dev_cleanup.model import (
    ACCOUNTS,
    BILLING_ACCOUNTS,
    GROUPS,
    ORGANIZATION_USERS,
    ORGANIZATIONS,
    PERMISSIONS,
    POLL_SECONDS,
    REMOVAL_WAIT_SECONDS,
    ROLES,
    SERVICEACCOUNTS,
    SERVICES,
    TEST_BILLING_ACCOUNT_NAME,
    TEST_GROUP_NAME,
    TEST_ORGANIZATION_NAME,
    TEST_PERMISSION_NAME,
    TEST_ROLE_NAME,
    TEST_SERVICEACCOUNT_NAME,
    TEST_USER_EMAIL,
    UNPROTECTION_WAIT_SECONDS,
    UUID,
    Findings,
    Kind,
    Ports,
    Row,
)


def is_test_organization(organization_id: str, name: str) -> bool:
    return bool(UUID.match(organization_id) and TEST_ORGANIZATION_NAME.match(name))


def is_test_user(email: str) -> bool:
    return bool(TEST_USER_EMAIL.match(email))


def find(ports: Ports, *, orphans: bool = False) -> Findings:
    """O que é resíduo de teste agora, em todos os lugares.

    Com `orphans`, o histórico de todo recurso removido (de teste ou não) também entra.
    """
    findings = Findings()
    users = ports.identity.register_users()
    findings.zitadel_users = {rid: mail for rid, mail in users.items() if is_test_user(mail)}
    findings.zitadel_organizations = {
        rid: name
        for rid, name in ports.identity.organizations().items()
        if is_test_organization(rid, name)
    }
    findings.account_rows = [row for row in ports.ssot.rows(ACCOUNTS) if is_test_user(row.label)]
    findings.billing_account_rows = [
        row
        for row in ports.ssot.rows(BILLING_ACCOUNTS)
        if TEST_BILLING_ACCOUNT_NAME.match(row.label)
    ]
    findings.organization_rows = [
        row for row in ports.ssot.rows(ORGANIZATIONS) if TEST_ORGANIZATION_NAME.match(row.label)
    ]
    # Usuário da Organization é de teste pelo e-mail, como a conta (o padrão dos testes).
    findings.organization_user_rows = [
        row for row in ports.ssot.rows(ORGANIZATION_USERS) if is_test_user(row.label)
    ]
    findings.role_rows = [row for row in ports.ssot.rows(ROLES) if TEST_ROLE_NAME.match(row.label)]
    findings.permission_rows = [
        row for row in ports.ssot.rows(PERMISSIONS) if TEST_PERMISSION_NAME.match(row.label)
    ]
    findings.group_rows = [
        row for row in ports.ssot.rows(GROUPS) if TEST_GROUP_NAME.match(row.label)
    ]
    findings.serviceaccount_rows = [
        row for row in ports.ssot.rows(SERVICEACCOUNTS) if TEST_SERVICEACCOUNT_NAME.match(row.label)
    ]
    # Ligação de serviço é de teste se o dono é de teste, ou se o dono nem existe mais no Zitadel
    # (sem usuário, a ligação não tem como convergir nem como ser desligada).
    test_owners = set(findings.zitadel_users) | {row.resource_id for row in findings.account_rows}
    findings.service_rows = [
        row
        for row in ports.ssot.rows(SERVICES)
        if row.label in test_owners or row.label not in users
    ]
    _find_history(ports, findings, test_owners, everything=orphans)
    findings.mails = ports.mail.count()
    return findings


def _find_history(
    ports: Ports, findings: Findings, test_owners: set[str], *, everything: bool
) -> None:
    """Histórico de recursos de teste que o loop já removeu (sem linha principal).

    O recurso removido sai da tabela principal e deixa o outbox, as Operations e os resultados.
    Só é de teste o que o rótulo gravado no outbox identifica como tal; o resto é mantido.
    """
    orphans: dict[Kind, list[Row]] = {}
    for kind in (
        ACCOUNTS,
        BILLING_ACCOUNTS,
        ORGANIZATIONS,
        SERVICES,
        ORGANIZATION_USERS,
        SERVICEACCOUNTS,
        ROLES,
        PERMISSIONS,
        GROUPS,
    ):
        live = {row.resource_id for row in ports.ssot.rows(kind)}
        orphans[kind] = [row for row in ports.ssot.history(kind) if row.resource_id not in live]
    test: dict[Kind, list[Row]] = {
        ACCOUNTS: [row for row in orphans[ACCOUNTS] if is_test_user(row.label)],
        BILLING_ACCOUNTS: [
            row for row in orphans[BILLING_ACCOUNTS] if TEST_BILLING_ACCOUNT_NAME.match(row.label)
        ],
        ORGANIZATIONS: [
            row for row in orphans[ORGANIZATIONS] if TEST_ORGANIZATION_NAME.match(row.label)
        ],
        ORGANIZATION_USERS: [row for row in orphans[ORGANIZATION_USERS] if is_test_user(row.label)],
        ROLES: [row for row in orphans[ROLES] if TEST_ROLE_NAME.match(row.label)],
        PERMISSIONS: [row for row in orphans[PERMISSIONS] if TEST_PERMISSION_NAME.match(row.label)],
        GROUPS: [row for row in orphans[GROUPS] if TEST_GROUP_NAME.match(row.label)],
        SERVICEACCOUNTS: [
            row for row in orphans[SERVICEACCOUNTS] if TEST_SERVICEACCOUNT_NAME.match(row.label)
        ],
    }
    # Uma ligação é de teste se o dono é uma conta de teste (viva ou já removida).
    owners = test_owners | {row.resource_id for row in test[ACCOUNTS]}
    test[SERVICES] = [row for row in orphans[SERVICES] if row.label in owners]
    if everything:  # `--orphans`: todo histórico de removido, reconhecido como de teste ou não
        test = {kind: list(rows) for kind, rows in orphans.items()}
    findings.history = {kind: rows for kind, rows in test.items() if rows}
    findings.kept_history = {kind: len(orphans[kind]) - len(test[kind]) for kind in orphans}


async def find_everywhere(ports: Ports, *, orphans: bool) -> Findings:
    """`find` e, no modo `--orphans`, as mensagens dos Streams de recursos sem linha principal."""
    findings = find(ports, orphans=orphans)
    if orphans:
        live = {
            kind: {row.resource_id for row in ports.ssot.rows(kind)}
            for kind in (
                ACCOUNTS,
                BILLING_ACCOUNTS,
                ORGANIZATIONS,
                SERVICES,
                ORGANIZATION_USERS,
                SERVICEACCOUNTS,
                ROLES,
                PERMISSIONS,
                GROUPS,
            )
        }
        found = await ports.bus.orphan_messages(live)
        findings.message_orphans = {kind: ids for kind, ids in found.items() if ids}
    return findings


# ---------------------------------------------------------------- remover


async def _wait_unprotected(ports: Ports, kind: Kind, resource_id: str) -> str | None:
    deadline = ports.clock() + UNPROTECTION_WAIT_SECONDS
    while ports.clock() < deadline:
        version = ports.ssot.unprotected_version(kind, resource_id)
        if version is not None:
            return version
        await ports.sleep(POLL_SECONDS)
    return None


async def remove_through_the_loop(
    ports: Ports, kind: Kind, resource_id: str, say: Callable[[str], None]
) -> bool:
    """Pede a remoção como a plataforma faz e espera o loop concluir. `False` se não deu."""
    if not kind.removable_through_requested:
        return False
    current = await ports.bus.last_version(kind, resource_id)
    if current is None or current[0] != "Ready":
        return False  # sem `Ready` o loop não remove com segurança: segue o caminho direto
    version = current[1]
    if kind.deletion_protected:
        # A proteção percorre o loop (decisão 0072): espera a geração confirmada, no SSOT.
        await ports.bus.request_unprotection(kind, resource_id, version)
        unprotected = await _wait_unprotected(ports, kind, resource_id)
        if unprotected is None:
            return False
        version = unprotected
    await ports.bus.request_deletion(kind, resource_id, version)
    deadline = ports.clock() + REMOVAL_WAIT_SECONDS
    while ports.clock() < deadline:
        if await ports.bus.removed(kind, resource_id):
            say(f"  removido pelo loop: {kind.resource_type} {resource_id}")
            return True
        await ports.sleep(POLL_SECONDS)
    return False


async def apply(
    ports: Ports, findings: Findings, say: Callable[[str], None], *, orphans: bool = False
) -> None:
    """Remove o resíduo: primeiro pelo loop, depois direto o que sobrou, e limpa a mensageria."""
    say("1. Pelo loop (organizações e usuários que ainda estão `Ready`)")
    # Os usuários da Organization antes dela: a Organization só é removida vazia (decisão 0077).
    for kind, rows in (
        (ORGANIZATION_USERS, findings.organization_user_rows),
        (SERVICEACCOUNTS, findings.serviceaccount_rows),
        (GROUPS, findings.group_rows),
        (ORGANIZATIONS, findings.organization_rows),
        (ROLES, findings.role_rows),
        (PERMISSIONS, findings.permission_rows),
        (BILLING_ACCOUNTS, findings.billing_account_rows),
        (ACCOUNTS, findings.account_rows),
    ):
        for row in rows:
            await remove_through_the_loop(ports, kind, row.resource_id, say)

    say("2. Direto, o que o loop não removeu")
    remaining = await find_everywhere(ports, orphans=orphans)
    for rid, name in remaining.zitadel_organizations.items():
        ports.identity.delete_organization(rid)
        say(f"  Zitadel: organização {name} ({rid})")
    for rid, mail in remaining.zitadel_users.items():
        ports.identity.delete_user(rid)
        say(f"  Zitadel: usuário {mail} ({rid})")
    for kind, rows in (
        (SERVICES, remaining.service_rows),
        (ORGANIZATION_USERS, remaining.organization_user_rows),
        (SERVICEACCOUNTS, remaining.serviceaccount_rows),
        (GROUPS, remaining.group_rows),
        (ORGANIZATIONS, remaining.organization_rows),
        (ROLES, remaining.role_rows),
        (PERMISSIONS, remaining.permission_rows),
        (BILLING_ACCOUNTS, remaining.billing_account_rows),
        (ACCOUNTS, remaining.account_rows),
    ):
        if rows:
            ports.ssot.delete(kind, {row.resource_id for row in rows})
            say(f"  SSOT: {len(rows)} linha(s) de {kind.module}.{kind.resource_type}")

    for kind in (
        SERVICES,
        ORGANIZATION_USERS,
        SERVICEACCOUNTS,
        GROUPS,
        ORGANIZATIONS,
        ROLES,
        PERMISSIONS,
        BILLING_ACCOUNTS,
        ACCOUNTS,
    ):
        ids = {row.resource_id for row in remaining.history.get(kind, [])}
        if ids:
            ports.ssot.delete(kind, ids)
            say(f"  SSOT: histórico de {len(ids)} recurso(s) removido(s) de {kind.table}")

    say("3. Mensageria e e-mails")
    affected: dict[Kind, set[str]] = {}
    for source in (findings, remaining):
        for kind, ids in source.resource_ids().items():
            affected.setdefault(kind, set()).update(ids)
    for kind, ids in affected.items():
        if ids:
            await ports.bus.purge(kind, ids)
            say(f"  NATS: mensagens de {len(ids)} recurso(s) de {kind.module}.{kind.resource_type}")
    if remaining.mails:
        ports.mail.delete()
        say(f"  Mailpit: {remaining.mails} mensagem(ns)")


async def clean(
    ports: Ports,
    *,
    apply_changes: bool,
    say: Callable[[str], None],
    orphans: bool = False,
) -> int:
    """Mostra o resíduo e, com `apply_changes`, remove. Código de saída: 0 limpo, 1 com resíduo."""
    if orphans:
        say("Modo --orphans: inclui o histórico de TODO recurso removido, de teste ou não.")
    findings = await find_everywhere(ports, orphans=orphans)
    if findings.is_clean():
        say("Ambiente limpo: nenhum resíduo de teste.")
        if note := findings.kept_history_note():
            say(note)
        return 0
    say(f"Resíduo de teste encontrado ({len(findings.lines())}):")
    for line in findings.lines():
        say(f"  - {line}")
    if not apply_changes:
        say("Nada foi removido. Use --apply para remover.")
        return 1
    await apply(ports, findings, say, orphans=orphans)
    left = await find_everywhere(ports, orphans=orphans)
    if left.is_clean():
        say("Pronto: ambiente limpo.")
        if note := left.kept_history_note():
            say(note)
        return 0
    say("Ainda sobrou resíduo:")
    for line in left.lines():
        say(f"  - {line}")
    return 1
