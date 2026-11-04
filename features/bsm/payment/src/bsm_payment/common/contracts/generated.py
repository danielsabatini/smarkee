# Gerado por datamodel-codegen a partir de schemas/ (decisão 0012). Não editar: altere o schema e regere.

from enum import StrEnum
from typing import Annotated, Any
from pydantic import AwareDatetime, ConfigDict, Field, RootModel
from datetime import timedelta
from bsm_payment.common.contracts.base import ContractModel


class MessageType(StrEnum):
    """
    Tipo semântico da mensagem.
    """

    desired = "desired"
    updated = "updated"


class MessageEmitter(StrEnum):
    """
    Emissor lógico (identidade funcional, não a instância).
    """

    api = "api"
    controller = "controller"


class MessageOperation(StrEnum):
    """
    Operação ou resultado semântico associado. desired, observed e updated usam changed.
    """

    create = "create"
    update = "update"
    delete = "delete"
    changed = "changed"
    reconcile = "reconcile"
    noop = "noop"


class RequestDigest(RootModel[str]):
    root: Annotated[str, Field(max_length=64, min_length=64, pattern="^[0-9a-f]{64}$")]
    """
    SHA-256, em hexadecimal minúsculo, da forma canônica do conteúdo pedido.
    """


class Duration(RootModel[timedelta]):
    root: timedelta
    """
    Duração ISO 8601, por exemplo PT5M.
    """


class Lifecycle(StrEnum):
    """
    Intenção de existência, em desired.
    """

    present = "present"
    absent = "absent"


class Reconciliation(StrEnum):
    """
    Controle da reconciliação, em desired. Quando suspended, o Reconciler não decide.
    """

    active = "active"
    suspended = "suspended"


class Presence(StrEnum):
    """
    Resultado da observação, no envelope de observed. unknown nunca é tratado como absent.
    """

    present = "present"
    absent = "absent"
    unknown = "unknown"


class Phase(StrEnum):
    """
    Fase consolidada do recurso (RESOURCE-CONTROL-LOOP.md, Lifecycle).
    """

    pending = "Pending"
    reconciling = "Reconciling"
    ready = "Ready"
    failed = "Failed"
    deleting = "Deleting"


class PlatformAccess(StrEnum):
    """
    Intenção de acesso à plataforma: granted mantém a autorização no projeto da plataforma (Project Grant da Organization; conjunto de permissões de ação do usuário cadastrado, na Account); revoked a remove.
    """

    granted = "granted"
    revoked = "revoked"


class ConditionStatus(StrEnum):
    true = "True"
    false = "False"
    unknown = "Unknown"


class Condition(ContractModel):
    """
    Fato consolidado do recurso (RESOURCE-CONTROL-LOOP.md, Conditions). Mantida pelo Manager.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    type: Annotated[str, Field(max_length=128, min_length=1, pattern="^[A-Z][A-Za-z0-9]*$")]
    """
    Tipo da condition, por exemplo Ready, ObservationStale, DriftLoop.
    """
    status: Annotated[ConditionStatus, Field(title="ConditionStatus")]
    reason: Annotated[str, Field(max_length=128, min_length=1, pattern="^[A-Z][A-Za-z0-9]*$")]
    """
    Código legível por máquina em PascalCase (tipo e motivo de condition, motivo de falha).
    """
    message: Annotated[str | None, Field(max_length=4096)] = None
    """
    Texto descritivo para pessoas. Nunca contém valores confidential ou secretReference.
    """
    observed_generation: Annotated[
        int | None, Field(alias="observedGeneration", ge=1, le=9007199254740991)
    ] = None
    """
    Geração lógica do estado desejado (desiredGeneration, observedGeneration).
    """
    last_transition_at: Annotated[AwareDatetime, Field(alias="lastTransitionAt")]
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """


