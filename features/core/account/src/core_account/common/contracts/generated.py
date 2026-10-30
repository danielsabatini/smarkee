# Gerado por datamodel-codegen a partir de schemas/ (decisão 0012). Não editar: altere o schema e regere.

from enum import StrEnum
from typing import Annotated, Any
from pydantic import AwareDatetime, ConfigDict, EmailStr, Field, RootModel
from datetime import timedelta
from core_account.common.contracts.base import ContractModel


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


class AccountState(StrEnum):
    """
    Estado do usuário no provedor de identidade. initial: aguardando a ativação (definição da senha).
    """

    initial = "initial"
    active = "active"
    inactive = "inactive"
    locked = "locked"


class PlatformPermission(RootModel[str]):
    root: Annotated[
        str,
        Field(
            max_length=128,
            min_length=5,
            pattern="^[a-z][a-z0-9]*\\.[a-z][a-z0-9]*\\.[a-z][a-z0-9]*$",
        ),
    ]
    """
    Permissão de ação do projeto da plataforma, no padrão <módulo>.<tipo>.<ação> (decisão 0028), por exemplo ipm.organization.create.
    """


class AccountCreateRequest(ContractModel):
    """
    Corpo de POST /v1/core/accounts (auto-cadastro, escrita anônima). A API atribui o resourceId e requestedBy = anonymous. Não há senha: a pessoa a define na página do provedor de identidade, pelo e-mail de ativação.
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


class AccountUpdateRequest(ContractModel):
    """
    Corpo de PATCH /v1/core/accounts/{resourceId}. resourceVersion é a versão lida; a única alteração possível é a proteção contra exclusão.
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
    deletion_protection: Annotated[bool, Field(alias="deletionProtection")]
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """


class AccountRegistrationResponse(ContractModel):
    """
    Resposta de POST /v1/core/accounts (auto-cadastro, escrita anônima): o pedido foi aceito, não aplicado. Uniforme: é a mesma exista ou não o e-mail, e por isso não traz o recurso nem o estado (RESOURCE-CONTROL-LOOP.md §6.1.2). O resourceId só identifica o cadastro para quem o fez; o e-mail de ativação é o canal de confirmação.
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
    registration_ticket: Annotated[
        str | None,
        Field(
            alias="registrationTicket",
            max_length=128,
            min_length=1,
            pattern="^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$",
        ),
    ] = None
    """
    Ticket temporário (UUIDv7) para acompanhar a ativação da conta sem autenticação.
    """
    ticket_expires_at: Annotated[AwareDatetime | None, Field(alias="ticketExpiresAt")] = None
    """
    Instante de expiração do ticket temporário de rastreamento.
    """


class AccountRegistrationStatus(ContractModel):
    """
    Status do processo de ativação da conta obtido através de um ticket temporário de rastreamento (UUIDv7). Seguro contra enumeração de e-mails e vazamento de dados pessoais.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    phase: Phase
    """
    Fase da conta no Resource Control Loop (Pending, Reconciling, Ready, Failed).
    """
    email_masked: Annotated[str, Field(alias="emailMasked", max_length=320)]
    """
    E-mail cadastrado mascarado para conferência do solicitante (ex: a***a@empresa.com).
    """
    email_dispatched: Annotated[bool, Field(alias="emailDispatched")]
    """
    Indica se o e-mail de ativação já foi emitido pelo provedor de identidade.
    """
    activated: bool
    """
    Indica se o usuário já completou a ativação (definição de senha e verificação de e-mail).
    """
    ticket_expires_at: Annotated[AwareDatetime, Field(alias="ticketExpiresAt")]
    """
    Instante em que o ticket temporário expira.
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


