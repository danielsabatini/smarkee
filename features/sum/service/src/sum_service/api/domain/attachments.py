"""Recursos de outros módulos que dependem de um serviço habilitado (decisão 0040).

Puro: descreve o que impede o desligamento e como dizer isso ao solicitante.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Attachment:
    """Quantos recursos de um tipo ainda pertencem ao dono."""

    singular: str
    plural: str
    count: int

    def describe(self) -> str:
        return f"{self.count} {self.singular if self.count == 1 else self.plural}"


def describe_all(attachments: list[Attachment]) -> str:
    return ", ".join(item.describe() for item in attachments)
