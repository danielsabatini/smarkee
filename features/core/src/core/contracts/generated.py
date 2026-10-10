# Gerado por datamodel-codegen a partir de schemas/ (decisão 0012). Não editar: altere o schema e regere.

from enum import StrEnum
from typing import Annotated, Any
from pydantic import AwareDatetime, ConfigDict, EmailStr, Field, RootModel
from datetime import timedelta
from core.contracts.base import ContractModel


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

    pending = "Pending"
    reconciling = "Reconciling"
    ready = "Ready"
    failed = "Failed"
    deleting = "Deleting"


class PlatformAccess(StrEnum):
    """
    Intenção de acesso à plataforma: granted mantém a autorização no projeto da plataforma (Project Grant da Organization; conjunto de roles de ação do usuário cadastrado, no User); revoked a remove.
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
    Motivo da rejeição; presente somente quando operationStatus é rejected.
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
    Corpo das respostas de erro da API. A mensagem identifica o campo e a regra violada e não repete valores confidential nem secretReference (SCHEMA.md, Limites e erros).
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


class OrganizationState(StrEnum):
    """
    Estado da organização no provedor de identidade.
    """

    active = "active"
    inactive = "inactive"


class OrganizationObservedData(ContractModel):
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
    platform_access: Annotated[PlatformAccess | None, Field(alias="platformAccess")] = None
    """
    granted quando o Project Grant do projeto da plataforma existe para a organização.
    """
    organization_state: Annotated[OrganizationState | None, Field(alias="organizationState")] = None


class OrganizationCreateSpecification(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    name: Annotated[
        str, Field(max_length=63, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$")
    ]
    """
    Nome único da organização na instância de identidade. Minúsculas, dígitos e hífen, como rótulo DNS.
    """
    platform_access: Annotated[PlatformAccess, Field(alias="platformAccess")]


class OrganizationRequestedCreateData(ContractModel):
    """
    data de requested com operation create. Publicado somente pela API; o dono é o requestedBy.
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
        OrganizationCreateSpecification, Field(title="OrganizationCreateSpecification")
    ]
    owner_quota_limit: Annotated[int | None, Field(alias="ownerQuotaLimit", ge=1, le=1000)] = None
    """
    Limite de Organizations do dono, definido pela API a partir do papel do solicitante (ausente para operadores: sem cota). O Manager aplica o limite na mesma unidade atômica do pedido (decisão 0010).
    """


class OrganizationUpdateSpecification(ContractModel):
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
    platform_access: Annotated[PlatformAccess | None, Field(alias="platformAccess")] = None


class OrganizationRequestedUpdateData(ContractModel):
    """
    data de requested com operation update. Traz a especificação alterada, a mudança do controle de reconciliação, ou ambas. Publicado somente pela API.
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
        OrganizationUpdateSpecification | None, Field(title="OrganizationUpdateSpecification")
    ] = None
    reconciliation: Reconciliation | None = None
    """
    Muda só o controle de reconciliação; não incrementa desiredGeneration.
    """


class OrganizationRequestedDeleteData(ContractModel):
    """
    data de requested com operation delete: declara lifecycle absent. Publicado somente pela API.
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


