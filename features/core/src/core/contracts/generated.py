# Gerado por datamodel-codegen a partir de schemas/ (decisão 0012). Não editar: altere o schema e regere.

from enum import StrEnum
from typing import Annotated, Any
from pydantic import AwareDatetime, BaseModel, ConfigDict, EmailStr, Field, RootModel
from datetime import timedelta


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

    api = "api"
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

    Pending = "Pending"
    Reconciling = "Reconciling"
    Ready = "Ready"
    Failed = "Failed"
    Deleting = "Deleting"


class ConditionStatus(StrEnum):
    True_ = "True"
    False_ = "False"
    Unknown = "Unknown"


class Condition(BaseModel):
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
    observedGeneration: Annotated[int | None, Field(ge=1, le=9007199254740991)] = None
    """
    Geração lógica do estado desejado (desiredGeneration, observedGeneration).
    """
    lastTransitionAt: AwareDatetime
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """


class ActionData(BaseModel):
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


class CompletedData(BaseModel):
    """
    data de completed: a operação foi aplicada no sistema externo. Não significa convergência (RESOURCE-CONTROL-LOOP.md).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    externalReference: Annotated[str | None, Field(max_length=256, min_length=1)] = None
    """
    Referência do recurso no sistema externo, quando diferente do resourceId.
    """


class FailedData(BaseModel):
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


class UpdatedData(BaseModel):
    """
    data de updated: resumo do estado consolidado no SSOT depois de uma alteração.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    phase: Phase
    lifecycle: Lifecycle
    resourceVersion: Annotated[str, Field(max_length=64, min_length=1, pattern="^[A-Za-z0-9-]+$")]
    """
    Versão persistida do recurso, para concorrência otimista. Valor opaco: não é sequência, instante nem geração.
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


class OperationStatusReason(StrEnum):
    """
    Motivo da rejeição; presente somente quando operationStatus é rejected.
    """

    conflict = "conflict"
    validation = "validation"
    not_found = "not_found"


class Operation(BaseModel):
    """
    Acompanhamento de uma solicitação assíncrona, exposto por GET /v1/operations/{operationId} (SSOT.md, Operation).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    operationId: Annotated[
        str, Field(max_length=128, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")
    ]
    """
    Identificador opaco atribuído pelo sistema (messageId, operationId, correlationId, causationId). O UUIDv7 em minúsculas atende ao padrão.
    """
    operationType: Annotated[OperationType, Field(title="OperationType")]
    module: Annotated[str, Field(max_length=63, min_length=1, pattern="^[a-z][a-z0-9-]*$")]
    resourceType: Annotated[str, Field(max_length=63, min_length=1, pattern="^[a-z][a-z0-9-]*$")]
    resourceId: Annotated[
        str, Field(max_length=128, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")
    ]
    """
    Identidade estável e opaca do recurso (SCHEMA.md, Identificador do recurso).
    """
    desiredGeneration: Annotated[int | None, Field(ge=1, le=9007199254740991)] = None
    """
    Geração produzida pelo pedido; ausente quando rejeitado.
    """
    operationStatus: Annotated[OperationStatus, Field(title="OperationStatus")]
    operationStatusReason: Annotated[
        OperationStatusReason | None, Field(title="OperationStatusReason")
    ] = None
    """
    Motivo da rejeição; presente somente quando operationStatus é rejected.
    """
    createdAt: AwareDatetime
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    updatedAt: AwareDatetime
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    completedAt: AwareDatetime | None = None
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """


class ApiAcceptedResponse(BaseModel):
    """
    Resposta das escritas assíncronas (POST, PATCH, DELETE): o pedido foi publicado, não aplicado (RESOURCE-CONTROL-LOOP.md, Interface HTTP).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    resourceId: Annotated[
        str, Field(max_length=128, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")
    ]
    """
    Identidade estável e opaca do recurso (SCHEMA.md, Identificador do recurso).
    """
    operationId: Annotated[
        str, Field(max_length=128, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")
    ]
    """
    Identificador opaco atribuído pelo sistema (messageId, operationId, correlationId, causationId). O UUIDv7 em minúsculas atende ao padrão.
    """


class ApiError(BaseModel):
    """
    Corpo das respostas de erro da API. A mensagem identifica o campo e a regra violada e não repete valores confidential nem secretReference (SCHEMA.md, Limites e erros).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    errorCode: Annotated[str, Field(max_length=128, min_length=1, pattern="^[A-Z][A-Za-z0-9]*$")]
    """
    Código estável do erro, por exemplo ValidationFailed, Conflict, IdempotencyKeyReused.
    """
    message: Annotated[str, Field(max_length=4096)]
    """
    Texto descritivo para pessoas. Nunca contém valores confidential ou secretReference.
    """
    field: Annotated[str | None, Field(max_length=256, min_length=1)] = None
    """
    Caminho do campo inválido no corpo do pedido, quando aplicável (por exemplo, firstAdministrator.email).
    """