class ActionData(ContractModel):
    """
    data de uma action: o motivo da decisão de reconciliação. A operação está no envelope (create, update, delete).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    reason: Annotated[str, Field(max_length=128, min_length=1, pattern="^[A-Z][A-Za-z0-9]*$")]
    """
    Motivo da decisão, por exemplo Missing, Drift, DeletionRequested.
    """
    message: Annotated[str | None, Field(max_length=4096)] = None
    """
    Texto descritivo para pessoas. Nunca contém valores confidential ou secretReference.
    """


class CompletedData(ContractModel):
    """
    data de completed: a operação foi aplicada no sistema externo. Não significa convergência (RESOURCE-CONTROL-LOOP.md).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    external_reference: Annotated[
        str | None, Field(alias="externalReference", max_length=256, min_length=1)
    ] = None
    """
    Referência do recurso no sistema externo, quando diferente do resourceId.
    """


class FailedData(ContractModel):
    """
    data de failed: a operação não foi aplicada, com a causa da falha.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    reason: Annotated[str, Field(max_length=128, min_length=1, pattern="^[A-Z][A-Za-z0-9]*$")]
    """
    Motivo da falha, por exemplo ProviderUnavailable, Rejected, StaleAction.
    """
    message: Annotated[str | None, Field(max_length=4096)] = None
    """
    Texto descritivo para pessoas. Nunca contém valores confidential ou secretReference.
    """
    retryable: bool
    """
    Se a mesma decisão pode ser tentada de novo. false é falha permanente para o actionId.
    """


class UpdatedData(ContractModel):
    """
    data de updated: resumo do estado consolidado no SSOT depois de uma alteração.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    phase: Phase
    lifecycle: Lifecycle
    resource_version: Annotated[
        str, Field(alias="resourceVersion", max_length=64, min_length=1, pattern="^[A-Za-z0-9-]+$")
    ]
    """
    Versão persistida do recurso, para concorrência otimista. Valor opaco: não é sequência, instante nem geração.
    """
    desired_generation: Annotated[
        int | None, Field(alias="desiredGeneration", ge=1, le=9007199254740991)
    ] = None
    """
    Geração do desired vigente no SSOT quando o updated foi gravado.
    """
    observed_generation: Annotated[
        int | None, Field(alias="observedGeneration", ge=1, le=9007199254740991)
    ] = None
    """
    Última geração cuja convergência o Manager confirmou com uma observação feita depois dela (semântica do status.observedGeneration do Kubernetes). Nunca maior que desiredGeneration; igual a ela, com phase Ready, a última alteração terminou. Ausente enquanto nenhuma geração foi confirmada.
    """
    removed: bool | None = None
    """
    true quando o recurso foi removido do SSOT (remoção convergida).
    """


class OperationType(StrEnum):
    create = "create"
    update = "update"
    delete = "delete"


class OperationStatus(StrEnum):
    accepted = "accepted"
    in_progress = "in_progress"
    completed = "completed"
    failed = "failed"
    rejected = "rejected"
    superseded = "superseded"


class OperationStatusReason(StrEnum):
    """
    Motivo da rejeição; presente somente quando operationStatus é rejected. protected: o recurso tem a proteção contra exclusão ligada (decisão 0043).
    """

    conflict = "conflict"
    validation = "validation"
    not_found = "not_found"
    protected = "protected"


class Operation(ContractModel):
    """
    Acompanhamento de uma solicitação assíncrona, exposto por GET /v1/operations/{operationId} (SSOT.md, Operation).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    operation_id: Annotated[
        str,
        Field(
            alias="operationId",
            max_length=128,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$",
        ),
    ]
    """
    Identificador opaco atribuído pelo sistema (messageId, operationId, correlationId, causationId). O UUIDv7 em minúsculas atende ao padrão.
    """
    operation_type: Annotated[OperationType, Field(alias="operationType", title="OperationType")]
    module: Annotated[str, Field(max_length=63, min_length=1, pattern="^[a-z][a-z0-9-]*$")]
    resource_type: Annotated[
        str, Field(alias="resourceType", max_length=63, min_length=1, pattern="^[a-z][a-z0-9-]*$")
    ]
    resource_id: Annotated[
        str,
        Field(
            alias="resourceId",
            max_length=128,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$",
        ),
    ]
    """
    Identidade estável e opaca do recurso (SCHEMA.md, Identificador do recurso).
    """
    desired_generation: Annotated[
        int | None, Field(alias="desiredGeneration", ge=1, le=9007199254740991)
    ] = None
    """
    Geração produzida pelo pedido; ausente quando rejeitado.
    """
    operation_status: Annotated[
        OperationStatus, Field(alias="operationStatus", title="OperationStatus")
    ]
    operation_status_reason: Annotated[
        OperationStatusReason | None,
        Field(alias="operationStatusReason", title="OperationStatusReason"),
    ] = None
    """
    Motivo da rejeição; presente somente quando operationStatus é rejected. protected: o recurso tem a proteção contra exclusão ligada (decisão 0043).
    """
    created_at: Annotated[AwareDatetime, Field(alias="createdAt")]
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    updated_at: Annotated[AwareDatetime, Field(alias="updatedAt")]
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    completed_at: Annotated[AwareDatetime | None, Field(alias="completedAt")] = None
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """


