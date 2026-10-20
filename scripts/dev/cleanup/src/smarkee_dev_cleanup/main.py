"""Limpeza segura dos dados de teste do ambiente de desenvolvimento.

Os testes (e2e, de integração e de jornada) criam usuários, Organizations e ligações de serviço
reais; quando um teste falha no meio, sobra resíduo no Zitadel, no SSOT, no NATS e no Mailpit.
Este comando acha **só** o que é de teste, pelo padrão do nome, e remove.

Segurança:
- só roda no ambiente de dev (recusa outro endereço de Zitadel, banco, NATS ou Mailpit);
- por padrão **não apaga nada**: mostra o plano e sai com 1 se houver resíduo (0 se estiver limpo);
  `--apply` remove, e sai com 1 se, depois de remover, ainda sobrar algo;
- nunca usa "tudo": cada alvo é identificado por um padrão de nome ou de e-mail de teste. A única
  exceção é `--orphans`, que você pede de forma explícita: inclui o histórico (outbox, Operations
  e resultados) e as mensagens dos Streams de TODO recurso que já não tem linha principal, tenha ou
  não rótulo de teste. Rode antes sem `--apply` para ver o que seria removido;
- usa o caminho nativo primeiro (pedido de remoção pelo loop) e só apaga direto o que o loop não
  removeu;
- a chave do `platform-bootstrap` é lida do volume da identidade, na memória, e nunca é impressa.
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path
from typing import cast

import nats

from smarkee_dev_cleanup.adapters import MailpitMail, NatsBus, PostgresSsot, ZitadelIdentity
from smarkee_dev_cleanup.engine import clean
from smarkee_dev_cleanup.model import Ports

REPOSITORY = Path(__file__).resolve().parents[5]


def read_key() -> dict[str, str]:
    """Chave do `platform-bootstrap`: do arquivo em `CLEANUP_ZITADEL_KEY_FILE`, ou do volume."""
    path = os.environ.get("CLEANUP_ZITADEL_KEY_FILE")
    if path:
        return cast("dict[str, str]", json.loads(Path(path).read_text(encoding="utf-8")))
    done = subprocess.run(
        [
            "docker",
            "run",
            "--rm",
            "-v",
            "identity-bootstrap:/b:ro",
            "postgres:18.6-alpine",
            "cat",
            "/b/service-account-platform-bootstrap.json",
        ],
        capture_output=True,
        check=True,
    )
    return cast("dict[str, str]", json.loads(done.stdout))


def nats_password() -> str:
    password = os.environ.get("CLEANUP_NATS_PASSWORD")
    if password:
        return password
    env = REPOSITORY / "infrastructure" / "dev" / "messaging" / ".env"
    for line in env.read_text(encoding="utf-8").splitlines():
        if line.startswith("SMARKEE_MESSAGING_PASSWORD="):
            return line.partition("=")[2].strip()
    raise SystemExit(
        "defina CLEANUP_NATS_PASSWORD ou o SMARKEE_MESSAGING_PASSWORD de infrastructure/dev/messaging/.env"
    )


def refuse_outside_development() -> None:
    """Só os endereços fixos de dev valem; qualquer outro, pedido por variável, é recusado."""
    for name in (
        "CLEANUP_ZITADEL_URL",
        "CLEANUP_DATABASE_HOST",
        "CLEANUP_NATS_URL",
        "CLEANUP_MAIL_URL",
    ):
        if os.environ.get(name):
            raise SystemExit(f"{name} não é aceita: este script só roda no ambiente de dev local")


async def run(
    *, apply_changes: bool, orphans: bool = False, say: Callable[[str], None] = print
) -> int:
    refuse_outside_development()
    client = await nats.connect(  # pyright: ignore[reportUnknownMemberType]
        servers=["nats://localhost:4222"], user="smarkee", password=nats_password(), name="cleanup"
    )
    try:
        ports = Ports(
            identity=ZitadelIdentity(read_key()),
            ssot=PostgresSsot(),
            bus=NatsBus(client.jetstream()),  # pyright: ignore[reportUnknownMemberType]
            mail=MailpitMail(),
        )
        return await clean(ports, apply_changes=apply_changes, say=say, orphans=orphans)
    finally:
        await client.drain()


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--apply", action="store_true", help="remove o resíduo (padrão: só mostra)")
    parser.add_argument(
        "--orphans",
        action="store_true",
        help=(
            "inclui o histórico e as mensagens de TODO recurso sem linha principal, de teste ou\n"
            "não (explícito: sem esta opção só o que é reconhecido como de teste)"
        ),
    )
    arguments = parser.parse_args()
    sys.exit(asyncio.run(run(apply_changes=arguments.apply, orphans=arguments.orphans)))


if __name__ == "__main__":
    main()
