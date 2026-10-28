"""Ponto de entrada da CLI smarkee-dev-retention."""

import argparse
import sys

from smarkee_dev_retention.adapters import RetentionDatabase, calculate_cutoff
from smarkee_dev_retention.engine import apply_retention, filter_targets, plan_retention
from smarkee_dev_retention.model import parse_duration


def build_parser() -> argparse.ArgumentParser:
    """Configura os argumentos da linha de comando."""
    parser = argparse.ArgumentParser(
        prog="smarkee-dev-retention",
        description="Expurgo de registros antigos de outbox e idempotency do SSOT.",
    )
    parser.add_argument(
        "--older-than",
        default="24h",
        help="Janela de retenção (ex: 24h, 7d, 30m, 0s). Padrão: 24h.",
    )
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Aplica o expurgo efetivo (sem esta flag, apenas simula em modo dry-run).",
    )
    parser.add_argument(
        "--module",
        help="Filtra por módulo específico (ex: core, bsm, sum, ipm).",
    )
    parser.add_argument(
        "--type",
        dest="resource_type",
        help="Filtra por tipo de recurso (ex: account, organization, permission).",
    )
    parser.add_argument(
        "--kind",
        dest="table_kind",
        choices=["outbox", "idempotency"],
        help="Filtra pelo tipo de tabela ('outbox' ou 'idempotency').",
    )
    return parser


def main() -> None:
    """Executa a rotina principal."""
    parser = build_parser()
    args = parser.parse_args()

    try:
        duration = parse_duration(args.older_than)
    except ValueError as e:
        sys.stderr.write(f"Erro: {e}\n")
        sys.exit(1)

    cutoff = calculate_cutoff(duration)
    targets = filter_targets(
        module=args.module,
        resource_type=args.resource_type,
        table_kind=args.table_kind,
    )

    if not targets:
        print("Nenhuma tabela encontrada para os critérios informados.")
        return

    db = RetentionDatabase.from_env()

    mode_label = "EXECUÇÃO EFETIVA (--apply)" if args.apply else "SIMULAÇÃO (dry-run)"
    print(f"--- SSOT Retention [{mode_label}] ---")
    print(f"Janela: registros anteriores a {args.older_than} (cutoff <= {cutoff.isoformat()})\n")

    if not args.apply:
        plan = plan_retention(db, targets, cutoff)
        total = sum(item.count for item in plan)
        for item in plan:
            status = f"{item.count} registro(s) para expurgar" if item.count > 0 else "0 (limpo)"
            print(f"  [{item.target.schema}.{item.target.table_name:<26}] : {status}")
        print(f"\nTotal elegível para expurgo: {total} registro(s).")
        print("Para aplicar a remoção, execute com a flag --apply.")
    else:
        results = apply_retention(db, targets, cutoff)
        total = sum(item.count for item in results)
        for item in results:
            table_desc = f"{item.target.schema}.{item.target.table_name:<26}"
            print(f"  [{table_desc}] : {item.count} registro(s) expurgado(s)")
        print(f"\nTotal expurgado: {total} registro(s).")


if __name__ == "__main__":
    main()
