"""Classe base dos modelos gerados a partir de `schemas/`.

Concentra a conversão de grafia dos contratos (`docs/SCHEMA.md` §8.3): no Python, os atributos
são `snake_case` (`observed_generation`); no JSON, os contratos são camelCase
(`observedGeneration`), por meio de um alias gerado a partir do schema.

- entrada: só o nome do contrato (camelCase) é aceito; o nome Python (`observed_generation`) é
  rejeitado, como qualquer outra grafia diferente da do meio;
- saída: `model_dump()` e `model_dump_json()` já usam o nome do contrato, sem depender de
  `by_alias=True` em cada chamada;
- objetos fechados: propriedade desconhecida é rejeitada (modo estrito, `SCHEMA.md` §15), na entrada
  de clientes externos e na publicação; o consumo de mensagens internas usa `validate_tolerant`.
"""

from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError


class ContractModel(BaseModel):
    """Base de todo modelo de contrato."""

    model_config = ConfigDict(
        extra="forbid",
        validate_by_alias=True,
        validate_by_name=False,
        serialize_by_alias=True,
    )


SUPPORTED_MAJOR = 1
"""`MAJOR` do contrato que este componente entende (`docs/SCHEMA.md` §13)."""


def validate_tolerant[M: BaseModel](model: type[M], data: Any) -> M:
    """Valida uma mensagem **consumida** em modo tolerante (`docs/SCHEMA.md` §15).

    Propriedades desconhecidas são ignoradas (um produtor de `MINOR` mais novo pode acrescentar
    campos opcionais), e todo campo conhecido continua validado. O consumidor nunca age sobre um
    campo que desconhece. A **entrada de clientes externos** e a **publicação** continuam estritas:
    usam `model_validate` sem esta função.
    """
    return model.model_validate(data, extra="ignore")


def supports_major(schema_version: str) -> bool:
    """Verdadeiro se o `MAJOR` de `schemaVersion` (`MAJOR.MINOR`) é o suportado."""
    return schema_version.split(".", 1)[0] == str(SUPPORTED_MAJOR)


def fields_of(error: ValidationError) -> str:
    """Nomes dos campos inválidos, sem os valores (que podem ser `confidential`)."""
    return ", ".join(".".join(str(part) for part in item["loc"]) for item in error.errors())