class ApiAcceptedResponse(ContractModel):
    """
    Resposta das escritas assíncronas (POST, PATCH, DELETE): o pedido foi publicado, não aplicado (RESOURCE-CONTROL-LOOP.md, Interface HTTP).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    resource_id: Annotated[
        str,
        Field(
            alias="resourceId",
            max_length=128,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$",
        ),
    ]
    """
    Identidade estável e opaca do recurso (SCHEMA.md, Identificador do recurso).
    """
    operation_id: Annotated[
        str,
        Field(
            alias="operationId",
            max_length=128,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$",
        ),
    ]
    """
    Identificador opaco atribuído pelo sistema (messageId, operationId, correlationId, causationId). O UUIDv7 em minúsculas atende ao padrão.
    """


class ApiError(ContractModel):
    """
    Corpo das respostas de erro do Receiver. A mensagem identifica o campo e a regra violada e não repete valores confidential nem secretReference (SCHEMA.md, Limites e erros).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    error_code: Annotated[
        str, Field(alias="errorCode", max_length=128, min_length=1, pattern="^[A-Z][A-Za-z0-9]*$")
    ]
    """
    Código estável do erro, por exemplo ValidationFailed, Conflict, IdempotencyKeyReused.
    """
    message: Annotated[str, Field(max_length=4096)]
    """
    Texto descritivo para pessoas. Nunca contém valores confidential ou secretReference.
    """
    field: Annotated[str | None, Field(max_length=256, min_length=1)] = None
    """
    Caminho do campo inválido no corpo do pedido, quando aplicável (por exemplo, specification.name).
    """


class PaymentProvider(StrEnum):
    """
    Gateway de pagamento responsável por custodiar e processar este método.
    """

    mercadopago = "mercadopago"


class PaymentMethodType(StrEnum):
    """
    Modalidade do meio de pagamento registrado no provedor.
    """

    credit_card = "credit_card"
    debit_card = "debit_card"
    pix = "pix"
    boleto = "boleto"


class PaymentMethodStatus(StrEnum):
    """
    Estado do método de pagamento reportado pelo gateway externo.
    """

    active = "active"
    inactive = "inactive"
    invalid = "invalid"


