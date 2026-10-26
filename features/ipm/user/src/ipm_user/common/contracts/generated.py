# Gerado por datamodel-codegen a partir de schemas/ (decisão 0012). Não editar: altere o schema e regere.

from enum import StrEnum
from typing import Annotated, Any
from pydantic import AwareDatetime, ConfigDict, EmailStr, Field, RootModel
from datetime import timedelta
from ipm_user.common.contracts.base import ContractModel


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


class UserState(StrEnum):
    """
    Estado do usuário no provedor de identidade. initial: aguardando a ativação (definição da senha pelo e-mail).
    """

    initial = "initial"
    active = "active"
    inactive = "inactive"
    locked = "locked"


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
    Permissão da plataforma no padrão <módulo>.<tipo>.<ação> (decisão 0028), por exemplo ipm.user.create. Só são aceitas as permissões do Project Grant da Organization (decisão 0077).
    """


class RoleName(RootModel[str]):
    root: Annotated[
        str, Field(max_length=128, min_length=5, pattern="^[a-z][a-z0-9]*\\.[a-z][a-zA-Z0-9]*$")
    ]
    """
    Identificador semântico da Role composta no padrão Google Cloud IAM (<módulo>.<tipo><Admin|Viewer>, decisão 0083), por exemplo ipm.userAdmin ou ipm.organizationViewer.
    """


class GroupName(RootModel[str]):
    root: Annotated[
        str, Field(max_length=63, min_length=2, pattern="^[a-z][a-z0-9-]{0,61}[a-z0-9]$")
    ]
    """
    Nome único de um grupo de usuários na Organization (slug curto, decisão 0088).
    """


class UserCreateSpecification(ContractModel):
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
    E-mail do usuário; é também o nome de login dele na Organization. Imutável: a troca de e-mail é feita pelo fluxo do provedor de identidade.
    """
    roles: Annotated[list[RoleName] | None, Field(max_length=32)] = None
    """
    Conjunto de Roles compostas atribuídas ao usuário na Organization, sem repetição e em ordem alfabética (decisão 0083). São expandidas pelo Manager em permissões atômicas no desired.
    """
    groups: Annotated[list[GroupName] | None, Field(max_length=32)] = None
    """
    Grupos de usuários da Organization aos quais o usuário pertence (decisão 0088). Suas roles são expandidas pelo Manager em permissions no desired.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """


class UserRequestedCreateData(ContractModel):
    """
    data de requested com operation create. Publicado somente pelo Receiver, depois de conferir a Organization, o escopo de quem pede, a cota e as permissões contra o catálogo do Grant (decisão 0077). Sem senha.
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
    organization_quota_limit: Annotated[
        int | None, Field(alias="organizationQuotaLimit", ge=1, le=1000)
    ] = None
    """
    Limite de usuários da Organization, definido pelo Receiver (ausente para operadores: sem cota). O Manager aplica o limite na mesma unidade atômica do pedido, sob trava por Organization (decisão 0077).
    """


class UserRequestedDeleteData(ContractModel):
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


class UserUpdateSpecification(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    roles: Annotated[list[RoleName] | None, Field(max_length=32)] = None
    """
    Conjunto de Roles compostas atribuídas ao usuário na Organization, sem repetição e em ordem alfabética (decisão 0083). São expandidas pelo Manager em permissões atômicas no desired.
    """
    groups: Annotated[list[GroupName] | None, Field(max_length=32)] = None
    """
    Grupos de usuários da Organization aos quais o usuário pertence (decisão 0088). Suas roles são expandidas pelo Manager em permissions no desired.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """


class UserRequestedUpdateData(ContractModel):
    """
    data de requested com operation update. Traz as permissões, a proteção contra exclusão, a mudança do controle de reconciliação, ou uma combinação delas. Publicado somente pelo Receiver.
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
        UserUpdateSpecification | None, Field(title="UserUpdateSpecification")
    ] = None
    reconciliation: Reconciliation | None = None
    """
    Muda só o controle de reconciliação; não incrementa desiredGeneration.
    """


