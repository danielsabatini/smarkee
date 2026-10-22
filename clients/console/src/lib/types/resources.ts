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
	platformRoles: string[];
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
	platformRoles?: string[];
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

export type GrantableRole =
	| 'ipm.organization.get'
	| 'ipm.organization.list'
	| 'ipm.organization.update'
	| 'ipm.user.bind'
	| 'ipm.user.create'
	| 'ipm.user.delete'
	| 'ipm.user.get'
	| 'ipm.user.list'
	| 'ipm.user.update';

export type UserState = 'initial' | 'active' | 'inactive' | 'locked';

export interface OrganizationUserDesiredView {
	lifecycle: Lifecycle;
	reconciliation: Reconciliation;
	organizationId: string;
	roles: GrantableRole[];
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
	roles?: GrantableRole[];
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
	serviceRoles: string[];
	managedRoles?: string[];
}

export interface ServiceObservedData {
	serviceRoles?: string[];
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
