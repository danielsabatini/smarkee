# Gerado por datamodel-codegen a partir de schemas/ (decisão 0012). Não editar: altere o schema e regere.

from enum import StrEnum
from typing import Annotated, Any
from pydantic import AwareDatetime, ConfigDict, Field, RootModel
from datetime import timedelta
from ipm_serviceaccount.common.contracts.base import ContractModel


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


class Permission(RootModel[str]):
    root: Annotated[
        str,
        Field(
            max_length=128,
            min_length=5,
            pattern="^[a-z][a-z0-9]*\\.[a-z][a-z0-9]*\\.[a-z][a-z0-9]*$",
        ),
    ]
    """
    Permissão da plataforma no padrão <módulo>.<tipo>.<ação> (decisão 0028). Só são aceitas as permissões do Project Grant da Organization.
    """


class RoleName(RootModel[str]):
    root: Annotated[
        str, Field(max_length=128, min_length=5, pattern="^[a-z][a-z0-9]*\\.[a-z][a-zA-Z0-9]*$")
    ]
    """
    Identificador semântico da Role composta (<módulo>.<tipo><Admin|Viewer> ou custom, decisões 0083 e 0092), por exemplo ipm.serviceaccountViewer.
    """


class KeyStatus(StrEnum):
    """
    active: a chave está no provedor e vale. expired: a chave do desired já venceu e o provedor a removeu.
    """

    active = "active"
    expired = "expired"


