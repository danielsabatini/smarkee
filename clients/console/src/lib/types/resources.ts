/**
 * Contratos de recursos da API pública da plataforma Smarkee.
 * Espelha rigorosamente os JSON Schemas oficiais em:
 * - schemas/core/account/resource.v1.schema.json
 * - schemas/ipm/organization/resource.v1.schema.json
 * - schemas/ipm/user/resource.v1.schema.json
 * - schemas/sum/service/resource.v1.schema.json
 */

import type {
	Condition,
	Lifecycle,
	PlatformAccess,
	Presence,
	Reconciliation,
	ResourcePhase
} from './common';

export type AccountState = 'initial' | 'active' | 'inactive' | 'locked';

export interface AccountDesiredView {
	lifecycle: Lifecycle;
	reconciliation: Reconciliation;
	platformAccess: PlatformAccess;
	platformPermissions: string[];
	deletionProtection?: boolean;
	givenName?: string;
	familyName?: string;
	email?: string;
}

export interface AccountObservedView {
	presence: Presence;
	observedAt: string;
	emailVerified?: boolean;
	accountState?: AccountState;
	platformAccess?: PlatformAccess;
	platformPermissions?: string[];
	deletionProtection?: boolean;
}

export interface AccountResource {
	resourceId: string;
	resourceVersion: string;
	desiredGeneration: number;
	phase: ResourcePhase;
	conditions: Condition[];
	desired: AccountDesiredView;
	observed?: AccountObservedView;
	createdAt: string;
	updatedAt: string;
}

export type OrganizationState = 'active' | 'inactive';

export interface OrganizationDesiredView {
	lifecycle: Lifecycle;
	reconciliation: Reconciliation;
	name: string;
	platformAccess: PlatformAccess;
	deletionProtection?: boolean;
}

export interface OrganizationObservedView {
	presence: Presence;
	observedAt: string;
	name?: string;
	platformAccess?: PlatformAccess;
	organizationState?: OrganizationState;
	deletionProtection?: boolean;
}

export interface OrganizationResource {
	resourceId: string;
	resourceVersion: string;
	desiredGeneration: number;
	phase: ResourcePhase;
	conditions: Condition[];
	desired: OrganizationDesiredView;
	observed?: OrganizationObservedView;
	createdAt: string;
	updatedAt: string;
}

export interface OrganizationListResponse {
	items: OrganizationResource[];
	nextCursor?: string;
}

export type GrantablePermission =
	| 'ipm.organization.get'
	| 'ipm.organization.list'
	| 'ipm.organization.update'
	| 'ipm.user.bind'
	| 'ipm.user.create'
	| 'ipm.user.delete'
	| 'ipm.user.get'
	| 'ipm.user.list'
	| 'ipm.user.update';

export type GrantableRole = GrantablePermission;

export type UserState = 'initial' | 'active' | 'inactive' | 'locked';

export interface OrganizationUserDesiredView {
	lifecycle: Lifecycle;
	reconciliation: Reconciliation;
	organizationId: string;
	/** Nomes de role (ex.: ipm.userAdmin); as permissões efetivas vão no observed (0097). */
	roles: string[];
	deletionProtection?: boolean;
	givenName?: string;
	familyName?: string;
	email?: string;
}

export interface OrganizationUserObservedView {
	presence: Presence;
	observedAt: string;
	emailVerified?: boolean;
	userState?: UserState;
	permissions?: GrantablePermission[];
	/** Calculadas pelo Controller a partir das roles (decisão 0097). */
	effectivePermissions?: GrantablePermission[];
	deletionProtection?: boolean;
}

export interface OrganizationUserResource {
	resourceId: string;
	resourceVersion: string;
	desiredGeneration: number;
	phase: ResourcePhase;
	conditions: Condition[];
	desired: OrganizationUserDesiredView;
	observed?: OrganizationUserObservedView;
	createdAt: string;
	updatedAt: string;
}

export interface OrganizationUserListResponse {
	items: OrganizationUserResource[];
	nextCursor?: string;
}

export interface ServiceDesiredData {
	lifecycle: Lifecycle;
	reconciliation: Reconciliation;
	ownerAccountId: string;
	service: string;
	servicePermissions: string[];
	managedPermissions?: string[];
}

export interface ServiceObservedData {
	servicePermissions?: string[];
}

export interface ServiceLinkResource {
	resourceId: string;
	resourceVersion: string;
	desiredGeneration: number;
	phase: ResourcePhase;
	conditions: Condition[];
	desired: ServiceDesiredData;
	observed?: ServiceObservedData;
	createdAt: string;
	updatedAt: string;
}

export interface ServiceListResponse {
	items: ServiceLinkResource[];
}