class PaymentObservedData(ContractModel):
    """
    data de observed do método de pagamento (bsm.payment): metadados não sensíveis lidos do gateway de pagamento. Os campos estão presentes quando presence é present; com absent ou unknown, data é vazio.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    customer_account_id: Annotated[
        str | None,
        Field(
            alias="customerAccountId", max_length=256, min_length=1, pattern="^[A-Za-z0-9._:@-]+$"
        ),
    ] = None
    """
    Identificador da Customer Account (cam.account) titular deste método de pagamento.
    """
    display_name: Annotated[
        str | None,
        Field(alias="displayName", max_length=120, min_length=1, pattern="^[^\\r\\n\\t]+$"),
    ] = None
    """
    Nome de exibição amigável do método de pagamento (por exemplo, Visa Corporativo Final 4242).
    """
    provider: PaymentProvider | None = None
    method_type: Annotated[PaymentMethodType | None, Field(alias="methodType")] = None
    status: PaymentMethodStatus | None = None
    provider_customer_id: Annotated[
        str | None,
        Field(
            alias="providerCustomerId", max_length=128, min_length=1, pattern="^[A-Za-z0-9._-]+$"
        ),
    ] = None
    """
    Identificador do cliente (Customer) no cofre do gateway de pagamento.
    """
    provider_payment_method_id: Annotated[
        str | None,
        Field(
            alias="providerPaymentMethodId",
            max_length=128,
            min_length=1,
            pattern="^[A-Za-z0-9._-]+$",
        ),
    ] = None
    """
    Identificador permanente do método de pagamento (Card/Instrument) no cofre do gateway de pagamento.
    """
    brand: Annotated[str | None, Field(max_length=32, min_length=1, pattern="^[a-z0-9_-]+$")] = None
    """
    Bandeira ou identificador da rede do meio de pagamento (por exemplo, visa, master, pix).
    """
    last_four_digits: Annotated[
        str | None, Field(alias="lastFourDigits", max_length=4, min_length=4, pattern="^[0-9]{4}$")
    ] = None
    """
    Últimos quatro dígitos do cartão (mascarado; não constitui dado sensível PAN).
    """
    expiration_month: Annotated[int | None, Field(alias="expirationMonth", ge=1, le=12)] = None
    """
    Mês de vencimento do cartão (1 a 12).
    """
    expiration_year: Annotated[int | None, Field(alias="expirationYear", ge=2024, le=2100)] = None
    """
    Ano de vencimento do cartão com quatro dígitos.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão confirmada pelo Controller (decisão 0074).
    """


class PaymentCreateRequest(ContractModel):
    """
    Corpo de POST /v1/bsm/payments. A API valida que customerAccountId pertence ao solicitante autenticado (salvo operador) e atribui resourceId, ownerAccountId = customerAccountId e deletionProtection = true.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    customer_account_id: Annotated[
        str,
        Field(
            alias="customerAccountId", max_length=256, min_length=1, pattern="^[A-Za-z0-9._:@-]+$"
        ),
    ]
    """
    Identificador da Customer Account (cam.account) titular deste método de pagamento.
    """
    display_name: Annotated[
        str, Field(alias="displayName", max_length=120, min_length=1, pattern="^[^\\r\\n\\t]+$")
    ]
    """
    Nome de exibição amigável do método de pagamento (por exemplo, Visa Corporativo Final 4242).
    """
    provider: PaymentProvider
    method_type: Annotated[PaymentMethodType, Field(alias="methodType")]
    provider_token: Annotated[
        str, Field(alias="providerToken", max_length=256, min_length=4, pattern="^[A-Za-z0-9._-]+$")
    ]
    """
    Token de uso único ou referência tokenizada emitida pelo gateway de pagamento (por exemplo, card_token_id do Mercado Pago). Nunca contém PAN ou CVV.
    """


class PaymentUpdateRequest(ContractModel):
    """
    Corpo de PATCH /v1/bsm/payments/{resourceId}. resourceVersion é a versão lida; pelo menos um campo deve ser alterado. provider, methodType e providerToken são imutáveis.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    resource_version: Annotated[
        str, Field(alias="resourceVersion", max_length=64, min_length=1, pattern="^[A-Za-z0-9-]+$")
    ]
    """
    Versão persistida do recurso, para concorrência otimista. Valor opaco: não é sequência, instante nem geração.
    """
    display_name: Annotated[
        str | None,
        Field(alias="displayName", max_length=120, min_length=1, pattern="^[^\\r\\n\\t]+$"),
    ] = None
    """
    Nome de exibição amigável do método de pagamento (por exemplo, Visa Corporativo Final 4242).
    """
    reconciliation: Reconciliation | None = None
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """


