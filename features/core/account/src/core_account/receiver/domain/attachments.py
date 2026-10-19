"""Recursos de outros módulos atrelados à conta (regra de exclusão segura, decisão 0040).

Puro: descreve o que impede a exclusão e como dizer isso ao solicitante.
"""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Attachment:
    """Quantos recursos de um tipo ainda pertencem à conta."""

    singular: str
    plural: str
    count: int

    def describe(self) -> str:
        return f"{self.count} {self.singular if self.count == 1 else self.plural}"


class AttachmentCheckError(Exception):
    """Não foi possível saber o que está atrelado à conta. Nunca é tratado como "nada atrelado".

    `retryable` diz se tentar de novo pode resolver (módulo indisponível); sem ele, falta
    permissão para consultar o módulo (por exemplo, o serviço foi desligado e as roles saíram).
    """

    def __init__(self, module: str, *, retryable: bool) -> None:
        super().__init__(f"não foi possível consultar o módulo {module}")
        self.module = module
        self.retryable = retryable


def describe_all(attachments: list[Attachment]) -> str:
    return ", ".join(item.describe() for item in attachments)
