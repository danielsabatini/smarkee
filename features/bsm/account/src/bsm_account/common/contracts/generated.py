# Gerado por datamodel-codegen a partir de schemas/ (decisão 0012). Não editar: altere o schema e regere.

from enum import StrEnum
from typing import Annotated, Any
from pydantic import AwareDatetime, ConfigDict, EmailStr, Field, RootModel
from datetime import timedelta
from bsm_account.common.contracts.base import ContractModel


class MessageType(StrEnum):
    """
    Tipo semântico da mensagem.
    """

    requested = "requested"
    desired = "desired"
    observed = "observed"
    action = "action"
    completed = "completed"
    failed = "failed"
    updated = "updated"


class MessageEmitter(StrEnum):
    """
    Emissor lógico (identidade funcional, não a instância).
    """

    receiver = "receiver"
    manager = "manager"
    observer = "observer"
    reconciler = "reconciler"
    executor = "executor"


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


class BillingCurrency(StrEnum):
    """
    Moeda ISO 4217 na qual a conta é faturada (BillingCurrency no FOCUS 1.4). Imutável após a criação.
    """

    brl = "BRL"
    usd = "USD"
    eur = "EUR"


class BillingContact(RootModel[EmailStr]):
    root: Annotated[EmailStr, Field(max_length=254, min_length=3)]
    """
    E-mail de contato financeiro para recebimento de faturas e alertas.
    """


class BillingAccountObservedData(ContractModel):
    """
    data de observed da Billing Account (bsm.account): estado lido do provedor (disco local na Fase P0). Os campos estão presentes quando presence é present; com absent ou unknown, data é vazio.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    display_name: Annotated[
        str | None,
        Field(
            alias="displayName",
            max_length=128,
            min_length=1,
            pattern="^[^\\u0000-\\u001f\\u007f]+$",
        ),
    ] = None
    """
    Nome de exibição da conta de faturamento (BillingAccountName no FOCUS 1.4).
    """
    billing_currency: Annotated[BillingCurrency | None, Field(alias="billingCurrency")] = None
    billing_contacts: Annotated[
        list[BillingContact] | None, Field(alias="billingContacts", max_length=10, min_length=1)
    ] = None
    """
    Conjunto de e-mails de contato financeiro, sem repetição.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão lida do provedor (decisão 0074).
    """


class BillingAccountCreateSpecification(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    display_name: Annotated[
        str,
        Field(
            alias="displayName",
            max_length=128,
            min_length=1,
            pattern="^[^\\u0000-\\u001f\\u007f]+$",
        ),
    ]
    """
    Nome de exibição da conta de faturamento (BillingAccountName no FOCUS 1.4).
    """
    billing_currency: Annotated[BillingCurrency, Field(alias="billingCurrency")]
    billing_contacts: Annotated[
        list[BillingContact], Field(alias="billingContacts", max_length=10, min_length=1)
    ]
    """
    Conjunto de e-mails de contato financeiro, sem repetição.
    """


class BillingAccountRequestedCreateData(ContractModel):
    """
    data de requested com operation create. Publicado somente pelo Receiver; o dono é o requestedBy.
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
    request_digest: Annotated[
        str, Field(alias="requestDigest", max_length=64, min_length=64, pattern="^[0-9a-f]{64}$")
    ]
    """
    SHA-256, em hexadecimal minúsculo, da forma canônica do conteúdo pedido.
    """
    specification: Annotated[
        BillingAccountCreateSpecification, Field(title="BillingAccountCreateSpecification")
    ]