class PaymentDesiredView(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    lifecycle: Lifecycle
    reconciliation: Reconciliation
    customer_account_id: Annotated[
        str,
        Field(
            alias="customerAccountId", max_length=256, min_length=1, pattern="^[A-Za-z0-9._:@-]+$"
        ),
    ]
    """
    Identificador da Customer Account (cam.account) titular deste método de pagamento.
    """
    display_name: Annotated[
        str, Field(alias="displayName", max_length=120, min_length=1, pattern="^[^\\r\\n\\t]+$")
    ]
    """
    Nome de exibição amigável do método de pagamento (por exemplo, Visa Corporativo Final 4242).
    """
    provider: PaymentProvider
    method_type: Annotated[PaymentMethodType, Field(alias="methodType")]
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """


class PaymentObservedView(ContractModel):
    """
    Última observação; ausente antes da primeira.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    presence: Presence
    observed_at: Annotated[AwareDatetime, Field(alias="observedAt")]
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    customer_account_id: Annotated[
        str | None,
        Field(
            alias="customerAccountId", max_length=256, min_length=1, pattern="^[A-Za-z0-9._:@-]+$"
        ),
    ] = None
    """
    Identificador da Customer Account (cam.account) titular deste método de pagamento.
    """
    display_name: Annotated[
        str | None,
        Field(alias="displayName", max_length=120, min_length=1, pattern="^[^\\r\\n\\t]+$"),
    ] = None
    """
    Nome de exibição amigável do método de pagamento (por exemplo, Visa Corporativo Final 4242).
    """
    provider: PaymentProvider | None = None
    method_type: Annotated[PaymentMethodType | None, Field(alias="methodType")] = None
    status: PaymentMethodStatus | None = None
    provider_customer_id: Annotated[
        str | None,
        Field(
            alias="providerCustomerId", max_length=128, min_length=1, pattern="^[A-Za-z0-9._-]+$"
        ),
    ] = None
    """
    Identificador do cliente (Customer) no cofre do gateway de pagamento.
    """
    provider_payment_method_id: Annotated[
        str | None,
        Field(
            alias="providerPaymentMethodId",
            max_length=128,
            min_length=1,
            pattern="^[A-Za-z0-9._-]+$",
        ),
    ] = None
    """
    Identificador permanente do método de pagamento (Card/Instrument) no cofre do gateway de pagamento.
    """
    brand: Annotated[str | None, Field(max_length=32, min_length=1, pattern="^[a-z0-9_-]+$")] = None
    """
    Bandeira ou identificador da rede do meio de pagamento (por exemplo, visa, master, pix).
    """
    last_four_digits: Annotated[
        str | None, Field(alias="lastFourDigits", max_length=4, min_length=4, pattern="^[0-9]{4}$")
    ] = None
    """
    Últimos quatro dígitos do cartão (mascarado; não constitui dado sensível PAN).
    """
    expiration_month: Annotated[int | None, Field(alias="expirationMonth", ge=1, le=12)] = None
    """
    Mês de vencimento do cartão (1 a 12).
    """
    expiration_year: Annotated[int | None, Field(alias="expirationYear", ge=2024, le=2100)] = None
    """
    Ano de vencimento do cartão com quatro dígitos.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """


class Payment(ContractModel):
    """
    Visão consolidada do método de pagamento (bsm.payment) exposta pela API (GET/POST/PATCH/DELETE). Não expõe o dono (ownerAccountId), o token bruto (providerToken) nem campos internos do SSOT (failureCount, requestedBy).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    resource_id: Annotated[
        str,
        Field(
            alias="resourceId",
            max_length=128,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$",
        ),
    ]
    """
    Identificador do método de pagamento (bsm.payment).
    """
    resource_version: Annotated[
        str, Field(alias="resourceVersion", max_length=64, min_length=1, pattern="^[A-Za-z0-9-]+$")
    ]
    """
    Versão persistida do recurso, para concorrência otimista. Valor opaco: não é sequência, instante nem geração.
    """
    desired_generation: Annotated[int, Field(alias="desiredGeneration", ge=1, le=9007199254740991)]
    """
    Geração lógica do estado desejado (desiredGeneration, observedGeneration).
    """
    observed_generation: Annotated[
        int | None, Field(alias="observedGeneration", ge=1, le=9007199254740991)
    ] = None
    """
    Última geração do desired confirmada pela observação; ausente antes da primeira. A alteração terminou quando observedGeneration >= desiredGeneration e a phase é Ready ou Failed (decisão 0098).
    """
    phase: Phase
    conditions: Annotated[list[Condition], Field(max_length=32)]
    desired: Annotated[PaymentDesiredView, Field(title="PaymentDesiredView")]
    observed: Annotated[PaymentObservedView | None, Field(title="PaymentObservedView")] = None
    """
    Última observação; ausente antes da primeira.
    """
    created_at: Annotated[AwareDatetime, Field(alias="createdAt")]
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    updated_at: Annotated[AwareDatetime, Field(alias="updatedAt")]
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """


class PaymentList(ContractModel):
    """
    Resposta de GET /v1/bsm/payments: página ordenada por resourceId, somente dos métodos de pagamento autorizados. nextCursor ausente indica a última página.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    items: Annotated[list[Payment], Field(max_length=200)]
    next_cursor: Annotated[
        str | None,
        Field(alias="nextCursor", max_length=512, min_length=1, pattern="^[A-Za-z0-9_-]+$"),
    ] = None
    """
    Cursor opaco da próxima página.
    """


class MessageEnvelope(ContractModel):
    """
    Metadados de transporte e rastreamento de toda mensagem (MESSAGING.md, Campos do envelope). O conteúdo de data é validado pelo contrato do messageType e do tipo de recurso. O tamanho de data é limitado a 256 KiB.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    message_id: Annotated[
        str,
        Field(
            alias="messageId",
            max_length=128,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$",
        ),
    ]
    """
    Identidade única da mensagem; também a chave de deduplicação do transporte.
    """
    schema_version: Annotated[
        str, Field(alias="schemaVersion", max_length=16, pattern="^[0-9]{1,4}\\.[0-9]{1,4}$")
    ]
    """
    Versão MAJOR.MINOR do contrato da mensagem (envelope e data).
    """
    message_type: Annotated[MessageType, Field(alias="messageType", title="MessageType")]
    """
    Tipo semântico da mensagem.
    """
    emitter: Annotated[MessageEmitter, Field(title="MessageEmitter")]
    """
    Emissor lógico (identidade funcional, não a instância).
    """
    module: Annotated[str, Field(max_length=63, min_length=1, pattern="^[a-z][a-z0-9-]*$")]
    """
    Módulo funcional ao qual a mensagem pertence (token do subject).
    """
    resource_type: Annotated[
        str, Field(alias="resourceType", max_length=63, min_length=1, pattern="^[a-z][a-z0-9-]*$")
    ]
    """
    Tipo de recurso (token do subject).
    """
    resource_id: Annotated[
        str,
        Field(
            alias="resourceId",
            max_length=128,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$",
        ),
    ]
    """
    Identidade estável e opaca do recurso (SCHEMA.md, Identificador do recurso).
    """
    operation: Annotated[MessageOperation, Field(title="MessageOperation")]
    """
    Operação ou resultado semântico associado. desired, observed e updated usam changed.
    """
    desired_generation: Annotated[
        int | None, Field(alias="desiredGeneration", ge=1, le=9007199254740991)
    ] = None
    """
    Geração lógica do estado desejado (desiredGeneration, observedGeneration).
    """
    observed_generation: Annotated[
        int | None, Field(alias="observedGeneration", ge=1, le=9007199254740991)
    ] = None
    """
    Geração desejada à qual a observação se relaciona; não é preenchida artificialmente.
    """
    presence: Presence | None = None
    action_id: Annotated[
        str | None,
        Field(alias="actionId", max_length=512, min_length=1, pattern="^[a-z0-9][a-z0-9.-]*$"),
    ] = None
    """
    Identidade determinística da decisão de reconciliação. O formato é definido pelo contrato do recurso (x-actionIdFormat no desired).
    """
    requested_by: Annotated[
        str | None,
        Field(alias="requestedBy", max_length=256, min_length=1, pattern="^[A-Za-z0-9._:@-]+$"),
    ] = None
    """
    Identificador opaco do solicitante autenticado (requestedBy). Não contém credenciais.
    """
    correlation_id: Annotated[
        str | None,
        Field(
            alias="correlationId",
            max_length=128,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$",
        ),
    ] = None
    """
    Identificador opaco atribuído pelo sistema (messageId, operationId, correlationId, causationId). O UUIDv7 em minúsculas atende ao padrão.
    """
    causation_id: Annotated[
        str | None,
        Field(
            alias="causationId",
            max_length=128,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$",
        ),
    ] = None
    """
    messageId da mensagem que causou esta.
    """
    occurred_at: Annotated[AwareDatetime, Field(alias="occurredAt")]
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    published_at: Annotated[AwareDatetime, Field(alias="publishedAt")]
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    published_by: Annotated[
        str | None,
        Field(alias="publishedBy", max_length=128, min_length=1, pattern="^[a-z][a-z0-9-]*$"),
    ] = None
    """
    Identidade de mensageria que entregou a mensagem ao transporte quando é diferente do emissor (o Publisher, nas mensagens `desired` e `updated`). O `emitter` continua sendo o autor da decisão.
    """
    observed_at: Annotated[AwareDatetime | None, Field(alias="observedAt")] = None
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    data: Annotated[dict[str, Any], Field(max_length=64)]
    """
    Conteúdo específico do messageType e do tipo de recurso, validado pelo respectivo contrato.
    """


class PaymentDesiredData(ContractModel):
    """
    data de desired do método de pagamento (bsm.payment): estado pretendido e controle de reconciliação. Publicado pela API. Não carrega PAN nem CVV.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    lifecycle: Lifecycle
    reconciliation: Reconciliation
    customer_account_id: Annotated[
        str,
        Field(
            alias="customerAccountId", max_length=256, min_length=1, pattern="^[A-Za-z0-9._:@-]+$"
        ),
    ]
    """
    Identificador da Customer Account (cam.account) titular deste método de pagamento.
    """
    display_name: Annotated[
        str, Field(alias="displayName", max_length=120, min_length=1, pattern="^[^\\r\\n\\t]+$")
    ]
    """
    Nome de exibição amigável do método de pagamento (por exemplo, Visa Corporativo Final 4242).
    """
    provider: PaymentProvider
    method_type: Annotated[PaymentMethodType, Field(alias="methodType")]
    provider_token: Annotated[
        str, Field(alias="providerToken", max_length=256, min_length=4, pattern="^[A-Za-z0-9._-]+$")
    ]
    """
    Token de uso único ou referência tokenizada emitida pelo gateway de pagamento (por exemplo, card_token_id do Mercado Pago). Nunca contém PAN ou CVV.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """
    owner_account_id: Annotated[
        str,
        Field(alias="ownerAccountId", max_length=256, min_length=1, pattern="^[A-Za-z0-9._:@-]+$"),
    ]
    """
    Dono do método de pagamento (sub do solicitante autenticado / customerAccountId). Atribuído pela API no create; imutável.
    """


class BsmPaymentContracts(
    RootModel[
        MessageEnvelope
        | Condition
        | ActionData
        | CompletedData
        | FailedData
        | UpdatedData
        | Operation
        | ApiAcceptedResponse
        | ApiError
        | PaymentDesiredData
        | PaymentObservedData
        | PaymentCreateRequest
        | PaymentUpdateRequest
        | Payment
        | PaymentList
    ]
):
    root: Annotated[
        MessageEnvelope
        | Condition
        | ActionData
        | CompletedData
        | FailedData
        | UpdatedData
        | Operation
        | ApiAcceptedResponse
        | ApiError
        | PaymentDesiredData
        | PaymentObservedData
        | PaymentCreateRequest
        | PaymentUpdateRequest
        | Payment
        | PaymentList,
        Field(title="BsmPaymentContracts"),
    ]
    """
    Índice dos contratos usados pelos componentes de payment do módulo bsm: entrada do gerador de modelos (decisão 0012). Não é um contrato. Todo contrato de common/ e de bsm/payment/ deve estar listado (verificado pelos testes de contrato).
    """
