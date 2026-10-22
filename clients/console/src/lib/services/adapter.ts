/**
 * Porta de serviço (contrato abstrato) para consumo de dados pelo Smarkee Console.
 * Desacopla componentes Svelte de chamadas HTTP ou simulações em memória.
 */

import type { Operation, RequestAccepted } from '../types/common';
import type {
	ConsoleNotification,
	OperationTitleInfo,
	OrganizationMetadataDemo,
	ResourceSummary,
	ServiceCatalogItem,
	UserContext
} from '../types/console';
import type {
	AccountResource,
	GrantableRole,
	OrganizationResource,
	OrganizationUserResource,
	ServiceLinkResource
} from '../types/resources';

export interface CreateOrganizationInput {
	name: string;
	displayName?: string;
	deletionProtection?: boolean;
}

export interface UpdateOrganizationInput {
	resourceId: string;
	name?: string;
	displayName?: string;
	deletionProtection?: boolean;
}

export interface CreateUserInput {
	organizationId: string;
	givenName: string;
	familyName: string;
	email: string;
	roles: GrantableRole[];
	deletionProtection?: boolean;
}

export interface UpdateUserInput {
	resourceId: string;
	roles?: GrantableRole[];
	deletionProtection?: boolean;
}

export interface UpdateAccountInput {
	resourceId: string;
	deletionProtection?: boolean;
}

export interface EnableServiceInput {
	service: string;
}

export interface ConsoleDataAdapter {
	getUserContext(): Promise<UserContext>;
	getAccount(resourceId: string): Promise<AccountResource>;
	listOrganizations(): Promise<OrganizationResource[]>;
	getOrganization(resourceId: string): Promise<OrganizationResource>;
	getOrganizationMetadataDemo(resourceId: string): OrganizationMetadataDemo;
	listUsers(organizationId: string): Promise<OrganizationUserResource[]>;
	listServices(): Promise<ServiceLinkResource[]>;
	getServiceCatalog(): ServiceCatalogItem[];
	listRecentResources(organizationId: string): Promise<ResourceSummary[]>;
	listOperations(organizationId?: string): Promise<OperationTitleInfo[]>;
	getOperation(operationId: string): Promise<Operation | null>;
	listNotifications(organizationId?: string): Promise<ConsoleNotification[]>;
	markNotificationAsRead(notificationId: string): Promise<void>;
	markAllNotificationsAsRead(organizationId?: string): Promise<void>;

	createOrganization(input: CreateOrganizationInput): Promise<RequestAccepted>;
	updateOrganization(input: UpdateOrganizationInput): Promise<RequestAccepted>;
	deleteOrganization(resourceId: string): Promise<RequestAccepted>;

	createUser(input: CreateUserInput): Promise<RequestAccepted>;
	updateUser(input: UpdateUserInput): Promise<RequestAccepted>;
	deleteUser(resourceId: string): Promise<RequestAccepted>;

	updateAccount(input: UpdateAccountInput): Promise<RequestAccepted>;
	deleteAccount(resourceId: string): Promise<RequestAccepted>;

	enableService(input: EnableServiceInput): Promise<RequestAccepted>;
	disableService(resourceId: string): Promise<RequestAccepted>;
}