class PlatformAccess(StrEnum):
    """
    Intenção de acesso da organização à plataforma: granted mantém o Project Grant do projeto da plataforma; revoked o remove (usuários da organização deixam de acessar).
    """

    granted = "granted"
    revoked = "revoked"


class FirstAdministrator(BaseModel):
    """
    Primeiro usuário administrador da organização. Usado somente na criação; alterações posteriores são feitas no próprio usuário.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    email: Annotated[EmailStr, Field(max_length=254, min_length=3)]
    givenName: Annotated[str, Field(max_length=256, min_length=1)]
    familyName: Annotated[str, Field(max_length=256, min_length=1)]


class OrganizationState(StrEnum):
    """
    Estado da organização no provedor de identidade.
    """

    active = "active"
    inactive = "inactive"


class OrganizationObservedData(BaseModel):
    """
    data de observed da Organization: estado lido do provedor de identidade. Os campos estão presentes quando presence é present; com absent ou unknown, data é vazio.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[
        str | None,
        Field(max_length=63, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"),
    ] = None
    """
    Nome único da organização na instância de identidade. Minúsculas, dígitos e hífen, como rótulo DNS.
    """
    platformAccess: PlatformAccess | None = None
    """
    granted quando o Project Grant do projeto da plataforma existe para a organização.
    """
    organizationState: OrganizationState | None = None


class OrganizationCreateSpecification(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[
        str, Field(max_length=63, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
    ]
    """
    Nome único da organização na instância de identidade. Minúsculas, dígitos e hífen, como rótulo DNS.
    """
    platformAccess: PlatformAccess
    firstAdministrator: FirstAdministrator


class OrganizationRequestedCreateData(BaseModel):
    """
    data de requested com operation create. Publicado somente pela API.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    operationId: Annotated[
        str, Field(max_length=128, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")
    ]
    """
    Identificador opaco atribuído pelo sistema (messageId, operationId, correlationId, causationId). O UUIDv7 em minúsculas atende ao padrão.
    """
    requestDigest: Annotated[str, Field(max_length=64, min_length=64, pattern="^[0-9a-f]{64}$")]
    """
    SHA-256, em hexadecimal minúsculo, da forma canônica do conteúdo pedido.
    """
    specification: Annotated[
        OrganizationCreateSpecification, Field(title="OrganizationCreateSpecification")
    ]


class OrganizationUpdateSpecification(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[
        str | None,
        Field(max_length=63, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"),
    ] = None
    """
    Nome único da organização na instância de identidade. Minúsculas, dígitos e hífen, como rótulo DNS.
    """
    platformAccess: PlatformAccess | None = None


class OrganizationRequestedUpdateData(BaseModel):
    """
    data de requested com operation update. Traz a especificação alterada, a mudança do controle de reconciliação, ou ambas. Publicado somente pela API.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    operationId: Annotated[
        str, Field(max_length=128, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")
    ]
    """
    Identificador opaco atribuído pelo sistema (messageId, operationId, correlationId, causationId). O UUIDv7 em minúsculas atende ao padrão.
    """
    requestDigest: Annotated[str, Field(max_length=64, min_length=64, pattern="^[0-9a-f]{64}$")]
    """
    SHA-256, em hexadecimal minúsculo, da forma canônica do conteúdo pedido.
    """
    resourceVersion: Annotated[str, Field(max_length=64, min_length=1, pattern="^[A-Za-z0-9-]+$")]
    """
    Versão persistida do recurso, para concorrência otimista. Valor opaco: não é sequência, instante nem geração.
    """
    specification: Annotated[
        OrganizationUpdateSpecification | None, Field(title="OrganizationUpdateSpecification")
    ] = None
    reconciliation: Reconciliation | None = None
    """
    Muda só o controle de reconciliação; não incrementa desiredGeneration.
    """


class OrganizationRequestedDeleteData(BaseModel):
    """
    data de requested com operation delete: declara lifecycle absent. Publicado somente pela API.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    operationId: Annotated[
        str, Field(max_length=128, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")
    ]
    """
    Identificador opaco atribuído pelo sistema (messageId, operationId, correlationId, causationId). O UUIDv7 em minúsculas atende ao padrão.
    """
    requestDigest: Annotated[str, Field(max_length=64, min_length=64, pattern="^[0-9a-f]{64}$")]
    """
    SHA-256, em hexadecimal minúsculo, da forma canônica do conteúdo pedido.
    """
    resourceVersion: Annotated[str, Field(max_length=64, min_length=1, pattern="^[A-Za-z0-9-]+$")]
    """
    Versão persistida do recurso, para concorrência otimista. Valor opaco: não é sequência, instante nem geração.
    """


class OrganizationCreateRequest(BaseModel):
    """
    Corpo de POST /v1/organizations. A API atribui resourceId, operationId, requestDigest e requestedBy, e registra platformAccess = granted: uma Organization criada sem acesso à plataforma não tem uso.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[
        str, Field(max_length=63, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
    ]
    """
    Nome único da organização na instância de identidade. Minúsculas, dígitos e hífen, como rótulo DNS.
    """
    firstAdministrator: FirstAdministrator


class OrganizationUpdateRequest(BaseModel):
    """
    Corpo de PATCH /v1/organizations/{resourceId}. resourceVersion é a versão lida; pelo menos um campo deve ser alterado.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    resourceVersion: Annotated[str, Field(max_length=64, min_length=1, pattern="^[A-Za-z0-9-]+$")]
    """
    Versão persistida do recurso, para concorrência otimista. Valor opaco: não é sequência, instante nem geração.
    """
    name: Annotated[
        str | None,
        Field(max_length=63, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"),
    ] = None
    """
    Nome único da organização na instância de identidade. Minúsculas, dígitos e hífen, como rótulo DNS.
    """
    platformAccess: PlatformAccess | None = None
    reconciliation: Reconciliation | None = None


class OrganizationDesiredView(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    lifecycle: Lifecycle
    reconciliation: Reconciliation
    name: Annotated[
        str, Field(max_length=63, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
    ]
    """
    Nome único da organização na instância de identidade. Minúsculas, dígitos e hífen, como rótulo DNS.
    """
    platformAccess: PlatformAccess


class OrganizationObservedView(BaseModel):
    """
    Última observação; ausente antes da primeira.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    presence: Presence
    observedAt: AwareDatetime
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    name: Annotated[
        str | None,
        Field(max_length=63, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"),
    ] = None
    """
    Nome único da organização na instância de identidade. Minúsculas, dígitos e hífen, como rótulo DNS.
    """
    platformAccess: PlatformAccess | None = None
    organizationState: OrganizationState | None = None


class Organization(BaseModel):
    """
    Visão consolidada da Organization exposta pela API (GET). Não expõe firstAdministrator (confidential) nem campos internos do SSOT (failureCount, requestedBy).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    resourceId: Annotated[
        str, Field(max_length=128, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")
    ]
    """
    Também o ID da organização no provedor de identidade e dos namespaces derivados (SCHEMA.md, Organization e identificadores derivados).
    """
    resourceVersion: Annotated[str, Field(max_length=64, min_length=1, pattern="^[A-Za-z0-9-]+$")]
    """
    Versão persistida do recurso, para concorrência otimista. Valor opaco: não é sequência, instante nem geração.
    """
    desiredGeneration: Annotated[int, Field(ge=1, le=9007199254740991)]
    """
    Geração lógica do estado desejado (desiredGeneration, observedGeneration).
    """
    phase: Phase
    conditions: Annotated[list[Condition], Field(max_length=32)]
    desired: Annotated[OrganizationDesiredView, Field(title="OrganizationDesiredView")]
    observed: Annotated[
        OrganizationObservedView | None, Field(title="OrganizationObservedView")
    ] = None
    """
    Última observação; ausente antes da primeira.
    """
    createdAt: AwareDatetime
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    updatedAt: AwareDatetime
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """


class OrganizationList(BaseModel):
    """
    Resposta de GET /v1/organizations: página ordenada por resourceId, somente das Organizations autorizadas. nextCursor ausente indica a última página.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    items: Annotated[list[Organization], Field(max_length=200)]
    nextCursor: Annotated[
        str | None, Field(max_length=512, min_length=1, pattern="^[A-Za-z0-9_-]+$")
    ] = None
    """
    Cursor opaco da próxima página.
    """


class MessageEnvelope(BaseModel):
    """
    Metadados de transporte e rastreamento de toda mensagem (MESSAGING.md, Campos do envelope). O conteúdo de data é validado pelo contrato do messageType e do tipo de recurso. O tamanho de data é limitado a 256 KiB.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    messageId: Annotated[
        str, Field(max_length=128, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")
    ]
    """
    Identidade única da mensagem; também a chave de deduplicação do transporte.
    """
    schemaVersion: Annotated[str, Field(max_length=16, pattern="^[0-9]{1,4}\\.[0-9]{1,4}$")]
    """
    Versão MAJOR.MINOR do contrato da mensagem (envelope e data).
    """
    messageType: Annotated[MessageType, Field(title="MessageType")]
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
    resourceType: Annotated[str, Field(max_length=63, min_length=1, pattern="^[a-z][a-z0-9-]*$")]
    """
    Tipo de recurso (token do subject).
    """
    resourceId: Annotated[
        str, Field(max_length=128, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$")
    ]
    """
    Identidade estável e opaca do recurso (SCHEMA.md, Identificador do recurso).
    """
    operation: Annotated[MessageOperation, Field(title="MessageOperation")]
    """
    Operação ou resultado semântico associado. desired, observed e updated usam changed.
    """
    desiredGeneration: Annotated[int | None, Field(ge=1, le=9007199254740991)] = None
    """
    Geração lógica do estado desejado (desiredGeneration, observedGeneration).
    """
    observedGeneration: Annotated[int | None, Field(ge=1, le=9007199254740991)] = None
    """
    Geração desejada à qual a observação se relaciona; não é preenchida artificialmente.
    """
    presence: Presence | None = None
    actionId: Annotated[
        str | None, Field(max_length=512, min_length=1, pattern="^[a-z0-9][a-z0-9.-]*$")
    ] = None
    """
    Identidade determinística da decisão de reconciliação. O formato é definido pelo contrato do recurso (x-actionIdFormat no desired).
    """
    requestedBy: Annotated[
        str | None, Field(max_length=256, min_length=1, pattern="^[A-Za-z0-9._:@-]+$")
    ] = None
    """
    Identificador opaco do solicitante autenticado (requestedBy). Não contém credenciais.
    """
    correlationId: Annotated[
        str | None,
        Field(max_length=128, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$"),
    ] = None
    """
    Identificador opaco atribuído pelo sistema (messageId, operationId, correlationId, causationId). O UUIDv7 em minúsculas atende ao padrão.
    """
    causationId: Annotated[
        str | None,
        Field(max_length=128, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$"),
    ] = None
    """
    messageId da mensagem que causou esta.
    """
    occurredAt: AwareDatetime
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    publishedAt: AwareDatetime
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    observedAt: AwareDatetime | None = None
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    data: Annotated[dict[str, Any], Field(max_length=64)]
    """
    Conteúdo específico do messageType e do tipo de recurso, validado pelo respectivo contrato.
    """


class OrganizationDesiredData(BaseModel):
    """
    data de desired da Organization: estado pretendido e controle de reconciliação. Publicado somente pelo Manager.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    lifecycle: Lifecycle
    reconciliation: Reconciliation
    name: Annotated[
        str, Field(max_length=63, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
    ]
    """
    Nome único da organização na instância de identidade. Minúsculas, dígitos e hífen, como rótulo DNS.
    """
    platformAccess: PlatformAccess
    firstAdministrator: FirstAdministrator


class CoreContracts(
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
        | OrganizationDesiredData
        | OrganizationObservedData
        | OrganizationRequestedCreateData
        | OrganizationRequestedUpdateData
        | OrganizationRequestedDeleteData
        | OrganizationCreateRequest
        | OrganizationUpdateRequest
        | Organization
        | OrganizationList
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
        | OrganizationDesiredData
        | OrganizationObservedData
        | OrganizationRequestedCreateData
        | OrganizationRequestedUpdateData
        | OrganizationRequestedDeleteData
        | OrganizationCreateRequest
        | OrganizationUpdateRequest
        | Organization
        | OrganizationList,
        Field(title="CoreContracts"),
    ]
    """
    Índice dos contratos usados pelo módulo core: entrada do gerador de modelos (decisão 0012). Não é um contrato. Todo contrato de common/ e core/ deve estar listado (verificado pelos testes de contrato).
    """
