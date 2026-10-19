"""Seções de configuração comuns aos papéis (decisão 0063).

Ordem: variável de ambiente → default. Não há arquivo de configuração: o componente roda em
contêiner, e os segredos entram por variável (ou arquivo montado), nunca no código. Cada papel
declara a sua classe `BaseSettings` com o prefixo `CORE_ACCOUNT_<PAPEL>_` e compõe as seções
abaixo; o nome da variável é `<PREFIXO><SEÇÃO>_<CAMPO>` (`docs/SCHEMA.md` §8.3).
"""

from collections.abc import Mapping

from pydantic import BaseModel, ConfigDict, SecretStr


class Section(BaseModel):
    """Seção de configuração: campo desconhecido é rejeitado."""

    model_config = ConfigDict(extra="forbid")


class NatsSettings(Section):
    url: str = "nats://broker.smarkee.internal:4222"
    user: str = "smarkee"
    password: SecretStr | None = None


class StateNatsSettings(NatsSettings):
    """NATS dos papéis com estado em memória e um consumer por instância (`NATS.md` §7.4)."""

    consumer_inactive_threshold_seconds: int = 300
    """Tempo sem uso após o qual o servidor remove o consumer da instância."""


class HealthSettings(Section):
    port: int = 8000
    """Porta das probes `/health/live`, `/health/ready` e `/health/startup` (decisão 0018)."""


class DatabaseSettings(Section):
    """Conexão com o SSOT. O papel de login (`user`) é de cada papel e não tem default aqui."""

    host: str = "database.smarkee.internal"
    port: int = 5432
    name: str = "smarkee"
    user: str
    password: SecretStr | None = None


def missing_variables(prefix: str, present: Mapping[str, bool]) -> list[str]:
    """Nomes completos das variáveis obrigatórias (sem default) que não foram informadas.

    `present` mapeia o sufixo da variável (por exemplo, `NATS_PASSWORD`) para "foi informada".
    """
    return [f"{prefix}{name}" for name, informed in present.items() if not informed]