class UserCreateRequest(ContractModel):
    """
    Corpo de POST /v1/ipm/users. O Receiver atribui resourceId, operationId, requestDigest e requestedBy. Não há senha: a pessoa a define na página do provedor de identidade, pelo e-mail de ativação. roles ausente equivale a nenhuma; deletionProtection ausente equivale a false (decisão 0077, 0085).
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
    E-mail do usuário; é também o nome de login dele na Organization. Imutável: a troca de e-mail é feita pelo fluxo do provedor de identidade.
    """
    roles: Annotated[list[RoleName] | None, Field(max_length=32)] = None
    """
    Conjunto de Roles compostas atribuídas ao usuário na Organization, sem repetição e em ordem alfabética (decisão 0083). São expandidas pelo Manager em permissões atômicas no desired.
    """
    groups: Annotated[list[GroupName] | None, Field(max_length=32)] = None
    """
    Grupos de usuários da Organization aos quais o usuário pertence (decisão 0088). Suas roles são expandidas pelo Manager em permissions no desired.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """


class UserUpdateRequest(ContractModel):
    """
    Corpo de PATCH /v1/ipm/users/{resourceId}. resourceVersion é a versão lida; pelo menos um campo deve ser alterado. Mudar roles exige ipm.user.bind (decisão 0077, 0085); reconciliation é do operador.
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
    roles: Annotated[list[RoleName] | None, Field(max_length=32)] = None
    """
    Conjunto de Roles compostas atribuídas ao usuário na Organization, sem repetição e em ordem alfabética (decisão 0083). São expandidas pelo Manager em permissões atômicas no desired.
    """
    groups: Annotated[list[GroupName] | None, Field(max_length=32)] = None
    """
    Grupos de usuários da Organization aos quais o usuário pertence (decisão 0088). Suas roles são expandidas pelo Manager em permissions no desired.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """
    reconciliation: Reconciliation | None = None


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


class UserObservedData(ContractModel):
    """
    data de observed do usuário da Organization: estado lido do provedor de identidade. Os campos estão presentes quando presence é present; com absent ou unknown, data é vazio.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    email_verified: Annotated[bool | None, Field(alias="emailVerified")] = None
    """
    Se o e-mail foi verificado (a ativação foi concluída).
    """
    user_state: Annotated[UserState | None, Field(alias="userState")] = None
    permissions: Annotated[list[Permission] | None, Field(max_length=64)] = None
    """
    Permissões que o usuário tem hoje na Organization, lidas das autorizações dele no provedor de identidade.
    """
    groups: Annotated[list[GroupName] | None, Field(max_length=32)] = None
    """
    Grupos de usuários aos quais o usuário pertence lidos do metadado `groups` no provedor de identidade (decisão 0088).
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão lida do metadado `deletionProtection` do usuário (decisão 0074). Ausente quando o metadado não existe ou tem valor que não é true nem false: o Reconciler trata como divergência e o Executor o regrava.
    """


class UserDesiredView(ContractModel):
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
    permissions: Annotated[list[Permission], Field(max_length=64)]
    """
    Conjunto de permissões, sem repetição e em ordem alfabética.
    """
    roles: Annotated[list[RoleName] | None, Field(max_length=32)] = None
    """
    Conjunto de Roles compostas atribuídas ao usuário na Organization, sem repetição e em ordem alfabética (decisão 0083). São expandidas pelo Manager em permissões atômicas no desired.
    """
    groups: Annotated[list[GroupName] | None, Field(max_length=32)] = None
    """
    Grupos de usuários da Organization aos quais o usuário pertence (decisão 0088). Suas roles são expandidas pelo Manager em permissions no desired.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
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
    E-mail do usuário; é também o nome de login dele na Organization. Imutável: a troca de e-mail é feita pelo fluxo do provedor de identidade.
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
    permissions: Annotated[list[Permission] | None, Field(max_length=64)] = None
    """
    Conjunto de permissões, sem repetição e em ordem alfabética.
    """
    groups: Annotated[list[GroupName] | None, Field(max_length=32)] = None
    """
    Grupos de usuários da Organization aos quais o usuário pertence (decisão 0088). Suas roles são expandidas pelo Manager em permissions no desired.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """


class User(ContractModel):
    """
    Visão consolidada do usuário da Organization exposta pelo Receiver (GET /v1/ipm/users/{resourceId}), legível pelo dono da Organization, por usuários dela com ipm.user.get e por operadores. Não expõe campos internos do SSOT (failureCount, requestedBy).
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
    Também o ID do usuário no provedor de identidade.
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