class BillingAccountUpdateSpecification(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    display_name: Annotated[
        str | None,
        Field(
            alias="displayName",
            max_length=128,
            min_length=1,
            pattern="^[^\\u0000-\\u001f\\u007f]+$",
        ),
    ] = None
    """
    Nome de exibição da conta de faturamento (BillingAccountName no FOCUS 1.4).
    """
    billing_contacts: Annotated[
        list[BillingContact] | None, Field(alias="billingContacts", max_length=10, min_length=1)
    ] = None
    """
    Conjunto de e-mails de contato financeiro, sem repetição.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """


class BillingAccountRequestedUpdateData(ContractModel):
    """
    data de requested com operation update. Traz a especificação alterada, a mudança do controle de reconciliação, ou ambas. Publicado somente pelo Receiver.
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
    request_digest: Annotated[
        str, Field(alias="requestDigest", max_length=64, min_length=64, pattern="^[0-9a-f]{64}$")
    ]
    """
    SHA-256, em hexadecimal minúsculo, da forma canônica do conteúdo pedido.
    """
    resource_version: Annotated[
        str, Field(alias="resourceVersion", max_length=64, min_length=1, pattern="^[A-Za-z0-9-]+$")
    ]
    """
    Versão persistida do recurso, para concorrência otimista. Valor opaco: não é sequência, instante nem geração.
    """
    specification: Annotated[
        BillingAccountUpdateSpecification | None, Field(title="BillingAccountUpdateSpecification")
    ] = None
    reconciliation: Reconciliation | None = None
    """
    Muda só o controle de reconciliação; não incrementa desiredGeneration.
    """


class BillingAccountRequestedDeleteData(ContractModel):
    """
    data de requested com operation delete: declara lifecycle absent. Publicado somente pelo Receiver.
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
    request_digest: Annotated[
        str, Field(alias="requestDigest", max_length=64, min_length=64, pattern="^[0-9a-f]{64}$")
    ]
    """
    SHA-256, em hexadecimal minúsculo, da forma canônica do conteúdo pedido.
    """
    resource_version: Annotated[
        str, Field(alias="resourceVersion", max_length=64, min_length=1, pattern="^[A-Za-z0-9-]+$")
    ]
    """
    Versão persistida do recurso, para concorrência otimista. Valor opaco: não é sequência, instante nem geração.
    """


class BillingAccountCreateRequest(ContractModel):
    """
    Corpo de POST /v1/bsm/accounts. O Receiver atribui resourceId, operationId, requestDigest e requestedBy, e o Manager atribui ownerAccountId = solicitante autenticado e deletionProtection = true.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    display_name: Annotated[
        str,
        Field(
            alias="displayName",
            max_length=128,
            min_length=1,
            pattern="^[^\\u0000-\\u001f\\u007f]+$",
        ),
    ]
    """
    Nome de exibição da conta de faturamento (BillingAccountName no FOCUS 1.4).
    """
    billing_currency: Annotated[BillingCurrency, Field(alias="billingCurrency")]
    billing_contacts: Annotated[
        list[BillingContact], Field(alias="billingContacts", max_length=10, min_length=1)
    ]
    """
    Conjunto de e-mails de contato financeiro, sem repetição.
    """


class BillingAccountUpdateRequest(ContractModel):
    """
    Corpo de PATCH /v1/bsm/accounts/{resourceId}. resourceVersion é a versão lida; pelo menos um campo deve ser alterado. billingCurrency não é aceito porque é imutável.
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
        Field(
            alias="displayName",
            max_length=128,
            min_length=1,
            pattern="^[^\\u0000-\\u001f\\u007f]+$",
        ),
    ] = None
    """
    Nome de exibição da conta de faturamento (BillingAccountName no FOCUS 1.4).
    """
    billing_contacts: Annotated[
        list[BillingContact] | None, Field(alias="billingContacts", max_length=10, min_length=1)
    ] = None
    """
    Conjunto de e-mails de contato financeiro, sem repetição.
    """
    reconciliation: Reconciliation | None = None
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """


class BillingAccountDesiredView(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    lifecycle: Lifecycle
    reconciliation: Reconciliation
    display_name: Annotated[
        str,
        Field(
            alias="displayName",
            max_length=128,
            min_length=1,
            pattern="^[^\\u0000-\\u001f\\u007f]+$",
        ),
    ]
    """
    Nome de exibição da conta de faturamento (BillingAccountName no FOCUS 1.4).
    """
    billing_currency: Annotated[BillingCurrency, Field(alias="billingCurrency")]
    billing_contacts: Annotated[
        list[BillingContact], Field(alias="billingContacts", max_length=10, min_length=1)
    ]
    """
    Conjunto de e-mails de contato financeiro, sem repetição.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """


class BillingAccountObservedView(ContractModel):
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
    display_name: Annotated[
        str | None,
        Field(
            alias="displayName",
            max_length=128,
            min_length=1,
            pattern="^[^\\u0000-\\u001f\\u007f]+$",
        ),
    ] = None
    """
    Nome de exibição da conta de faturamento (BillingAccountName no FOCUS 1.4).
    """
    billing_currency: Annotated[BillingCurrency | None, Field(alias="billingCurrency")] = None
    billing_contacts: Annotated[
        list[BillingContact] | None, Field(alias="billingContacts", max_length=10, min_length=1)
    ] = None
    """
    Conjunto de e-mails de contato financeiro, sem repetição.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """


class BillingAccount(ContractModel):
    """
    Visão consolidada da Billing Account (bsm.account) exposta pelo Receiver (GET). Não expõe o dono (ownerAccountId) nem campos internos do SSOT (failureCount, requestedBy).
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
    Identificador da Billing Account (BillingAccountId no FOCUS 1.4).
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
    phase: Phase
    conditions: Annotated[list[Condition], Field(max_length=32)]
    desired: Annotated[BillingAccountDesiredView, Field(title="BillingAccountDesiredView")]
    observed: Annotated[
        BillingAccountObservedView | None, Field(title="BillingAccountObservedView")
    ] = None
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