class ServiceAccountKeySpecification(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    public_key: Annotated[
        str,
        Field(
            alias="publicKey",
            max_length=2048,
            min_length=200,
            pattern="^-----BEGIN PUBLIC KEY-----\\n[A-Za-z0-9+/=\\n]+-----END PUBLIC KEY-----\\n?$",
        ),
    ]
    """
    Chave pública RSA (mínimo 2048 bits) em PEM (SubjectPublicKeyInfo). Não é segredo. A chave privada correspondente nunca sai do cliente.
    """
    expires_at: Annotated[AwareDatetime, Field(alias="expiresAt")]
    """
    Vencimento da chave: no futuro e em até 365 dias da criação.
    """


class ServiceAccountDesiredKey(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    public_key: Annotated[
        str,
        Field(
            alias="publicKey",
            max_length=2048,
            min_length=200,
            pattern="^-----BEGIN PUBLIC KEY-----\\n[A-Za-z0-9+/=\\n]+-----END PUBLIC KEY-----\\n?$",
        ),
    ]
    """
    Chave pública RSA (mínimo 2048 bits) em PEM (SubjectPublicKeyInfo). Não é segredo. A chave privada correspondente nunca sai do cliente.
    """
    expires_at: Annotated[AwareDatetime, Field(alias="expiresAt")]
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    fingerprint: Annotated[str, Field(max_length=64, min_length=64, pattern="^[0-9a-f]{64}$")]
    """
    SHA-256, em hexadecimal minúsculo, do DER SubjectPublicKeyInfo da chave pública. Calculado pelo Receiver; identifica a chave entre o desired e o observed (o provedor não devolve a pública).
    """


class ServiceAccountObservedKey(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    fingerprint: Annotated[str, Field(max_length=64, min_length=64, pattern="^[0-9a-f]{64}$")]
    """
    SHA-256, em hexadecimal minúsculo, do DER SubjectPublicKeyInfo da chave pública. Calculado pelo Receiver; identifica a chave entre o desired e o observed (o provedor não devolve a pública).
    """
    key_id: Annotated[
        str | None, Field(alias="keyId", max_length=128, min_length=1, pattern="^[A-Za-z0-9_.-]+$")
    ] = None
    """
    Identificador da chave no provedor de identidade (kid da assertion).
    """
    expires_at: Annotated[AwareDatetime | None, Field(alias="expiresAt")] = None
    """
    Instante com fuso explícito (RFC 3339), por exemplo 2026-10-04T14:00:00Z.
    """
    status: KeyStatus


class UserState(StrEnum):
    """
    Estado da service account (machine user) no provedor de identidade.
    """

    active = "active"
    inactive = "inactive"
    locked = "locked"


class AccessTokenType(StrEnum):
    """
    Tipo do access token da máquina. A plataforma exige jwt (token opaco não é aceito pelo gateway).
    """

    jwt = "jwt"
    bearer = "bearer"


class ServiceAccountObservedData(ContractModel):
    """
    data de observed da service account: estado lido do provedor de identidade. Os campos estão presentes quando presence é present; com absent ou unknown, data é vazio. Sem material privado.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    user_state: Annotated[UserState | None, Field(alias="userState")] = None
    access_token_type: Annotated[AccessTokenType | None, Field(alias="accessTokenType")] = None
    description: Annotated[
        str | None, Field(max_length=256, min_length=1, pattern="^[^\\u0000-\\u001f\\u007f]+$")
    ] = None
    """
    Descrição lida da máquina no provedor; ausente quando vazia.
    """
    permissions: Annotated[list[Permission] | None, Field(max_length=64)] = None
    """
    Permissões que a service account tem hoje na Organization, lidas das autorizações dela.
    """
    effective_permissions: Annotated[
        list[Permission] | None, Field(alias="effectivePermissions", max_length=64)
    ] = None
    """
    Permissões efetivas que o Controller calculou das `roles` da service account a partir do catálogo (decisão 0097) e que reconcilia no provedor. Não fazem parte do `desired`: mudar uma Role as recalcula sem nova geração.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Lida do metadado deletionProtection (decisão 0074). Ausente quando o metadado não existe ou é inválido.
    """
    keys: Annotated[list[ServiceAccountObservedKey] | None, Field(max_length=8)] = None
    """
    Chaves lidas do provedor (e do metadado de mapeamento), sem material privado.
    """


class ServiceAccountCreateSpecification(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    organization_id: Annotated[
        str,
        Field(
            alias="organizationId",
            max_length=128,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$",
        ),
    ]
    """
    Identidade estável e opaca do recurso (SCHEMA.md, Identificador do recurso).
    """
    name: Annotated[
        str, Field(max_length=63, min_length=2, pattern="^[a-z][a-z0-9-]{0,61}[a-z0-9]$")
    ]
    """
    Nome único da service account dentro da Organization. Minúsculas, dígitos e hífen (slug). Imutável após a criação; é também o nome de usuário (username) da máquina no provedor de identidade.
    """
    description: Annotated[
        str | None, Field(max_length=256, min_length=1, pattern="^[^\\u0000-\\u001f\\u007f]+$")
    ] = None
    """
    Descrição legível do propósito da service account.
    """
    roles: Annotated[list[RoleName] | None, Field(max_length=32)] = None
    """
    Conjunto de Roles atribuídas à service account na Organization, sem repetição e em ordem alfabética. O Controller as expande em permissões atômicas (`observed.effectivePermissions`, decisão 0097).
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """
    keys: Annotated[list[ServiceAccountDesiredKey], Field(max_length=3, min_length=1)]
    """
    Chaves pretendidas, já com o fingerprint calculado pelo Receiver. No máximo 3.
    """


class ServiceAccountRequestedCreateData(ContractModel):
    """
    data de requested com operation create. Publicado somente pelo Receiver, depois de conferir a Organization, o escopo de quem pede, a cota, o teto de roles e as chaves públicas (RSA de 2048 bits ou mais), que chegam com o fingerprint calculado (decisão 0094). Sem material privado.
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
        ServiceAccountCreateSpecification, Field(title="ServiceAccountCreateSpecification")
    ]
    organization_quota_limit: Annotated[
        int | None, Field(alias="organizationQuotaLimit", ge=1, le=1000)
    ] = None
    """
    Limite de service accounts da Organization, definido pelo Receiver (ausente para operadores: sem cota). O Manager aplica o limite na mesma unidade atômica do pedido, sob trava por Organization (decisão 0094).
    """


class ServiceAccountRequestedDeleteData(ContractModel):
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


class ServiceAccountUpdateSpecification(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    description: Annotated[
        str | None, Field(max_length=256, min_length=1, pattern="^[^\\u0000-\\u001f\\u007f]+$")
    ] = None
    """
    Descrição legível do propósito da service account.
    """
    roles: Annotated[list[RoleName] | None, Field(max_length=32)] = None
    """
    Conjunto de Roles atribuídas à service account na Organization, sem repetição e em ordem alfabética. O Controller as expande em permissões atômicas (`observed.effectivePermissions`, decisão 0097).
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """
    keys: Annotated[list[ServiceAccountDesiredKey] | None, Field(max_length=3, min_length=1)] = None
    """
    Chaves pretendidas, já com o fingerprint calculado pelo Receiver. No máximo 3.
    """


class ServiceAccountRequestedUpdateData(ContractModel):
    """
    data de requested com operation update. Traz a descrição, as roles, as chaves, a proteção contra exclusão, a mudança do controle de reconciliação, ou uma combinação delas. Publicado somente pelo Receiver.
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
        ServiceAccountUpdateSpecification | None, Field(title="ServiceAccountUpdateSpecification")
    ] = None
    reconciliation: Reconciliation | None = None
    """
    Muda só o controle de reconciliação; não incrementa desiredGeneration.
    """


class ServiceAccountCreateRequest(ContractModel):
    """
    Corpo de POST /v1/ipm/serviceaccounts. O Receiver atribui resourceId (o ID da máquina no provedor), operationId, requestDigest e requestedBy. keys leva só chaves PÚBLICAS: a privada é gerada e guardada pelo cliente. deletionProtection ausente equivale a true (decisão 0094).
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    organization_id: Annotated[
        str,
        Field(
            alias="organizationId",
            max_length=128,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$",
        ),
    ]
    """
    Identidade estável e opaca do recurso (SCHEMA.md, Identificador do recurso).
    """
    name: Annotated[
        str, Field(max_length=63, min_length=2, pattern="^[a-z][a-z0-9-]{0,61}[a-z0-9]$")
    ]
    """
    Nome único da service account dentro da Organization. Minúsculas, dígitos e hífen (slug). Imutável após a criação; é também o nome de usuário (username) da máquina no provedor de identidade.
    """
    description: Annotated[
        str | None, Field(max_length=256, min_length=1, pattern="^[^\\u0000-\\u001f\\u007f]+$")
    ] = None
    """
    Descrição legível do propósito da service account.
    """
    roles: Annotated[list[RoleName] | None, Field(max_length=32)] = None
    """
    Conjunto de Roles atribuídas à service account na Organization, sem repetição e em ordem alfabética. O Controller as expande em permissões atômicas (`observed.effectivePermissions`, decisão 0097).
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """
    keys: Annotated[list[ServiceAccountKeySpecification], Field(max_length=3, min_length=1)]
    """
    Chaves públicas pedidas pelo cliente (publicKey e expiresAt). No máximo 3, para rotação sem parada.
    """


class ServiceAccountUpdateRequest(ContractModel):
    """
    Corpo de PATCH /v1/ipm/serviceaccounts/{resourceId}. resourceVersion é a versão lida; pelo menos um campo deve ser alterado. keys substitui a lista inteira (adicionar ou remover chave é ler, alterar e enviar; mínimo 1). Mudar roles ou keys exige ipm.serviceaccount.bind; reconciliation é do operador.
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
    description: Annotated[
        str | None, Field(max_length=256, min_length=1, pattern="^[^\\u0000-\\u001f\\u007f]+$")
    ] = None
    """
    Descrição legível do propósito da service account.
    """
    roles: Annotated[list[RoleName] | None, Field(max_length=32)] = None
    """
    Conjunto de Roles atribuídas à service account na Organization, sem repetição e em ordem alfabética. O Controller as expande em permissões atômicas (`observed.effectivePermissions`, decisão 0097).
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """
    keys: Annotated[
        list[ServiceAccountKeySpecification] | None, Field(max_length=3, min_length=1)
    ] = None
    """
    Chaves públicas pedidas pelo cliente (publicKey e expiresAt). No máximo 3, para rotação sem parada.
    """
    reconciliation: Reconciliation | None = None


class ServiceAccountDesiredView(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    lifecycle: Lifecycle
    reconciliation: Reconciliation
    organization_id: Annotated[
        str,
        Field(
            alias="organizationId",
            max_length=128,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$",
        ),
    ]
    """
    Identidade estável e opaca do recurso (SCHEMA.md, Identificador do recurso).
    """
    name: Annotated[
        str, Field(max_length=63, min_length=2, pattern="^[a-z][a-z0-9-]{0,61}[a-z0-9]$")
    ]
    """
    Nome único da service account dentro da Organization. Minúsculas, dígitos e hífen (slug). Imutável após a criação; é também o nome de usuário (username) da máquina no provedor de identidade.
    """
    description: Annotated[
        str | None, Field(max_length=256, min_length=1, pattern="^[^\\u0000-\\u001f\\u007f]+$")
    ] = None
    """
    Descrição legível do propósito da service account.
    """
    roles: Annotated[list[RoleName] | None, Field(max_length=32)] = None
    """
    Conjunto de Roles atribuídas à service account na Organization, sem repetição e em ordem alfabética. O Controller as expande em permissões atômicas (`observed.effectivePermissions`, decisão 0097).
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """
    keys: Annotated[list[ServiceAccountDesiredKey], Field(max_length=3)]
    """
    Chaves pretendidas, já com o fingerprint calculado pelo Receiver. No máximo 3.
    """


class ServiceAccountObservedView(ContractModel):
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
    user_state: Annotated[UserState | None, Field(alias="userState")] = None
    access_token_type: Annotated[AccessTokenType | None, Field(alias="accessTokenType")] = None
    description: Annotated[
        str | None, Field(max_length=256, min_length=1, pattern="^[^\\u0000-\\u001f\\u007f]+$")
    ] = None
    """
    Descrição legível do propósito da service account.
    """
    permissions: Annotated[list[Permission] | None, Field(max_length=64)] = None
    """
    Conjunto de permissões, sem repetição e em ordem alfabética.
    """
    effective_permissions: Annotated[
        list[Permission] | None, Field(alias="effectivePermissions", max_length=64)
    ] = None
    """
    Permissões efetivas que o Controller calculou das `roles` da service account a partir do catálogo (decisão 0097) e que reconcilia no provedor. Não fazem parte do `desired`: mudar uma Role as recalcula sem nova geração.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """
    keys: Annotated[list[ServiceAccountObservedKey] | None, Field(max_length=8)] = None
    """
    Chaves lidas do provedor (e do metadado de mapeamento), sem material privado.
    """


class ServiceAccount(ContractModel):
    """
    Visão consolidada da service account da Organization exposta pelo Receiver (GET /v1/ipm/serviceaccounts/{resourceId}), legível pelo dono da Organization, por usuários e service accounts dela com ipm.serviceaccount.get e por operadores. Não expõe campos internos do SSOT nem material privado.
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
    Também o ID da máquina (machine user) no provedor de identidade e o userId do arquivo de chave.
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
    desired: Annotated[ServiceAccountDesiredView, Field(title="ServiceAccountDesiredView")]
    observed: Annotated[
        ServiceAccountObservedView | None, Field(title="ServiceAccountObservedView")
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


class ServiceAccountList(ContractModel):
    """
    Resposta de GET /v1/ipm/serviceaccounts?organizationId=: página ordenada por resourceId, somente das service accounts da Organization pedida, quando quem pede é o dono dela, um usuário ou service account dela com ipm.serviceaccount.list ou um operador. nextCursor ausente indica a última página.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    items: Annotated[list[ServiceAccount], Field(max_length=200)]
    next_cursor: Annotated[
        str | None,
        Field(alias="nextCursor", max_length=512, min_length=1, pattern="^[A-Za-z0-9_-]+$"),
    ] = None
    """
    Cursor opaco da próxima página.
    """


class GrantablePermission(StrEnum):
    """
    Catálogo das permissões que uma Organization pode delegar aos usuários dela (decisão 0081): o Project Grant de cada Organization tem exatamente estas, e o Receiver do User recusa as demais antes do loop. Fonte única, versionada com o código e igual em todos os ambientes; não há operador nem criação e remoção de Organization aqui. Este enum é só a semente inicial: o catálogo vivo vem de `grantable = true` em `ipm.permission` (decisão 0083). Ele deve listar exatamente as permissões `ipm.*` `grantable` da semente `0001-permission.sql` (verificado por teste em ipm/permission); mudar é mudar este enum, regerar os modelos do ipm/user, do ipm/organization e do ipm/role e implantar.
    """

    ipm_group_bind = "ipm.group.bind"
    ipm_group_create = "ipm.group.create"
    ipm_group_delete = "ipm.group.delete"
    ipm_group_get = "ipm.group.get"
    ipm_group_list = "ipm.group.list"
    ipm_group_update = "ipm.group.update"
    ipm_organization_get = "ipm.organization.get"
    ipm_organization_list = "ipm.organization.list"
    ipm_organization_update = "ipm.organization.update"
    ipm_role_bind = "ipm.role.bind"
    ipm_role_create = "ipm.role.create"
    ipm_role_delete = "ipm.role.delete"
    ipm_role_get = "ipm.role.get"
    ipm_role_list = "ipm.role.list"
    ipm_role_update = "ipm.role.update"
    ipm_serviceaccount_bind = "ipm.serviceaccount.bind"
    ipm_serviceaccount_create = "ipm.serviceaccount.create"
    ipm_serviceaccount_delete = "ipm.serviceaccount.delete"
    ipm_serviceaccount_get = "ipm.serviceaccount.get"
    ipm_serviceaccount_list = "ipm.serviceaccount.list"
    ipm_serviceaccount_update = "ipm.serviceaccount.update"
    ipm_user_bind = "ipm.user.bind"
    ipm_user_create = "ipm.user.create"
    ipm_user_delete = "ipm.user.delete"
    ipm_user_get = "ipm.user.get"
    ipm_user_list = "ipm.user.list"
    ipm_user_update = "ipm.user.update"


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


class ServiceAccountDesiredData(ContractModel):
    """
    data de desired da service account da Organization: estado pretendido e controle de reconciliação. Publicado somente pelo Manager. Só chaves públicas; nenhum segredo.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    lifecycle: Lifecycle
    reconciliation: Reconciliation
    organization_id: Annotated[
        str,
        Field(
            alias="organizationId",
            max_length=128,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$",
        ),
    ]
    """
    Organization dona da service account (o resourceId dela, também o ID da organização no provedor de identidade). Imutável.
    """
    name: Annotated[
        str, Field(max_length=63, min_length=2, pattern="^[a-z][a-z0-9-]{0,61}[a-z0-9]$")
    ]
    """
    Nome único da service account dentro da Organization. Minúsculas, dígitos e hífen (slug). Imutável após a criação; é também o nome de usuário (username) da máquina no provedor de identidade.
    """
    description: Annotated[
        str | None, Field(max_length=256, min_length=1, pattern="^[^\\u0000-\\u001f\\u007f]+$")
    ] = None
    """
    Descrição legível do propósito da service account.
    """
    roles: Annotated[list[RoleName] | None, Field(max_length=32)] = None
    """
    Roles atribuídas diretamente; expandidas pelo Controller em `observed.effectivePermissions` (decisão 0097).
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão. Na service account nasce true (decisão 0094); gravada como metadado no provedor (decisão 0074).
    """
    keys: Annotated[list[ServiceAccountDesiredKey], Field(max_length=3)]
    """
    Chaves públicas da service account (no máximo 3). Cada uma vira uma chave no provedor.
    """


class Keys(RootModel[list[ServiceAccountKeySpecification]]):
    """
    Chaves públicas pedidas pelo cliente (publicKey e expiresAt). No máximo 3, para rotação sem parada.
    """

    root: Annotated[list[ServiceAccountKeySpecification], Field(max_length=3)]
    """
    Chaves públicas pedidas pelo cliente (publicKey e expiresAt). No máximo 3, para rotação sem parada.
    """


class IpmServiceaccountContracts(
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
        | ServiceAccountDesiredData
        | ServiceAccountObservedData
        | ServiceAccountRequestedCreateData
        | ServiceAccountRequestedDeleteData
        | ServiceAccountRequestedUpdateData
        | ServiceAccountCreateRequest
        | ServiceAccountUpdateRequest
        | ServiceAccount
        | ServiceAccountList
        | GrantablePermission
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
        | ServiceAccountDesiredData
        | ServiceAccountObservedData
        | ServiceAccountRequestedCreateData
        | ServiceAccountRequestedDeleteData
        | ServiceAccountRequestedUpdateData
        | ServiceAccountCreateRequest
        | ServiceAccountUpdateRequest
        | ServiceAccount
        | ServiceAccountList
        | GrantablePermission,
        Field(title="IpmServiceaccountContracts"),
    ]
    """
    Índice dos contratos usados pelos componentes de serviceaccount do módulo ipm: entrada do gerador de modelos (decisão 0012). Não é um contrato. Todo contrato de common/ e de ipm/serviceaccount/ deve estar listado (verificado pelos testes de contrato). Uma definição que nenhum contrato referencia, mas que o código usa, entra pelo fragmento (#/$defs/...), como o catálogo grantablePermission (decisão 0081).
    """