class UserList(ContractModel):
    """
    Resposta de GET /v1/ipm/users?organizationId=: página ordenada por resourceId, somente dos usuários da Organization pedida, quando quem pede é o dono dela, um usuário dela com ipm.user.list ou um operador. nextCursor ausente indica a última página.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    items: Annotated[list[User], Field(max_length=200)]
    next_cursor: Annotated[
        str | None,
        Field(alias="nextCursor", max_length=512, min_length=1, pattern="^[A-Za-z0-9_-]+$"),
    ] = None
    """
    Cursor opaco da próxima página.
    """


class UserDesiredData(ContractModel):
    """
    data de desired do usuário da Organization: estado pretendido e controle de reconciliação. Publicado somente pelo Manager. Sem senha: a credencial é definida pelo usuário no provedor de identidade. Com lifecycle absent, não carrega dados pessoais.
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
    Organization onde o usuário vive (o resourceId da Organization, também o ID da organização no provedor de identidade). Imutável.
    """
    permissions: Annotated[list[Permission], Field(max_length=64)]
    """
    Permissões da plataforma que o usuário deve ter na Organization, por autorização no Project Grant dela (decisão 0077). Inclui as permissões diretas e as expandidas a partir de roles (decisão 0083).
    """
    roles: Annotated[list[RoleName] | None, Field(max_length=32)] = None
    """
    Roles compostas atribuídas diretamente ao usuário na Organization (decisão 0083). São expandidas pelo Manager em permissions e não criam objetos no provedor de identidade.
    """
    groups: Annotated[list[GroupName] | None, Field(max_length=32)] = None
    """
    Grupos de usuários aos quais o usuário pertence na Organization (decisão 0088). Suas roles são expandidas transitivamente pelo Manager em permissions e o conjunto é gravado em metadados no provedor.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão. No usuário da Organization nasce false (exceção à decisão 0043, registrada na 0077); gravada como metadado no provedor (decisão 0074).
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
    E-mail do usuário; é também o nome de login dele na Organization. Imutável: a troca de e-mail é feita pelo fluxo do provedor de identidade.
    """


class IpmUserContracts(
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
        | UserDesiredData
        | UserObservedData
        | UserRequestedCreateData
        | UserRequestedDeleteData
        | UserRequestedUpdateData
        | UserCreateRequest
        | UserUpdateRequest
        | User
        | UserList
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
        | UserDesiredData
        | UserObservedData
        | UserRequestedCreateData
        | UserRequestedDeleteData
        | UserRequestedUpdateData
        | UserCreateRequest
        | UserUpdateRequest
        | User
        | UserList
        | GrantablePermission,
        Field(title="IpmUserContracts"),
    ]
    """
    Índice dos contratos usados pelos componentes de user do módulo ipm: entrada do gerador de modelos (decisão 0012). Não é um contrato. Todo contrato de common/ e de ipm/user/ deve estar listado (verificado pelos testes de contrato). Uma definição que nenhum contrato referencia, mas que o código usa, entra pelo fragmento (#/$defs/...), como o catálogo grantablePermission (decisão 0081).
    """
