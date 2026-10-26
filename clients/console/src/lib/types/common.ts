/**
 * Primitivas comuns e tipos de controle do loop de recursos da plataforma Smarkee.
 * Espelha rigorosamente schemas/common/definitions.v1.schema.json,
 * schemas/common/condition.v1.schema.json, schemas/common/operation.v1.schema.json
 * e schemas/common/api-accepted-response.v1.schema.json.
 */

export type ResourcePhase =
	| 'Pending'
	| 'Reconciling'
	| 'Ready'
	| 'Failed'
	| 'Deleting'
	| 'Degraded';

export type Lifecycle = 'present' | 'absent';

export type Reconciliation = 'active' | 'suspended';

export type Presence = 'present' | 'absent' | 'unknown';

export type PlatformAccess = 'granted' | 'revoked';

export type ConditionStatus = 'True' | 'False' | 'Unknown';

export interface Condition {
	type: string;
	status: ConditionStatus;
	reason: string;
	message?: string;
	observedGeneration?: number;
	lastTransitionAt: string;
}

export interface RequestAccepted {
	resourceId: string;
	operationId: string;
}

export type OperationType = 'create' | 'update' | 'delete';

export type OperationStatus =
	| 'accepted'
	| 'in_progress'
	| 'completed'
	| 'failed'
	| 'rejected'
	| 'superseded';

export type OperationStatusReason = 'conflict' | 'validation' | 'not_found' | 'protected';

export interface Operation {
	operationId: string;
	operationType: OperationType;
	module: string;
	resourceType: string;
	resourceId: string;
	desiredGeneration?: number;
	operationStatus: OperationStatus;
	operationStatusReason?: OperationStatusReason;
	createdAt: string;
	updatedAt: string;
	completedAt?: string;
}

/**
 * Padrão oficial de identificadores opacos e de recursos (definitions.v1.schema.json).
 * Impede ataques de path traversal antes de interpolar caminhos de URL HTTP.
 */
export const OPAQUE_IDENTIFIER_PATTERN = /^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$/;

/**
 * Padrão oficial de nomes de Organization no provedor de identidade (ipm/organization/definitions.v1.schema.json).
 */
export const ORGANIZATION_NAME_PATTERN = /^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?$/;

/**
 * Valida se o identificador fornecido obedece estritamente ao contrato de identificador opaco/resourceId.
 */
export function isValidIdentifier(value: string): boolean {
	return (
		typeof value === 'string' &&
		value.length >= 1 &&
		value.length <= 128 &&
		OPAQUE_IDENTIFIER_PATTERN.test(value)
	);
}

/**
 * Garante que um identificador seja seguro para interpolação em caminhos HTTP, lançando erro explícito caso contrário.
 */
export function validateIdentifier(value: string, label = 'resourceId'): string {
	if (!isValidIdentifier(value)) {
		throw new Error(
			`Identificador inválido para ${label}: deve corresponder ao padrão oficial ^[a-z0-9]([a-z0-9-]{0,126}[a-z0-9])?$.`
		);
	}
	return value;
}