class AccountObservedData(ContractModel):
    """
    data de observed da Account: estado lido do provedor de identidade. Os campos estão presentes quando presence é present; com absent ou unknown, data é vazio.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    email_verified: Annotated[bool | None, Field(alias="emailVerified")] = None
    """
    Se o e-mail foi verificado (a ativação foi concluída).
    """
    account_state: Annotated[AccountState | None, Field(alias="accountState")] = None
    platform_access: Annotated[PlatformAccess | None, Field(alias="platformAccess")] = None
    """
    granted quando o usuário tem ao menos uma permissão de ação no projeto da plataforma (a lista está em platformPermissions).
    """
    platform_permissions: Annotated[
        list[PlatformPermission] | None, Field(alias="platformPermissions", max_length=64)
    ] = None
    """
    Permissões de ação que o usuário tem hoje no projeto da plataforma, lidas do provedor de identidade. platformAccess é granted quando há ao menos uma.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão lida do metadado `deletionProtection` do provedor de identidade (decisão 0074). Ausente quando o metadado não existe ou tem valor que não é true nem false: o Reconciler trata como divergência e o Executor o regrava.
    """
    last_resend_at: Annotated[AwareDatetime | None, Field(alias="lastResendAt")] = None
    """
    Instante em que o reenvio do e-mail de ativação foi executado pela última vez no provedor de identidade.
    """


class AccountDesiredView(ContractModel):
    model_config = ConfigDict(
        extra="forbid",
    )
    lifecycle: Lifecycle
    reconciliation: Reconciliation
    platform_access: Annotated[PlatformAccess, Field(alias="platformAccess")]
    platform_permissions: Annotated[
        list[PlatformPermission], Field(alias="platformPermissions", max_length=64)
    ]
    """
    Conjunto de permissões de ação, sem repetição e em ordem alfabética.
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
    E-mail do usuário; é também o nome de login. Imutável: a troca de e-mail é feita pelo fluxo do provedor de identidade.
    """


class AccountObservedView(ContractModel):
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
    account_state: Annotated[AccountState | None, Field(alias="accountState")] = None
    platform_access: Annotated[PlatformAccess | None, Field(alias="platformAccess")] = None
    platform_permissions: Annotated[
        list[PlatformPermission] | None, Field(alias="platformPermissions", max_length=64)
    ] = None
    """
    Conjunto de permissões de ação, sem repetição e em ordem alfabética.
    """
    deletion_protection: Annotated[bool | None, Field(alias="deletionProtection")] = None
    """
    Proteção contra exclusão, em desired. Todo recurso que pode ser apagado nasce com true; enquanto for true, o delete é recusado. Ausente vale como true. Desproteger é um update (decisão 0043).
    """


class Account(ContractModel):
    """
    Visão consolidada da Account exposta pela API (GET /v1/core/accounts/{resourceId}), legível pelo próprio usuário e por operadores. Não expõe campos internos do SSOT (failureCount, requestedBy).
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
    observed_generation: Annotated[
        int | None, Field(alias="observedGeneration", ge=1, le=9007199254740991)
    ] = None
    """
    Última geração do desired confirmada pela observação; ausente antes da primeira. A alteração terminou quando observedGeneration >= desiredGeneration e a phase é Ready ou Failed (decisão 0098).
    """
    phase: Phase
    conditions: Annotated[list[Condition], Field(max_length=32)]
    desired: Annotated[AccountDesiredView, Field(title="AccountDesiredView")]
    observed: Annotated[AccountObservedView | None, Field(title="AccountObservedView")] = None
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


class AccountDesiredData(ContractModel):
    """
    data de desired da Account: estado pretendido e controle de reconciliação. Publicado somente pelo Manager. Sem senha: a credencial é definida pelo usuário no provedor de identidade (decisão 0014). Com lifecycle absent, não carrega dados pessoais.
    """

    model_config = ConfigDict(
        extra="forbid",
    )
    lifecycle: Lifecycle
    reconciliation: Reconciliation
    platform_access: Annotated[PlatformAccess, Field(alias="platformAccess")]
    """
    granted: o usuário tem o conjunto de permissões de ação do usuário cadastrado no projeto da plataforma. Atribuído pelo Manager na criação.
    """
    platform_permissions: Annotated[
        list[PlatformPermission], Field(alias="platformPermissions", max_length=64)
    ]
    """
    Permissões de ação que o usuário deve ter no projeto da plataforma. Atribuído pelo Manager na criação, a partir da sua configuração; vazio quando platformAccess é revoked (decisão 0025).
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
    E-mail do usuário; é também o nome de login. Imutável: a troca de e-mail é feita pelo fluxo do provedor de identidade.
    """
    resend_requested_at: Annotated[AwareDatetime | None, Field(alias="resendRequestedAt")] = None
    """
    Instante em que o reenvio do e-mail de ativação foi solicitado.
    """


class CoreAccountContracts(
    RootModel[
        MessageEnvelope
        | Condition
        | ActionData
        | CompletedData
        | FailedData
        | UpdatedData
        | ApiError
        | AccountDesiredData
        | AccountObservedData
        | AccountCreateRequest
        | AccountUpdateRequest
        | AccountRegistrationResponse
        | AccountRegistrationStatus
        | Account
    ]
):
    root: Annotated[
        MessageEnvelope
        | Condition
        | ActionData
        | CompletedData
        | FailedData
        | UpdatedData
        | ApiError
        | AccountDesiredData
        | AccountObservedData
        | AccountCreateRequest
        | AccountUpdateRequest
        | AccountRegistrationResponse
        | AccountRegistrationStatus
        | Account,
        Field(title="CoreAccountContracts"),
    ]
    """
    Índice dos contratos usados pelos componentes de account do módulo core: entrada do gerador de modelos (decisão 0012). Não é um contrato. Todo contrato de common/ e de core/account/ deve estar listado (verificado pelos testes de contrato).
    """
