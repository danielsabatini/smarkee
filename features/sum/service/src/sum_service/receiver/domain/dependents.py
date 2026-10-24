"""Recursos de outros módulos que dependem de um serviço habilitado (decisão 0040).

Desabilitar um serviço tira as permissões dele; antes, é preciso que nada do dono dependa dele.
"""


class DependentsCheckError(Exception):
    """Não foi possível saber o que depende do serviço. Nunca é tratado como "nada depende".

    `retryable` diz se tentar de novo pode resolver (módulo indisponível); sem ele, falta permissão
    para consultar o módulo.
    """

    def __init__(self, service: str, *, retryable: bool) -> None:
        super().__init__(f"não foi possível consultar o que depende do serviço {service}")
        self.service = service
        self.retryable = retryable
