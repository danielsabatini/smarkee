"""Adaptador de banco de dados do SSOT usando papéis de manutenção dedicados."""

import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import psycopg
from psycopg import sql

from smarkee_dev_retention.model import TargetTable


class RetentionDatabase:
    """Executa contagens e expurgo nas tabelas do SSOT usando menor privilégio."""

    def __init__(
        self,
        host: str,
        port: int,
        dbname: str,
        passwords: Mapping[str, str] | None = None,
    ) -> None:
        self.host = host
        self.port = port
        self.dbname = dbname
        self.passwords = dict(passwords or {})

    @classmethod
    def from_env(cls) -> RetentionDatabase:
        """Instancia o adaptador a partir de variáveis de ambiente."""
        host = os.getenv("SMARKEE_DATABASE_HOST", "database.smarkee.internal")
        port = int(os.getenv("SMARKEE_DATABASE_PORT", "5432"))
        dbname = os.getenv("SMARKEE_DATABASE_NAME", "ssot")
        # Em dev, o padrão das senhas dos papéis de manutenção é igual ao próprio nome do papel
        passwords = {
            "core_maintenance_login": os.getenv(
                "SMARKEE_CORE_MAINTENANCE_PASSWORD", "core_maintenance_login"
            ),
            "bsm_maintenance_login": os.getenv(
                "SMARKEE_BSM_MAINTENANCE_PASSWORD", "bsm_maintenance_login"
            ),
            "sum_service_maintenance_login": os.getenv(
                "SMARKEE_SUM_SERVICE_MAINTENANCE_PASSWORD", "sum_service_maintenance_login"
            ),
            "ipm_maintenance_login": os.getenv(
                "SMARKEE_IPM_MAINTENANCE_PASSWORD", "ipm_maintenance_login"
            ),
        }
        return cls(host=host, port=port, dbname=dbname, passwords=passwords)

    def _get_connection(self, role: str) -> psycopg.Connection:
        password = self.passwords.get(role, role)
        return psycopg.connect(
            host=self.host,
            port=self.port,
            dbname=self.dbname,
            user=role,
            password=password,
            autocommit=True,
        )

    def count_expired(self, target: TargetTable, cutoff: datetime) -> int:
        """Conta quantas linhas estão elegíveis para expurgo na tabela."""
        with self._get_connection(target.maintenance_role) as conn, conn.cursor() as cur:
            if target.table_kind == "outbox":
                query = sql.SQL(
                    "SELECT count(*) FROM {}.{}"
                    " WHERE published_at IS NOT NULL AND published_at < %s"
                ).format(sql.Identifier(target.schema), sql.Identifier(target.table_name))
            else:
                query = sql.SQL("SELECT count(*) FROM {}.{} WHERE created_at < %s").format(
                    sql.Identifier(target.schema), sql.Identifier(target.table_name)
                )

            cur.execute(query, (cutoff,))
            row = cur.fetchone()
            return int(row[0]) if row else 0

    def purge_expired(self, target: TargetTable, cutoff: datetime) -> int:
        """Remove as linhas elegíveis e retorna a quantidade de linhas excluídas."""
        with self._get_connection(target.maintenance_role) as conn, conn.cursor() as cur:
            if target.table_kind == "outbox":
                query = sql.SQL(
                    "DELETE FROM {}.{} WHERE published_at IS NOT NULL AND published_at < %s"
                ).format(sql.Identifier(target.schema), sql.Identifier(target.table_name))
            else:
                query = sql.SQL("DELETE FROM {}.{} WHERE created_at < %s").format(
                    sql.Identifier(target.schema), sql.Identifier(target.table_name)
                )

            cur.execute(query, (cutoff,))
            return cur.rowcount if cur.rowcount >= 0 else 0


def calculate_cutoff(older_than: timedelta) -> datetime:
    """Calcula o timestamp limite (cutoff) no fuso UTC."""
    return datetime.now(UTC) - older_than
