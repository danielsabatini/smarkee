/**
 * Modelos específicos de UI e contexto de sessão do Smarkee Console.
 * Conforme docs/console/CONSOLE.md §7.1 e §9.
 */

import type { Operation, ResourcePhase } from './common';

export type ModuleCode = 'IPM' | 'SUM' | 'AEM' | 'ODM';

export interface ServiceCatalogItem {
	code: ModuleCode;
	serviceKey: string;
	name: string;
	shortName: string;
	description: string;
	href: string;
	isDemo: boolean;
	rolesGranted: string[];
}

export interface ResourceSummary {
	resourceId: string;
	displayName: string;
	subtitle?: string;
	module: string;
	resourceType: 'ipm.organization' | 'ipm.user' | 'sum.service' | 'core.account' | string;
	typeLabel: string;
	phase: ResourcePhase;
	updatedAt: string;
	href: string;
	isDemo?: boolean;
	organizationId?: string;
}

export type NotificationSeverity = 'info' | 'success' | 'warning' | 'error';

export interface ConsoleNotification {
	id: string;
	title: string;
	description: string;
	severity: NotificationSeverity;
	createdAt: string;
	read: boolean;
	organizationId?: string;
	relatedOperationId?: string;
	href?: string;
}

export interface AuthSessionConfig {
	issuer: string;
	clientId: string;
	redirectUri: string;
	scopes: string[];
}

export interface UserContext {
	accountId: string;
	displayName: string;
	emailMasked: string;
	roles: string[];
	activeOrganizationId: string | null;
	authConfig: AuthSessionConfig;
}

export interface OrganizationMetadataDemo {
	displayName: string;
	planDemo: string;
	primaryRegionDemo: string;
	memberCount: number;
}

export interface OperationTitleInfo {
	operation: Operation;
	title: string;
	subtitle: string;
	organizationId?: string;
}
