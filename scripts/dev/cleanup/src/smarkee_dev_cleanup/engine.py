"""Achar o resíduo de teste, removê-lo (loop primeiro, direto depois) e verificar o resultado."""

from collections.abc import Callable

from smarkee_dev_cleanup.model import (
    ORGANIZATIONS,
    POLL_SECONDS,
    REMOVAL_WAIT_SECONDS,
    SERVICES,
    TEST_ORGANIZATION_NAME,
    TEST_USER_EMAIL,
    USERS,
    UUID,
    Findings,
    Kind,
    Ports,
)


def is_test_organization(organization_id: str, name: str) -> bool:
    return bool(UUID.match(organization_id) and TEST_ORGANIZATION_NAME.match(name))


def is_test_user(email: str) -> bool:
    return bool(TEST_USER_EMAIL.match(email))


def find(ports: Ports) -> Findings:
    """O que é resíduo de teste agora, em todos os lugares."""
    findings = Findings()
    users = ports.identity.register_users()
    findings.zitadel_users = {rid: mail for rid, mail in users.items() if is_test_user(mail)}
    findings.zitadel_organizations = {
        rid: name
        for rid, name in ports.identity.organizations().items()
        if is_test_organization(rid, name)
    }
    findings.user_rows = [row for row in ports.ssot.rows(USERS) if is_test_user(row.label)]
    findings.organization_rows = [
        row for row in ports.ssot.rows(ORGANIZATIONS) if TEST_ORGANIZATION_NAME.match(row.label)
    ]
    # Ligação de serviço é de teste se o dono é de teste, ou se o dono nem existe mais no Zitadel
    # (sem usuário, a ligação não tem como convergir nem como ser desligada).
    test_owners = set(findings.zitadel_users) | {row.resource_id for row in findings.user_rows}
    findings.service_rows = [
        row
        for row in ports.ssot.rows(SERVICES)
        if row.label in test_owners or row.label not in users
    ]
    findings.mails = ports.mail.count()
    return findings


# ---------------------------------------------------------------- remover


async def remove_through_the_loop(
    ports: Ports, kind: Kind, resource_id: str, say: Callable[[str], None]
) -> bool:
    """Pede a remoção como a plataforma faz e espera o loop concluir. `False` se não deu."""
    current = await ports.bus.last_version(kind, resource_id)
    if current is None or current[0] != "Ready":
        return False  # sem `Ready` o loop não remove com segurança: segue o caminho direto
    await ports.bus.request_deletion(kind, resource_id, current[1])
    deadline = ports.clock() + REMOVAL_WAIT_SECONDS
    while ports.clock() < deadline:
        if await ports.bus.removed(kind, resource_id):
            say(f"  removido pelo loop: {kind.resource_type} {resource_id}")
            return True
        await ports.sleep(POLL_SECONDS)
    return False


async def apply(ports: Ports, findings: Findings, say: Callable[[str], None]) -> None:
    """Remove o resíduo: primeiro pelo loop, depois direto o que sobrou, e limpa a mensageria."""
    say("1. Pelo loop (organizações e usuários que ainda estão `Ready`)")
    for kind, rows in ((ORGANIZATIONS, findings.organization_rows), (USERS, findings.user_rows)):
        for row in rows:
            await remove_through_the_loop(ports, kind, row.resource_id, say)

    say("2. Direto, o que o loop não removeu")
    remaining = find(ports)
    for rid, name in remaining.zitadel_organizations.items():
        ports.identity.delete_organization(rid)
        say(f"  Zitadel: organização {name} ({rid})")
    for rid, mail in remaining.zitadel_users.items():
        ports.identity.delete_user(rid)
        say(f"  Zitadel: usuário {mail} ({rid})")
    for kind, rows in (
        (SERVICES, remaining.service_rows),
        (ORGANIZATIONS, remaining.organization_rows),
        (USERS, remaining.user_rows),
    ):
        if rows:
            ports.ssot.delete(kind, {row.resource_id for row in rows})
            say(f"  SSOT: {len(rows)} linha(s) de {kind.module}.{kind.resource_type}")

    say("3. Mensageria e e-mails")
    for kind, ids in findings.resource_ids().items():
        if ids:
            await ports.bus.purge(kind, ids)
            say(f"  NATS: mensagens de {len(ids)} recurso(s) de {kind.module}.{kind.resource_type}")
    if remaining.mails:
        ports.mail.delete()
        say(f"  Mailpit: {remaining.mails} mensagem(ns)")


async def clean(ports: Ports, *, apply_changes: bool, say: Callable[[str], None]) -> int:
    """Mostra o resíduo e, com `apply_changes`, remove. Código de saída: 0 limpo, 1 com resíduo."""
    findings = find(ports)
    if findings.is_clean():
        say("Ambiente limpo: nenhum resíduo de teste.")
        return 0
    say(f"Resíduo de teste encontrado ({len(findings.lines())}):")
    for line in findings.lines():
        say(f"  - {line}")
    if not apply_changes:
        say("Nada foi removido. Use --apply para remover.")
        return 1
    await apply(ports, findings, say)
    left = find(ports)
    if left.is_clean():
        say("Pronto: ambiente limpo.")
        return 0
    say("Ainda sobrou resíduo:")
    for line in left.lines():
        say(f"  - {line}")
    return 1