class OrganizationCreateRequest(ContractModel):
    """
    Corpo de POST /v1/organizations. A API atribui resourceId, operationId, requestDigest e requestedBy, registra platformAccess = granted e o dono (ownerUserId = solicitante autenticado): uma Organization criada sem acesso à plataforma não tem uso.
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


class OrganizationUpdateRequest(ContractModel):
    """
    Corpo de PATCH /v1/organizations/{resourceId}. resourceVersion é a versão lida; pelo menos um campo deve ser alterado.
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
    name: Annotated[
        str | None,
        Field(max_length=63, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"),
    ] = None
    """
    Nome único da organização na instância de identidade. Minúsculas, dígitos e hífen, como rótulo DNS.
    """
    platform_access: Annotated[PlatformAccess | None, Field(alias="platformAccess")] = None
    reconciliation: Reconciliation | None = None


class OrganizationDesiredView(ContractModel):
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
    platform_access: Annotated[PlatformAccess, Field(alias="platformAccess")]


class OrganizationObservedView(ContractModel):
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
    name: Annotated[
        str | None,
        Field(max_length=63, min_length=1, pattern="^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$"),
    ] = None
    """
    Nome único da organização na instância de identidade. Minúsculas, dígitos e hífen, como rótulo DNS.
    """
    platform_access: Annotated[PlatformAccess | None, Field(alias="platformAccess")] = None
    organization_state: Annotated[OrganizationState | None, Field(alias="organizationState")] = None


class Organization(ContractModel):
    """
    Visão consolidada da Organization exposta pela API (GET). Não expõe o dono (ownerUserId) nem campos internos do SSOT (failureCount, requestedBy).
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
    Também o ID da organização no provedor de identidade e dos namespaces derivados (SCHEMA.md, Organization e identificadores derivados).
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
    desired: Annotated[OrganizationDesiredView, Field(title="OrganizationDesiredView")]
    observed: Annotated[
        OrganizationObservedView | None, Field(title="OrganizationObservedView")
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


class OrganizationList(ContractModel):
    """
    Resposta de GET /v1/organizations: página ordenada por resourceId, somente das Organizations autorizadas. nextCursor ausente indica a última página.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    items: Annotated[list[Organization], Field(max_length=200)]
    next_cursor: Annotated[
        str | None,
        Field(alias="nextCursor", max_length=512, min_length=1, pattern="^[A-Za-z0-9_-]+$"),
    ] = None
    """
    Cursor opaco da próxima página.
    """


class UserState(StrEnum):
    """
    Estado do usuário no provedor de identidade. initial: aguardando a ativação (definição da senha).
    """

    initial = "initial"
    active = "active"
    inactive = "inactive"
    locked = "locked"


class UserObservedData(ContractModel):
    """
    data de observed do User: estado lido do provedor de identidade. Os campos estão presentes quando presence é present; com absent ou unknown, data é vazio.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    email_verified: Annotated[bool | None, Field(alias="emailVerified")] = None
    """
    Se o e-mail foi verificado (a ativação foi concluída).
    """
    user_state: Annotated[UserState | None, Field(alias="userState")] = None
    platform_access: Annotated[PlatformAccess | None, Field(alias="platformAccess")] = None
    """
    granted quando o conjunto de roles de ação do usuário cadastrado está atribuído a ele no projeto da plataforma.
    """


class UserCreateSpecification(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    given_name: Annotated[str, Field(alias="givenName", max_length=256, min_length=1)]
    """
    Nome próprio do usuário.
    """
    family_name: Annotated[str, Field(alias="familyName", max_length=256, min_length=1)]
    """
    Sobrenome do usuário.
    """
    email: Annotated[EmailStr, Field(max_length=254, min_length=3)]
    """
    E-mail do usuário; é também o nome de login. Imutável: a troca de e-mail é feita pelo fluxo do provedor de identidade.
    """


class UserRequestedCreateData(ContractModel):
    """
    data de requested com operation create. Publicado somente pela API, com requestedBy = anonymous no auto-cadastro. Sem senha (decisão 0014).
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
    specification: Annotated[UserCreateSpecification, Field(title="UserCreateSpecification")]


class UserRequestedDeleteData(ContractModel):
    """
    data de requested com operation delete: declara lifecycle absent. Publicado somente pela API.
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


class UserCreateRequest(ContractModel):
    """
    Corpo de POST /v1/users (auto-cadastro, escrita anônima). A API atribui resourceId, operationId e requestDigest, e requestedBy = anonymous. Não há senha: a pessoa a define na página do provedor de identidade, pelo e-mail de ativação.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    given_name: Annotated[str, Field(alias="givenName", max_length=256, min_length=1)]
    """
    Nome próprio do usuário.
    """
    family_name: Annotated[str, Field(alias="familyName", max_length=256, min_length=1)]
    """
    Sobrenome do usuário.
    """
    email: Annotated[EmailStr, Field(max_length=254, min_length=3)]
    """
    E-mail do usuário; é também o nome de login. Imutável: a troca de e-mail é feita pelo fluxo do provedor de identidade.
    """


class UserDesiredView(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    lifecycle: Lifecycle
    reconciliation: Reconciliation
    platform_access: Annotated[PlatformAccess, Field(alias="platformAccess")]
    given_name: Annotated[str | None, Field(alias="givenName", max_length=256, min_length=1)] = None
    """
    Nome próprio do usuário.
    """
    family_name: Annotated[str | None, Field(alias="familyName", max_length=256, min_length=1)] = (
        None
    )
    """
    Sobrenome do usuário.
    """
    email: Annotated[EmailStr | None, Field(max_length=254, min_length=3)] = None
    """
    E-mail do usuário; é também o nome de login. Imutável: a troca de e-mail é feita pelo fluxo do provedor de identidade.
    """


class UserObservedView(ContractModel):
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
    email_verified: Annotated[bool | None, Field(alias="emailVerified")] = None
    user_state: Annotated[UserState | None, Field(alias="userState")] = None
    platform_access: Annotated[PlatformAccess | None, Field(alias="platformAccess")] = None


class User(ContractModel):
    """
    Visão consolidada do User exposta pela API (GET /v1/users/{resourceId}), legível pelo próprio usuário e por operadores. Não expõe campos internos do SSOT (failureCount, requestedBy).
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
    Também o ID do usuário no provedor de identidade (decisão 0014).
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
    desired: Annotated[UserDesiredView, Field(title="UserDesiredView")]
    observed: Annotated[UserObservedView | None, Field(title="UserObservedView")] = None
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
    observed_at: Annotated[AwareDatetime | None, Field(alias="observedAt")] = None
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    data: Annotated[dict[str, Any], Field(max_length=64)]
    """
    Conteúdo específico do messageType e do tipo de recurso, validado pelo respectivo contrato.
    """


class OrganizationDesiredData(ContractModel):
    """
    data de desired da Organization: estado pretendido e controle de reconciliação. Publicado somente pelo Manager. Não carrega dados pessoais.
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
    platform_access: Annotated[PlatformAccess, Field(alias="platformAccess")]
    owner_user_id: Annotated[
        str,
        Field(
            alias="ownerUserId",
            max_length=128,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$",
        ),
    ]
    """
    Dono da Organization: resourceId do User autenticado que a criou (sub do token). Atribuído pelo Manager a partir de requestedBy no create; imutável.
    """


class UserDesiredData(ContractModel):
    """
    data de desired do User: estado pretendido e controle de reconciliação. Publicado somente pelo Manager. Sem senha: a credencial é definida pelo usuário no provedor de identidade (decisão 0014). Com lifecycle absent, não carrega dados pessoais.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    lifecycle: Lifecycle
    reconciliation: Reconciliation
    platform_access: Annotated[PlatformAccess, Field(alias="platformAccess")]
    """
    granted: o usuário tem o conjunto de roles de ação do usuário cadastrado no projeto da plataforma. Atribuído pelo Manager na criação.
    """
    given_name: Annotated[str | None, Field(alias="givenName", max_length=256, min_length=1)] = None
    """
    Nome próprio do usuário.
    """
    family_name: Annotated[str | None, Field(alias="familyName", max_length=256, min_length=1)] = (
        None
    )
    """
    Sobrenome do usuário.
    """
    email: Annotated[EmailStr | None, Field(max_length=254, min_length=3)] = None
    """
    E-mail do usuário; é também o nome de login. Imutável: a troca de e-mail é feita pelo fluxo do provedor de identidade.
    """


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
        | UserDesiredData
        | UserObservedData
        | UserRequestedCreateData
        | UserRequestedDeleteData
        | UserCreateRequest
        | User
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
        | OrganizationList
        | UserDesiredData
        | UserObservedData
        | UserRequestedCreateData
        | UserRequestedDeleteData
        | UserCreateRequest
        | User,
        Field(title="CoreContracts"),
    ]
    """
    Índice dos contratos usados pelo módulo core: entrada do gerador de modelos (decisão 0012). Não é um contrato. Todo contrato de common/ e core/ deve estar listado (verificado pelos testes de contrato).
    """