class BillingAccountList(ContractModel):
    """
    Resposta de GET /v1/bsm/accounts: página ordenada por resourceId, somente das Billing Accounts autorizadas. nextCursor ausente indica a última página.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    items: Annotated[list[BillingAccount], Field(max_length=200)]
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


class BillingAccountDesiredData(ContractModel):
    """
    data de desired da Billing Account (bsm.account): estado pretendido e controle de reconciliação. Publicado somente pelo Manager.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    lifecycle: Lifecycle
    reconciliation: Reconciliation
    display_name: Annotated[
        str,
        Field(
            alias="displayName",
            max_length=128,
            min_length=1,
            pattern="^[^\\u0000-\\u001f\\u007f]+$",
        ),
    ]
    """
    Nome de exibição da conta de faturamento (BillingAccountName no FOCUS 1.4).
    """
    billing_currency: Annotated[BillingCurrency, Field(alias="billingCurrency")]
    billing_contacts: Annotated[
        list[BillingContact], Field(alias="billingContacts", max_length=10, min_length=1)
    ]
    """
    Conjunto de e-mails de contato financeiro, sem repetição.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """
    owner_account_id: Annotated[
        str,
        Field(
            alias="ownerAccountId",
            max_length=128,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$",
        ),
    ]
    """
    Dono da Billing Account: resourceId da Account autenticada que a criou (sub do token). Atribuído pelo Manager a partir de requestedBy no create; imutável.
    """


class BsmAccountContracts(
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
        | BillingAccountDesiredData
        | BillingAccountObservedData
        | BillingAccountRequestedCreateData
        | BillingAccountRequestedUpdateData
        | BillingAccountRequestedDeleteData
        | BillingAccountCreateRequest
        | BillingAccountUpdateRequest
        | BillingAccount
        | BillingAccountList
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
        | BillingAccountDesiredData
        | BillingAccountObservedData
        | BillingAccountRequestedCreateData
        | BillingAccountRequestedUpdateData
        | BillingAccountRequestedDeleteData
        | BillingAccountCreateRequest
        | BillingAccountUpdateRequest
        | BillingAccount
        | BillingAccountList,
        Field(title="BsmAccountContracts"),
    ]
    """
    Índice dos contratos usados pelos componentes de account do módulo bsm: entrada do gerador de modelos (decisão 0012). Não é um contrato. Todo contrato de common/ e de bsm/account/ deve estar listado (verificado pelos testes de contrato).
    """
