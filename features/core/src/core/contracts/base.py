"""Classe base dos modelos gerados a partir de `schemas/`.

Concentra a conversão de grafia dos contratos (`docs/SCHEMA.md` §8.3): no Python, os atributos
são `snake_case` (`observed_generation`); no JSON, os contratos são camelCase
(`observedGeneration`), por meio de um alias gerado a partir do schema.

- entrada: só o nome do contrato (camelCase) é aceito; o nome Python (`observed_generation`) é
  rejeitado, como qualquer outra grafia diferente da do meio;
- saída: `model_dump()` e `model_dump_json()` já usam o nome do contrato, sem depender de
  `by_alias=True` em cada chamada;
- objetos fechados: propriedade desconhecida é rejeitada (modo estrito, `SCHEMA.md` §15).
"""

from pydantic import BaseModel, ConfigDict


class ContractModel(BaseModel):
    """Base de todo modelo de contrato."""

    model_config = ConfigDict(
        extra="forbid",
        validate_by_alias=True,
        validate_by_name=False,
        serialize_by_alias=True,
    )
