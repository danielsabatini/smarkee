"""CLI de recuperação e republicação do estado desired vigente no SSOT.

Varre as tabelas dos recursos no banco `ssot` e remonta as mensagens `desired`
no formato canônico. Pode enfileirar nas tabelas de outbox de cada feature
ou publicar diretamente no NATS JetStream com deduplicação determinística
via `Nats-Msg-Id`.

Segurança:
- Por padrão exibe apenas o plano e sai sem alterar dados.
- `--apply` executa a ação.
"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from smarkee_dev_republish.adapters import NatsBus, PostgresSsot
from smarkee_dev_republish.engine import build_plan, execute_plan, select_kinds

REPOSITORY = Path(__file__).resolve().parents[4]


def nats_password() -> str:
    """Recupera a senha do NATS de dev a partir do .env da infraestrutura."""
    password = os.environ.get("REPUBLISH_NATS_PASSWORD") or os.environ.get(
        "SMARKEE_MESSAGING_PASSWORD"
    )
    if password:
        return password
    env = REPOSITORY / "infrastructure" / "dev" / "messaging" / ".env"
    if env.is_file():
        for line in env.read_text(encoding="utf-8").splitlines():
            if line.startswith("SMARKEE_MESSAGING_PASSWORD="):
                return line.partition("=")[2].strip()
    return ""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="smarkee-dev-republish",
        description="Reconstrói e republica estados desired do SSOT para outbox ou NATS.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Executa a republicação (por padrão exibe apenas o plano sem alterar nada).",
    )
    parser.add_argument(
        "--target",
        choices=["outbox", "nats"],
        default="outbox",
        help="Destino da republicação: 'outbox' (padrão, enfileira nas tabelas de outbox) "
        "ou 'nats' (publica diretamente no JetStream com deduplicação determinística).",
    )
    parser.add_argument(
        "--module",
        type=str,
        default=None,
        help="Filtra por módulo específico (ex: ipm, core, bsm, sum).",
    )
    parser.add_argument(
        "--type",
        dest="resource_type",
        type=str,
        default=None,
        help="Filtra por tipo de recurso específico (ex: user, role, serviceaccount).",
    )
    parser.add_argument(
        "--resource-id",
        type=str,
        default=None,
        help="Filtra por ID de recurso específico.",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="Modo silencioso: exibe apenas o total de recursos afetados.",
    )
    return parser.parse_args(argv)


async def async_main(args: argparse.Namespace) -> int:
    ssot = PostgresSsot()
    kinds = select_kinds(module=args.module, resource_type=args.resource_type)
    if not kinds:
        print("Nenhum recurso encontrado para os filtros fornecidos.", file=sys.stderr)
        return 1

    try:
        plan = build_plan(ssot, kinds, resource_id=args.resource_id)
    except Exception as error:
        print(f"Erro ao consultar SSOT: {error}", file=sys.stderr)
        return 1

    total_records = sum(len(records) for records in plan.values())
    if not args.quiet:
        print("=== Plano de Republicação (DESIRED) ===")
        print(f"Destino selecionado: {args.target}")
        for kind, records in plan.items():
            print(f"- {kind.module}.{kind.resource_type}: {len(records)} recurso(s)")
        print(f"Total: {total_records} recurso(s)")

    if total_records == 0:
        if not args.quiet:
            print("Nada para republicar.")
        return 0

    if not args.apply:
        if not args.quiet:
            print("\nModo de visualização. Execute com --apply para efetivar a republicação.")
        return 0

    nats_bus: NatsBus | None = None
    if args.target == "nats":
        pwd = nats_password()
        nats_bus = NatsBus(password=pwd)
        try:
            await nats_bus.connect()
        except Exception as error:
            print(f"Erro ao conectar ao NATS: {error}", file=sys.stderr)
            return 1

    try:
        results = await execute_plan(plan, args.target, ssot, nats_bus=nats_bus)
        if not args.quiet:
            print("\n=== Resultado da Execução ===")
            for kind_name, count in results.items():
                print(f"- {kind_name}: {count} mensagem(ns) processada(s)")
    finally:
        if nats_bus:
            await nats_bus.close()

    return 0


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    code = asyncio.run(async_main(args))
    sys.exit(code)


if __name__ == "__main__":
    main()
