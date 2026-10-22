/**
 * Adaptador simulado (MockDataAdapter) do Smarkee Console.
 * Todos os recursos retornados aderem estritamente aos JSON Schemas oficiais em schemas/
 * e são verificados por testes de contrato com ajv.
 */

import { PLATFORM_SERVICE_CATALOG } from '../config/navigation';
import {
	ORGANIZATION_NAME_PATTERN,
	validateIdentifier,
	type Operation,
	type RequestAccepted
} from '../types/common';
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
	OrganizationResource,
	OrganizationUserResource,
	ServiceLinkResource
} from '../types/resources';
import type {
	ConsoleDataAdapter,
	CreateOrganizationInput,
	UpdateOrganizationInput,
	CreateUserInput,
	UpdateUserInput,
	UpdateAccountInput,
	EnableServiceInput
} from './adapter';

export interface MockDataAdapterOptions {
	transitionDelayMs?: number;
}

const DEFAULT_ACCOUNT_ID = '0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e';
const ORG_ACME_ID = '0199c8a4-8a01-7b01-9c01-1a2b3c4d5e01';
const ORG_GLOBEX_ID = '0199c8a4-8a02-7b02-9c02-1a2b3c4d5e02';
const ORG_INITECH_ID = '0199c8a4-8a03-7b03-9c03-1a2b3c4d5e03';

export class MockDataAdapter implements ConsoleDataAdapter {
	private readonly transitionDelayMs: number;
	private counter = 100;
	private account: AccountResource;
	private organizations: OrganizationResource[];
	private organizationDemoMeta: Record<string, OrganizationMetadataDemo>;
	private usersByOrganization: Record<string, OrganizationUserResource[]>;
	private services: ServiceLinkResource[];
	private operations: OperationTitleInfo[];
	private notifications: ConsoleNotification[];

	constructor(options: MockDataAdapterOptions = {}) {
		this.transitionDelayMs = options.transitionDelayMs ?? 1200;

		this.account = {
			resourceId: DEFAULT_ACCOUNT_ID,
			resourceVersion: '4',
			desiredGeneration: 1,
			phase: 'Ready',
			conditions: [
				{
					type: 'Ready',
					status: 'True',
					reason: 'Reconciled',
					message: 'Account exists in the identity provider with platform access.',
					observedGeneration: 1,
					lastTransitionAt: '2026-10-21T10:00:05Z'
				}
			],
			desired: {
				lifecycle: 'present',
				reconciliation: 'active',
				platformAccess: 'granted',
				platformRoles: ['core.account.delete', 'core.account.get', 'core.account.update'],
				deletionProtection: true,
				givenName: 'Daniel',
				familyName: 'Freitas',
				email: 'daniel.freitas@smarkee.example.com'
			},
			observed: {
				presence: 'present',
				observedAt: '2026-10-21T10:00:04Z',
				emailVerified: true,
				accountState: 'active',
				platformAccess: 'granted',
				platformRoles: ['core.account.delete', 'core.account.get', 'core.account.update'],
				deletionProtection: true
			},
			createdAt: '2026-10-15T09:00:00Z',
			updatedAt: '2026-10-21T10:00:05Z'
		};

		this.organizations = [
			{
				resourceId: ORG_ACME_ID,
				resourceVersion: '7',
				desiredGeneration: 2,
				phase: 'Ready',
				conditions: [
					{
						type: 'Ready',
						status: 'True',
						reason: 'Reconciled',
						message: 'Organization exists in the identity provider with platform access.',
						observedGeneration: 2,
						lastTransitionAt: '2026-10-21T11:30:00Z'
					}
				],
				desired: {
					lifecycle: 'present',
					reconciliation: 'active',
					name: 'acme-corporation',
					platformAccess: 'granted',
					deletionProtection: true
				},
				observed: {
					presence: 'present',
					observedAt: '2026-10-21T11:29:58Z',
					name: 'acme-corporation',
					platformAccess: 'granted',
					organizationState: 'active',
					deletionProtection: true
				},
				createdAt: '2026-10-16T08:00:00Z',
				updatedAt: '2026-10-21T11:30:00Z'
			},
			{
				resourceId: ORG_GLOBEX_ID,
				resourceVersion: '3',
				desiredGeneration: 1,
				phase: 'Reconciling',
				conditions: [
					{
						type: 'Ready',
						status: 'False',
						reason: 'Reconciling',
						message: 'Applying Project Grant and organization administrator roles.',
						observedGeneration: 1,
						lastTransitionAt: '2026-10-21T13:45:00Z'
					},
					{
						type: 'Progressing',
						status: 'True',
						reason: 'ActionDispatched',
						message: 'Executor is configuring organization grant roles in Zitadel.',
						observedGeneration: 1,
						lastTransitionAt: '2026-10-21T13:45:00Z'
					}
				],
				desired: {
					lifecycle: 'present',
					reconciliation: 'active',
					name: 'globex-labs',
					platformAccess: 'granted',
					deletionProtection: true
				},
				observed: {
					presence: 'present',
					observedAt: '2026-10-21T13:44:50Z',
					name: 'globex-labs',
					platformAccess: 'granted',
					organizationState: 'active',
					deletionProtection: true
				},
				createdAt: '2026-10-20T15:10:00Z',
				updatedAt: '2026-10-21T13:45:00Z'
			},
			{
				resourceId: ORG_INITECH_ID,
				resourceVersion: '5',
				desiredGeneration: 2,
				phase: 'Ready',
				conditions: [
					{
						type: 'Ready',
						status: 'True',
						reason: 'Reconciled',
						message: 'Organization exists in the identity provider with platform access.',
						observedGeneration: 2,
						lastTransitionAt: '2026-10-19T17:20:00Z'
					}
				],
				desired: {
					lifecycle: 'present',
					reconciliation: 'active',
					name: 'initech-cloud',
					platformAccess: 'granted',
					deletionProtection: false
				},
				observed: {
					presence: 'present',
					observedAt: '2026-10-19T17:19:55Z',
					name: 'initech-cloud',
					platformAccess: 'granted',
					organizationState: 'active',
					deletionProtection: false
				},
				createdAt: '2026-10-18T11:00:00Z',
				updatedAt: '2026-10-19T17:20:00Z'
			}
		];

		this.organizationDemoMeta = {
			[ORG_ACME_ID]: {
				displayName: 'Acme Corporation',
				planDemo: 'Enterprise',
				primaryRegionDemo: 'us-east-1',
				memberCount: 12
			},
			[ORG_GLOBEX_ID]: {
				displayName: 'Globex Labs',
				planDemo: 'Business',
				primaryRegionDemo: 'sa-east-1',
				memberCount: 5
			},
			[ORG_INITECH_ID]: {
				displayName: 'Initech Cloud',
				planDemo: 'Standard',
				primaryRegionDemo: 'us-west-2',
				memberCount: 3
			}
		};

		this.usersByOrganization = {
			[ORG_ACME_ID]: [
				{
					resourceId: '0199c8c1-1d2e-7f3a-8b4c-5d6e7f8a9b01',
					resourceVersion: '3',
					desiredGeneration: 1,
					phase: 'Ready',
					conditions: [
						{
							type: 'Ready',
							status: 'True',
							reason: 'Reconciled',
							message: 'User exists in the organization with the expected roles.',
							observedGeneration: 1,
							lastTransitionAt: '2026-10-21T12:00:05Z'
						}
					],
					desired: {
						lifecycle: 'present',
						reconciliation: 'active',
						organizationId: ORG_ACME_ID,
						roles: [
							'ipm.organization.get',
							'ipm.organization.list',
							'ipm.user.create',
							'ipm.user.get',
							'ipm.user.list',
							'ipm.user.update'
						],
						deletionProtection: true,
						givenName: 'Beatriz',
						familyName: 'Lima',
						email: 'beatriz.lima@acme.example.com'
					},
					observed: {
						presence: 'present',
						observedAt: '2026-10-21T12:00:04Z',
						emailVerified: true,
						userState: 'active',
						roles: [
							'ipm.organization.get',
							'ipm.organization.list',
							'ipm.user.create',
							'ipm.user.get',
							'ipm.user.list',
							'ipm.user.update'
						],
						deletionProtection: true
					},
					createdAt: '2026-10-17T14:00:00Z',
					updatedAt: '2026-10-21T12:00:05Z'
				},
				{
					resourceId: '0199c8c1-1d2e-7f3a-8b4c-5d6e7f8a9b02',
					resourceVersion: '2',
					desiredGeneration: 1,
					phase: 'Reconciling',
					conditions: [
						{
							type: 'Ready',
							status: 'False',
							reason: 'Reconciling',
							message: 'Provisioning user grant in organization.',
							observedGeneration: 1,
							lastTransitionAt: '2026-10-21T13:50:00Z'
						}
					],
					desired: {
						lifecycle: 'present',
						reconciliation: 'active',
						organizationId: ORG_ACME_ID,
						roles: ['ipm.organization.get', 'ipm.user.get', 'ipm.user.list'],
						deletionProtection: false,
						givenName: 'Carlos',
						familyName: 'Mendes',
						email: 'carlos.mendes@acme.example.com'
					},
					observed: {
						presence: 'present',
						observedAt: '2026-10-21T13:49:58Z',
						emailVerified: false,
						userState: 'initial',
						roles: ['ipm.organization.get', 'ipm.user.get', 'ipm.user.list'],
						deletionProtection: false
					},
					createdAt: '2026-10-21T13:48:00Z',
					updatedAt: '2026-10-21T13:50:00Z'
				}
			],
			[ORG_GLOBEX_ID]: [
				{
					resourceId: '0199c8c1-1d2e-7f3a-8b4c-5d6e7f8a9b03',
					resourceVersion: '4',
					desiredGeneration: 1,
					phase: 'Ready',
					conditions: [
						{
							type: 'Ready',
							status: 'True',
							reason: 'Reconciled',
							message: 'User exists in the organization with the expected roles.',
							observedGeneration: 1,
							lastTransitionAt: '2026-10-21T09:15:00Z'
						}
					],
					desired: {
						lifecycle: 'present',
						reconciliation: 'active',
						organizationId: ORG_GLOBEX_ID,
						roles: ['ipm.organization.get', 'ipm.user.get', 'ipm.user.list'],
						deletionProtection: true,
						givenName: 'Helena',
						familyName: 'Rocha',
						email: 'helena.rocha@globex.example.com'
					},
					observed: {
						presence: 'present',
						observedAt: '2026-10-21T09:14:55Z',
						emailVerified: true,
						userState: 'active',
						roles: ['ipm.organization.get', 'ipm.user.get', 'ipm.user.list'],
						deletionProtection: true
					},
					createdAt: '2026-10-20T16:00:00Z',
					updatedAt: '2026-10-21T09:15:00Z'
				}
			],
			[ORG_INITECH_ID]: [
				{
					resourceId: '0199c8c1-1d2e-7f3a-8b4c-5d6e7f8a9b04',
					resourceVersion: '2',
					desiredGeneration: 1,
					phase: 'Failed',
					conditions: [
						{
							type: 'Ready',
							status: 'False',
							reason: 'IdentityProviderQuotaExceeded',
							message: 'Failed to reconcile user grant after maximum retry attempts.',
							observedGeneration: 1,
							lastTransitionAt: '2026-10-21T08:10:00Z'
						}
					],
					desired: {
						lifecycle: 'present',
						reconciliation: 'active',
						organizationId: ORG_INITECH_ID,
						roles: ['ipm.organization.get', 'ipm.user.get'],
						deletionProtection: false,
						givenName: 'Rafael',
						familyName: 'Costa',
						email: 'rafael.costa@initech.example.com'
					},
					observed: {
						presence: 'absent',
						observedAt: '2026-10-21T08:09:50Z'
					},
					createdAt: '2026-10-21T08:00:00Z',
					updatedAt: '2026-10-21T08:10:00Z'
				}
			]
		};

		this.services = [
			{
				resourceId: '0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1b',
				resourceVersion: '2',
				desiredGeneration: 1,
				phase: 'Ready',
				conditions: [
					{
						type: 'Ready',
						status: 'True',
						reason: 'Reconciled',
						message: 'O usuário tem as roles do serviço ipm.',
						observedGeneration: 1,
						lastTransitionAt: '2026-10-21T10:15:00Z'
					}
				],
				desired: {
					lifecycle: 'present',
					reconciliation: 'active',
					ownerAccountId: DEFAULT_ACCOUNT_ID,
					service: 'ipm',
					serviceRoles: [
						'ipm.organization.create',
						'ipm.organization.delete',
						'ipm.organization.get',
						'ipm.organization.list',
						'ipm.organization.update'
					],
					managedRoles: [
						'ipm.organization.create',
						'ipm.organization.delete',
						'ipm.organization.get',
						'ipm.organization.list',
						'ipm.organization.update'
					]
				},
				observed: {
					serviceRoles: [
						'ipm.organization.create',
						'ipm.organization.delete',
						'ipm.organization.get',
						'ipm.organization.list',
						'ipm.organization.update'
					]
				},
				createdAt: '2026-10-15T14:00:00Z',
				updatedAt: '2026-10-21T10:15:00Z'
			}
		];

		this.operations = [
			{
				title: 'Atualização da Organização',
				subtitle: 'Provisionando organização no provedor de identidade...',
				organizationId: ORG_ACME_ID,
				operation: {
					operationId: '0199c8d0-1111-7a01-8b01-000000000001',
					operationType: 'update',
					module: 'ipm',
					resourceType: 'organization',
					resourceId: ORG_ACME_ID,
					desiredGeneration: 2,
					operationStatus: 'in_progress',
					createdAt: '2026-10-21T13:58:00Z',
					updatedAt: '2026-10-21T13:58:30Z'
				}
			},
			{
				title: 'Criação de Usuário',
				subtitle: 'Aguardando processamento...',
				organizationId: ORG_ACME_ID,
				operation: {
					operationId: '0199c8d0-1111-7a01-8b01-000000000002',
					operationType: 'create',
					module: 'ipm',
					resourceType: 'user',
					resourceId: '0199c8c1-1d2e-7f3a-8b4c-5d6e7f8a9b02',
					desiredGeneration: 1,
					operationStatus: 'accepted',
					createdAt: '2026-10-21T13:55:00Z',
					updatedAt: '2026-10-21T13:55:05Z'
				}
			},
			{
				title: 'Habilitação de Serviço (IPM)',
				subtitle: 'Serviço habilitado com sucesso no catálogo.',
				organizationId: ORG_ACME_ID,
				operation: {
					operationId: '0199c8d0-1111-7a01-8b01-000000000003',
					operationType: 'create',
					module: 'sum',
					resourceType: 'service',
					resourceId: '0199c8b0-2d4e-7f10-8a3b-6c7d8e9f0a1b',
					desiredGeneration: 1,
					operationStatus: 'completed',
					createdAt: '2026-10-21T13:00:00Z',
					updatedAt: '2026-10-21T13:00:12Z',
					completedAt: '2026-10-21T13:00:12Z'
				}
			},
			{
				title: 'Exclusão de Organização recusada',
				subtitle: 'Recurso com proteção contra exclusão ativa.',
				organizationId: ORG_ACME_ID,
				operation: {
					operationId: '0199c8d0-1111-7a01-8b01-000000000004',
					operationType: 'delete',
					module: 'ipm',
					resourceType: 'organization',
					resourceId: ORG_ACME_ID,
					operationStatus: 'rejected',
					operationStatusReason: 'protected',
					createdAt: '2026-10-21T12:40:00Z',
					updatedAt: '2026-10-21T12:40:02Z',
					completedAt: '2026-10-21T12:40:02Z'
				}
			},
			{
				title: 'Falha no processamento de Usuário',
				subtitle: 'Tempo limite de sincronização excedido.',
				organizationId: ORG_INITECH_ID,
				operation: {
					operationId: '0199c8d0-1111-7a01-8b01-000000000005',
					operationType: 'create',
					module: 'ipm',
					resourceType: 'user',
					resourceId: '0199c8c1-1d2e-7f3a-8b4c-5d6e7f8a9b04',
					desiredGeneration: 1,
					operationStatus: 'failed',
					createdAt: '2026-10-21T08:00:00Z',
					updatedAt: '2026-10-21T08:10:00Z',
					completedAt: '2026-10-21T08:10:00Z'
				}
			}
		];

		this.notifications = [
			{
				id: 'notif-001',
				title: 'Organização acme-corporation pronta',
				description: 'A organização está pronta para uso e disponível.',
				severity: 'success',
				createdAt: 'há 10 minutos',
				read: false,
				organizationId: ORG_ACME_ID,
				href: '/identity/organizations'
			},
			{
				id: 'notif-002',
				title: 'Exclusão bloqueada por proteção de exclusão',
				description:
					'A solicitação de exclusão em acme-corporation foi rejeitada pois o recurso está protegido.',
				severity: 'warning',
				createdAt: 'há 25 minutos',
				read: false,
				organizationId: ORG_ACME_ID,
				relatedOperationId: '0199c8d0-1111-7a01-8b01-000000000004'
			},
			{
				id: 'notif-003',
				title: 'Serviço IPM habilitado no SUM',
				description:
					'O serviço foi ativado para sua conta. Talvez seja necessário iniciar uma nova sessão para atualizar os acessos.',
				severity: 'info',
				createdAt: 'há 1 hora',
				read: false,
				href: '/services/enabled'
			}
		];
	}

	async getUserContext(): Promise<UserContext> {
		return {
			accountId: this.account.resourceId,
			displayName:
				`${this.account.desired.givenName ?? 'Usuário'} ${this.account.desired.familyName ?? ''}`.trim(),
			emailMasked: 'd***@smarkee.example.com',
			roles: [
				...(this.account.desired.platformRoles ?? []),
				...this.services.flatMap((s) => s.desired.serviceRoles)
			],
			activeOrganizationId: this.organizations[0]?.resourceId ?? null,
			authConfig: {
				issuer: 'https://identity.smarkee.internal',
				clientId: 'console-web-client',
				redirectUri: 'http://localhost:5173/auth/callback',
				scopes: [
					'openid',
					'profile',
					'urn:zitadel:iam:org:project:id:roles-core:aud',
					'urn:zitadel:iam:org:project:id:roles-sum:aud',
					'urn:zitadel:iam:org:project:id:roles-ipm:aud'
				]
			}
		};
	}

	async getAccount(resourceId: string): Promise<AccountResource> {
		const validId = validateIdentifier(resourceId, 'accountId');
		if (validId !== this.account.resourceId) {
			throw new Error(`Account ${validId} não encontrada.`);
		}
		return structuredClone(this.account);
	}

	async listOrganizations(): Promise<OrganizationResource[]> {
		return structuredClone(this.organizations);
	}

	async getOrganization(resourceId: string): Promise<OrganizationResource> {
		const validId = validateIdentifier(resourceId, 'organizationId');
		const found = this.organizations.find((org) => org.resourceId === validId);
		if (!found) {
			throw new Error(`Organization ${validId} não encontrada.`);
		}
		return structuredClone(found);
	}

	getOrganizationMetadataDemo(resourceId: string): OrganizationMetadataDemo {
		const validId = validateIdentifier(resourceId, 'organizationId');
		const existing = this.organizationDemoMeta[validId];
		if (existing) {
			const usersCount = this.usersByOrganization[validId]?.length ?? existing.memberCount;
			return {
				...existing,
				memberCount: Math.max(existing.memberCount, usersCount)
			};
		}
		const org = this.organizations.find((o) => o.resourceId === validId);
		return {
			displayName: org ? this.formatOrganizationTitle(org.desired.name) : validId,
			planDemo: 'Enterprise',
			primaryRegionDemo: 'us-east-1',
			memberCount: this.usersByOrganization[validId]?.length ?? 1
		};
	}

	async listUsers(organizationId: string): Promise<OrganizationUserResource[]> {
		const validOrgId = validateIdentifier(organizationId, 'organizationId');
		return structuredClone(this.usersByOrganization[validOrgId] ?? []);
	}

	async listServices(): Promise<ServiceLinkResource[]> {
		return structuredClone(this.services);
	}

	getServiceCatalog(): ServiceCatalogItem[] {
		return structuredClone(PLATFORM_SERVICE_CATALOG);
	}

	async listRecentResources(organizationId: string): Promise<ResourceSummary[]> {
		const validOrgId = validateIdentifier(organizationId, 'organizationId');
		const org = this.organizations.find((item) => item.resourceId === validOrgId);
		const orgUsers = this.usersByOrganization[validOrgId] ?? [];

		const summaries: ResourceSummary[] = [];

		if (org) {
			summaries.push({
				resourceId: org.resourceId,
				displayName: org.desired.name,
				subtitle: 'Organização',
				module: 'ipm',
				resourceType: 'ipm.organization',
				typeLabel: 'Organização',
				phase: org.phase,
				updatedAt: 'há 2 horas',
				href: '/identity/organizations',
				isDemo: false,
				organizationId: org.resourceId
			});
		}

		for (const user of orgUsers) {
			summaries.push({
				resourceId: user.resourceId,
				displayName: `${user.desired.givenName ?? ''} ${user.desired.familyName ?? ''}`.trim(),
				subtitle: 'Usuário',
				module: 'ipm',
				resourceType: 'ipm.user',
				typeLabel: 'Usuário',
				phase: user.phase,
				updatedAt: 'há 3 horas',
				href: '/identity/users',
				isDemo: false,
				organizationId: validOrgId
			});
		}

		for (const svc of this.services) {
			summaries.push({
				resourceId: svc.resourceId,
				displayName: svc.desired.service.toUpperCase(),
				subtitle: 'Serviço',
				module: 'sum',
				resourceType: 'sum.service',
				typeLabel: 'Serviço',
				phase: svc.phase,
				updatedAt: 'há 5 horas',
				href: '/services/enabled',
				isDemo: false,
				organizationId: validOrgId
			});
		}

		summaries.push({
			resourceId: this.account.resourceId,
			displayName: `${this.account.desired.givenName} ${this.account.desired.familyName}`,
			subtitle: 'Conta Titular',
			module: 'core',
			resourceType: 'core.account',
			typeLabel: 'Conta',
			phase: this.account.phase,
			updatedAt: 'há 1 dia',
			href: '/identity/accounts',
			isDemo: false,
			organizationId: validOrgId
		});

		return summaries;
	}

	async listOperations(organizationId?: string): Promise<OperationTitleInfo[]> {
		if (!organizationId) {
			return structuredClone(this.operations);
		}
		const validOrgId = validateIdentifier(organizationId, 'organizationId');
		return structuredClone(
			this.operations.filter((item) => !item.organizationId || item.organizationId === validOrgId)
		);
	}

	async getOperation(operationId: string): Promise<Operation | null> {
		const validOpId = validateIdentifier(operationId, 'operationId');
		const found = this.operations.find((item) => item.operation.operationId === validOpId);
		return found ? structuredClone(found.operation) : null;
	}

	async listNotifications(organizationId?: string): Promise<ConsoleNotification[]> {
		if (!organizationId) {
			return structuredClone(this.notifications);
		}
		const validOrgId = validateIdentifier(organizationId, 'organizationId');
		return structuredClone(
			this.notifications.filter((n) => !n.organizationId || n.organizationId === validOrgId)
		);
	}

	async markNotificationAsRead(notificationId: string): Promise<void> {
		const item = this.notifications.find((n) => n.id === notificationId);
		if (item) {
			item.read = true;
		}
	}

	async markAllNotificationsAsRead(organizationId?: string): Promise<void> {
		for (const item of this.notifications) {
			if (!organizationId || !item.organizationId || item.organizationId === organizationId) {
				item.read = true;
			}
		}
	}

	async createOrganization(input: CreateOrganizationInput): Promise<RequestAccepted> {
		const normalizedName = input.name.trim().toLowerCase();
		if (!ORGANIZATION_NAME_PATTERN.test(normalizedName)) {
			throw new Error(
				'Nome da Organization inválido: use apenas letras minúsculas, números e hífens (padrão DNS).'
			);
		}

		const now = new Date().toISOString();
		const resourceId = this.nextIdentifier('0199c8a4-9900-7b00-8c00');
		const operationId = this.nextIdentifier('0199c8d0-9900-7a00-8b00');

		if (this.organizations.some((org) => org.desired.name === normalizedName)) {
			const rejectedOp: OperationTitleInfo = {
				title: `Criação de Organização (${normalizedName})`,
				subtitle: 'Conflito: já existe uma organização com este nome.',
				operation: {
					operationId,
					operationType: 'create',
					module: 'ipm',
					resourceType: 'organization',
					resourceId,
					operationStatus: 'rejected',
					operationStatusReason: 'conflict',
					createdAt: now,
					updatedAt: now,
					completedAt: now
				}
			};
			this.operations.unshift(rejectedOp);
			return { resourceId, operationId };
		}

		const newOrg: OrganizationResource = {
			resourceId,
			resourceVersion: '1',
			desiredGeneration: 1,
			phase: 'Pending',
			conditions: [
				{
					type: 'Ready',
					status: 'False',
					reason: 'Pending',
					message: 'Request accepted by Receiver; awaiting initial reconciliation.',
					observedGeneration: 1,
					lastTransitionAt: now
				},
				{
					type: 'Progressing',
					status: 'True',
					reason: 'RequestAccepted',
					message: 'Reconciling organization in identity provider.',
					observedGeneration: 1,
					lastTransitionAt: now
				}
			],
			desired: {
				lifecycle: 'present',
				reconciliation: 'active',
				name: normalizedName,
				platformAccess: 'granted',
				deletionProtection: input.deletionProtection ?? true
			},
			createdAt: now,
			updatedAt: now
		};

		if (input.displayName) {
			this.organizationDemoMeta[resourceId] = {
				displayName: input.displayName.trim(),
				planDemo: 'Enterprise',
				primaryRegionDemo: 'us-east-1',
				memberCount: 1
			};
		}

		this.organizations.unshift(newOrg);
		this.organizationDemoMeta[resourceId] = {
			displayName: this.formatOrganizationTitle(normalizedName),
			planDemo: 'Enterprise',
			primaryRegionDemo: 'us-east-1',
			memberCount: 1
		};
		this.usersByOrganization[resourceId] = [];

		const opEntry: OperationTitleInfo = {
			title: `Criação de Organização (${normalizedName})`,
			subtitle: 'Solicitação recebida; processando criação...',
			organizationId: resourceId,
			operation: {
				operationId,
				operationType: 'create',
				module: 'ipm',
				resourceType: 'organization',
				resourceId,
				desiredGeneration: 1,
				operationStatus: 'accepted',
				createdAt: now,
				updatedAt: now
			}
		};
		this.operations.unshift(opEntry);

		this.scheduleReconciliationTransition(
			operationId,
			() => {
				newOrg.phase = 'Reconciling';
				newOrg.resourceVersion = '2';
				newOrg.updatedAt = new Date().toISOString();
				opEntry.subtitle = 'Provisionando organização e Project Grant no provedor...';
			},
			() => {
				const doneAt = new Date().toISOString();
				newOrg.phase = 'Ready';
				newOrg.resourceVersion = '3';
				newOrg.updatedAt = doneAt;
				newOrg.conditions = [
					{
						type: 'Ready',
						status: 'True',
						reason: 'Reconciled',
						message: 'Organization exists in the identity provider with platform access.',
						observedGeneration: 1,
						lastTransitionAt: doneAt
					}
				];
				newOrg.observed = {
					presence: 'present',
					observedAt: doneAt,
					name: normalizedName,
					platformAccess: 'granted',
					organizationState: 'active',
					deletionProtection: newOrg.desired.deletionProtection
				};
				opEntry.subtitle = 'Organização pronta com sucesso.';
				this.notifications.unshift({
					id: `notif-${Date.now()}`,
					title: `Organização ${normalizedName} pronta`,
					description: 'A organização está pronta para uso.',
					severity: 'success',
					createdAt: 'agora',
					read: false,
					organizationId: resourceId,
					relatedOperationId: operationId,
					href: '/identity/organizations'
				});
			}
		);

		return { resourceId, operationId };
	}

	async createUser(input: CreateUserInput): Promise<RequestAccepted> {
		const validOrgId = validateIdentifier(input.organizationId, 'organizationId');
		const now = new Date().toISOString();
		const resourceId = this.nextIdentifier('0199c8c1-9900-7f00-8b00');
		const operationId = this.nextIdentifier('0199c8d0-9900-7a00-8b00');

		const sortedRoles = [...new Set(input.roles)].sort();
		const newUser: OrganizationUserResource = {
			resourceId,
			resourceVersion: '1',
			desiredGeneration: 1,
			phase: 'Reconciling',
			conditions: [
				{
					type: 'Ready',
					status: 'False',
					reason: 'Reconciling',
					message: 'Provisioning user in organization.',
					observedGeneration: 1,
					lastTransitionAt: now
				}
			],
			desired: {
				lifecycle: 'present',
				reconciliation: 'active',
				organizationId: validOrgId,
				roles: sortedRoles,
				deletionProtection: input.deletionProtection ?? false,
				givenName: input.givenName.trim(),
				familyName: input.familyName.trim(),
				email: input.email.trim().toLowerCase()
			},
			createdAt: now,
			updatedAt: now
		};

		if (!this.usersByOrganization[validOrgId]) {
			this.usersByOrganization[validOrgId] = [];
		}
		this.usersByOrganization[validOrgId].unshift(newUser);

		const opEntry: OperationTitleInfo = {
			title: `Criação de Usuário (${newUser.desired.givenName} ${newUser.desired.familyName})`,
			subtitle: 'Solicitação recebida; criando usuário...',
			organizationId: validOrgId,
			operation: {
				operationId,
				operationType: 'create',
				module: 'ipm',
				resourceType: 'user',
				resourceId,
				desiredGeneration: 1,
				operationStatus: 'accepted',
				createdAt: now,
				updatedAt: now
			}
		};
		this.operations.unshift(opEntry);

		this.scheduleReconciliationTransition(
			operationId,
			() => {
				opEntry.subtitle = 'Vinculando usuário à organização...';
			},
			() => {
				const doneAt = new Date().toISOString();
				newUser.phase = 'Ready';
				newUser.resourceVersion = '2';
				newUser.updatedAt = doneAt;
				newUser.conditions = [
					{
						type: 'Ready',
						status: 'True',
						reason: 'Reconciled',
						message: 'User exists in the organization with the expected roles.',
						observedGeneration: 1,
						lastTransitionAt: doneAt
					}
				];
				newUser.observed = {
					presence: 'present',
					observedAt: doneAt,
					emailVerified: true,
					userState: 'active',
					roles: sortedRoles,
					deletionProtection: newUser.desired.deletionProtection
				};
				opEntry.subtitle = 'Usuário adicionado com sucesso.';
			}
		);

		return { resourceId, operationId };
	}

	async enableService(input: EnableServiceInput): Promise<RequestAccepted> {
		const serviceName = input.service.trim().toLowerCase();
		const catalogItem = PLATFORM_SERVICE_CATALOG.find((c) => c.serviceKey === serviceName);
		const now = new Date().toISOString();
		const operationId = this.nextIdentifier('0199c8d0-9900-7a00-8b00');

		const existing = this.services.find((s) => s.desired.service === serviceName);
		const resourceId = existing?.resourceId ?? this.nextIdentifier('0199c8b0-9900-7f00-8a00');

		const roles = catalogItem
			? [...catalogItem.rolesGranted].sort()
			: [`${serviceName}.resource.get`];

		const serviceResource: ServiceLinkResource = existing ?? {
			resourceId,
			resourceVersion: '1',
			desiredGeneration: 1,
			phase: 'Pending',
			conditions: [
				{
					type: 'Ready',
					status: 'False',
					reason: 'Pending',
					message: `Solicitação de habilitação do serviço ${serviceName} aceita.`,
					observedGeneration: 1,
					lastTransitionAt: now
				}
			],
			desired: {
				lifecycle: 'present',
				reconciliation: 'active',
				ownerAccountId: this.account.resourceId,
				service: serviceName,
				serviceRoles: roles,
				managedRoles: roles
			},
			createdAt: now,
			updatedAt: now
		};

		if (existing) {
			existing.desired.lifecycle = 'present';
			existing.desired.serviceRoles = roles;
			existing.phase = 'Reconciling';
			existing.desiredGeneration += 1;
			existing.updatedAt = now;
		} else {
			this.services.push(serviceResource);
		}

		const opEntry: OperationTitleInfo = {
			title: `Habilitação de Serviço (${serviceName.toUpperCase()})`,
			subtitle: `Habilitando serviço ${serviceName.toUpperCase()}...`,
			operation: {
				operationId,
				operationType: existing ? 'update' : 'create',
				module: 'sum',
				resourceType: 'service',
				resourceId,
				desiredGeneration: serviceResource.desiredGeneration,
				operationStatus: 'accepted',
				createdAt: now,
				updatedAt: now
			}
		};
		this.operations.unshift(opEntry);

		this.scheduleReconciliationTransition(
			operationId,
			() => {
				serviceResource.phase = 'Reconciling';
				serviceResource.resourceVersion = String(Number(serviceResource.resourceVersion) + 1);
				serviceResource.updatedAt = new Date().toISOString();
				serviceResource.conditions = [
					{
						type: 'Ready',
						status: 'False',
						reason: 'Reconciling',
						message: `Concedendo roles do serviço ${serviceName} no provedor de identidade.`,
						observedGeneration: serviceResource.desiredGeneration,
						lastTransitionAt: serviceResource.updatedAt
					},
					{
						type: 'Progressing',
						status: 'True',
						reason: 'ActionDispatched',
						message: 'Aguardando confirmação do Executor do SUM.',
						observedGeneration: serviceResource.desiredGeneration,
						lastTransitionAt: serviceResource.updatedAt
					}
				];
				opEntry.subtitle = `Vinculando serviço ${serviceName.toUpperCase()} à organização...`;
			},
			() => {
				const doneAt = new Date().toISOString();
				serviceResource.phase = 'Ready';
				serviceResource.resourceVersion = String(Number(serviceResource.resourceVersion) + 1);
				serviceResource.updatedAt = doneAt;
				serviceResource.conditions = [
					{
						type: 'Ready',
						status: 'True',
						reason: 'Reconciled',
						message: `O usuário tem as roles do serviço ${serviceName}.`,
						observedGeneration: serviceResource.desiredGeneration,
						lastTransitionAt: doneAt
					}
				];
				serviceResource.observed = {
					serviceRoles: roles
				};
				opEntry.subtitle = `Serviço ${serviceName.toUpperCase()} habilitado com sucesso.`;
				this.notifications.unshift({
					id: `notif-${Date.now()}`,
					title: `Serviço ${serviceName.toUpperCase()} habilitado`,
					description: `O serviço ${serviceName.toUpperCase()} foi ativado e está disponível na organização.`,
					severity: 'success',
					createdAt: 'agora',
					read: false,
					relatedOperationId: operationId,
					href: '/services/enabled'
				});
			}
		);

		return { resourceId, operationId };
	}

	async disableService(resourceId: string): Promise<RequestAccepted> {
		const validId = validateIdentifier(resourceId, 'serviceResourceId');
		const found = this.services.find((s) => s.resourceId === validId);
		if (!found) {
			throw new Error(`Ligação de serviço ${validId} não encontrada.`);
		}

		const now = new Date().toISOString();
		const operationId = this.nextIdentifier('0199c8d0-9900-7a00-8b00');

		found.desired.lifecycle = 'absent';
		found.desired.serviceRoles = [];
		found.desiredGeneration += 1;
		found.phase = 'Reconciling';
		found.updatedAt = now;

		const opEntry: OperationTitleInfo = {
			title: `Desabilitação de Serviço (${found.desired.service.toUpperCase()})`,
			subtitle: 'Removendo serviço da organização...',
			operation: {
				operationId,
				operationType: 'delete',
				module: 'sum',
				resourceType: 'service',
				resourceId: validId,
				desiredGeneration: found.desiredGeneration,
				operationStatus: 'accepted',
				createdAt: now,
				updatedAt: now
			}
		};
		this.operations.unshift(opEntry);

		this.scheduleReconciliationTransition(
			operationId,
			() => {
				found.phase = 'Deleting';
				found.updatedAt = new Date().toISOString();
			},
			() => {
				const doneAt = new Date().toISOString();
				found.phase = 'Ready';
				found.observed = {};
				found.updatedAt = doneAt;
				opEntry.subtitle = `Serviço ${found.desired.service.toUpperCase()} desabilitado.`;
			}
		);

		return { resourceId: validId, operationId };
	}

	async deleteOrganization(resourceId: string): Promise<RequestAccepted> {
		const validId = validateIdentifier(resourceId, 'organizationId');
		const org = this.organizations.find((item) => item.resourceId === validId);
		const now = new Date().toISOString();
		const operationId = this.nextIdentifier('0199c8d0-9900-7a00-8b00');

		if (!org) {
			const notFoundOp: OperationTitleInfo = {
				title: 'Exclusão de Organização',
				subtitle: 'Organização não encontrada.',
				operation: {
					operationId,
					operationType: 'delete',
					module: 'ipm',
					resourceType: 'organization',
					resourceId: validId,
					operationStatus: 'rejected',
					operationStatusReason: 'not_found',
					createdAt: now,
					updatedAt: now,
					completedAt: now
				}
			};
			this.operations.unshift(notFoundOp);
			return { resourceId: validId, operationId };
		}

		if (org.desired.deletionProtection !== false) {
			const protectedOp: OperationTitleInfo = {
				title: `Exclusão de Organização (${org.desired.name})`,
				subtitle: 'Rejeitada: recurso com proteção contra exclusão ativa.',
				organizationId: validId,
				operation: {
					operationId,
					operationType: 'delete',
					module: 'ipm',
					resourceType: 'organization',
					resourceId: validId,
					operationStatus: 'rejected',
					operationStatusReason: 'protected',
					createdAt: now,
					updatedAt: now,
					completedAt: now
				}
			};
			this.operations.unshift(protectedOp);
			return { resourceId: validId, operationId };
		}

		org.desired.lifecycle = 'absent';
		org.desired.platformAccess = 'revoked';
		org.desiredGeneration += 1;
		org.phase = 'Deleting';
		org.updatedAt = now;

		const opEntry: OperationTitleInfo = {
			title: `Exclusão de Organização (${org.desired.name})`,
			subtitle: 'Removendo organização no provedor de identidade...',
			organizationId: validId,
			operation: {
				operationId,
				operationType: 'delete',
				module: 'ipm',
				resourceType: 'organization',
				resourceId: validId,
				desiredGeneration: org.desiredGeneration,
				operationStatus: 'accepted',
				createdAt: now,
				updatedAt: now
			}
		};
		this.operations.unshift(opEntry);

		this.scheduleReconciliationTransition(
			operationId,
			() => {
				org.updatedAt = new Date().toISOString();
			},
			() => {
				org.phase = 'Ready';
				org.observed = {
					presence: 'absent',
					observedAt: new Date().toISOString()
				};
				opEntry.subtitle = 'Organização removida com sucesso.';
			}
		);

		return { resourceId: validId, operationId };
	}

	private nextIdentifier(prefix: string): string {
		this.counter += 1;
		const suffix = this.counter.toString(16).padStart(12, '0');
		return `${prefix}-${suffix}`;
	}

	private formatOrganizationTitle(slug: string): string {
		return slug
			.split('-')
			.map((part) => part.charAt(0).toUpperCase() + part.slice(1))
			.join(' ');
	}

	private scheduleReconciliationTransition(
		operationId: string,
		onInProgress: () => void,
		onCompleted: () => void
	): void {
		const target = this.operations.find((item) => item.operation.operationId === operationId);
		if (!target) {
			return;
		}

		const step1Delay = Math.max(25, Math.round(this.transitionDelayMs * 0.4));
		const step2Delay = Math.max(60, this.transitionDelayMs);

		setTimeout(() => {
			target.operation.operationStatus = 'in_progress';
			target.operation.updatedAt = new Date().toISOString();
			onInProgress();
		}, step1Delay);

		setTimeout(() => {
			const doneAt = new Date().toISOString();
			target.operation.operationStatus = 'completed';
			target.operation.updatedAt = doneAt;
			target.operation.completedAt = doneAt;
			onCompleted();
		}, step2Delay);
	}

	async updateOrganization(input: UpdateOrganizationInput): Promise<RequestAccepted> {
		const validId = validateIdentifier(input.resourceId, 'organizationId');
		const org = this.organizations.find((item) => item.resourceId === validId);
		const now = new Date().toISOString();
		const operationId = this.nextIdentifier('0199c8d0-9900-7a00-8b00');

		if (!org) {
			const notFoundOp: OperationTitleInfo = {
				title: 'Edição de Organização',
				subtitle: 'Organização não encontrada.',
				operation: {
					operationId,
					operationType: 'update',
					module: 'ipm',
					resourceType: 'organization',
					resourceId: validId,
					operationStatus: 'rejected',
					operationStatusReason: 'not_found',
					createdAt: now,
					updatedAt: now,
					completedAt: now
				}
			};
			this.operations.unshift(notFoundOp);
			return { resourceId: validId, operationId };
		}

		if (input.name !== undefined) {
			const normalizedName = input.name.trim().toLowerCase();
			if (!ORGANIZATION_NAME_PATTERN.test(normalizedName)) {
				throw new Error(
					'Nome da Organization inválido: use apenas letras minúsculas, números e hífens (padrão DNS).'
				);
			}
			org.desired.name = normalizedName;
		}

		if (input.deletionProtection !== undefined) {
			org.desired.deletionProtection = input.deletionProtection;
		}

		org.updatedAt = now;

		if (input.displayName !== undefined) {
			const meta = this.organizationDemoMeta[validId] || {
				planDemo: 'Enterprise',
				primaryRegionDemo: 'us-east-1',
				memberCount: 1,
				displayName: org.desired.name
			};
			meta.displayName = input.displayName.trim() || org.desired.name;
			this.organizationDemoMeta[validId] = meta;
		}

		const successOp: OperationTitleInfo = {
			title: `Edição de Organização (${org.desired.name})`,
			subtitle: 'A organização foi atualizada com sucesso.',
			operation: {
				operationId,
				operationType: 'update',
				module: 'ipm',
				resourceType: 'organization',
				resourceId: validId,
				operationStatus: 'completed',
				createdAt: now,
				updatedAt: now,
				completedAt: now
			}
		};
		this.operations.unshift(successOp);

		return { resourceId: validId, operationId };
	}

	async updateUser(input: UpdateUserInput): Promise<RequestAccepted> {
		const validId = validateIdentifier(input.resourceId, 'userId');
		const now = new Date().toISOString();
		const operationId = this.nextIdentifier('0199c8d0-9900-7a00-8b00');

		let foundUser;
		for (const orgUsers of Object.values(this.usersByOrganization)) {
			foundUser = orgUsers.find((u) => u.resourceId === validId);
			if (foundUser) break;
		}

		if (!foundUser) {
			const notFoundOp: OperationTitleInfo = {
				title: 'Edição de Usuário',
				subtitle: 'Usuário não encontrado.',
				operation: {
					operationId,
					operationType: 'update',
					module: 'ipm',
					resourceType: 'user',
					resourceId: validId,
					operationStatus: 'rejected',
					operationStatusReason: 'not_found',
					createdAt: now,
					updatedAt: now,
					completedAt: now
				}
			};
			this.operations.unshift(notFoundOp);
			return { resourceId: validId, operationId };
		}

		if (input.roles !== undefined) {
			foundUser.desired.roles = [...input.roles];
		}
		if (input.deletionProtection !== undefined) {
			foundUser.desired.deletionProtection = input.deletionProtection;
		}

		foundUser.updatedAt = now;

		const successOp: OperationTitleInfo = {
			title: `Edição de Usuário (${foundUser.desired.givenName})`,
			subtitle: 'O usuário foi atualizado com sucesso.',
			operation: {
				operationId,
				operationType: 'update',
				module: 'ipm',
				resourceType: 'user',
				resourceId: validId,
				operationStatus: 'completed',
				createdAt: now,
				updatedAt: now,
				completedAt: now
			}
		};
		this.operations.unshift(successOp);

		return { resourceId: validId, operationId };
	}

	async deleteUser(resourceId: string): Promise<RequestAccepted> {
		const validId = validateIdentifier(resourceId, 'userId');
		const now = new Date().toISOString();
		const operationId = this.nextIdentifier('0199c8d0-9900-7a00-8b00');

		let foundUser;
		let foundOrgId;
		for (const [orgId, orgUsers] of Object.entries(this.usersByOrganization)) {
			foundUser = orgUsers.find((u) => u.resourceId === validId);
			if (foundUser) {
				foundOrgId = orgId;
				break;
			}
		}

		if (!foundUser || !foundOrgId) {
			const notFoundOp: OperationTitleInfo = {
				title: 'Exclusão de Usuário',
				subtitle: 'Usuário não encontrado.',
				operation: {
					operationId,
					operationType: 'delete',
					module: 'ipm',
					resourceType: 'user',
					resourceId: validId,
					operationStatus: 'rejected',
					operationStatusReason: 'not_found',
					createdAt: now,
					updatedAt: now,
					completedAt: now
				}
			};
			this.operations.unshift(notFoundOp);
			return { resourceId: validId, operationId };
		}

		if (foundUser.desired.deletionProtection !== false) {
			const protectedOp: OperationTitleInfo = {
				title: `Exclusão de Usuário (${foundUser.desired.givenName})`,
				subtitle: 'O usuário está protegido contra exclusão.',
				operation: {
					operationId,
					operationType: 'delete',
					module: 'ipm',
					resourceType: 'user',
					resourceId: validId,
					operationStatus: 'rejected',
					operationStatusReason: 'conflict',
					createdAt: now,
					updatedAt: now,
					completedAt: now
				}
			};
			this.operations.unshift(protectedOp);
			return { resourceId: validId, operationId };
		}

		// Simulando exclusão instantânea
		this.usersByOrganization[foundOrgId] = this.usersByOrganization[foundOrgId].filter(
			(u) => u.resourceId !== validId
		);

		const successOp: OperationTitleInfo = {
			title: `Exclusão de Usuário (${foundUser.desired.givenName})`,
			subtitle: 'O usuário foi removido da organização.',
			operation: {
				operationId,
				operationType: 'delete',
				module: 'ipm',
				resourceType: 'user',
				resourceId: validId,
				operationStatus: 'completed',
				createdAt: now,
				updatedAt: now,
				completedAt: now
			}
		};
		this.operations.unshift(successOp);

		return { resourceId: validId, operationId };
	}

	async updateAccount(input: UpdateAccountInput): Promise<RequestAccepted> {
		const validId = validateIdentifier(input.resourceId, 'accountId');
		const now = new Date().toISOString();
		const operationId = this.nextIdentifier('0199c8d0-9900-7a00-8b00');

		if (this.account.resourceId !== validId) {
			throw new Error('Conta não encontrada.');
		}

		if (input.deletionProtection !== undefined) {
			this.account.desired.deletionProtection = input.deletionProtection;
		}

		this.account.updatedAt = now;

		const successOp: OperationTitleInfo = {
			title: 'Edição de Conta',
			subtitle: 'Conta atualizada com sucesso.',
			operation: {
				operationId,
				operationType: 'update',
				module: 'core',
				resourceType: 'account',
				resourceId: validId,
				operationStatus: 'completed',
				createdAt: now,
				updatedAt: now,
				completedAt: now
			}
		};
		this.operations.unshift(successOp);

		return { resourceId: validId, operationId };
	}

	async deleteAccount(resourceId: string): Promise<RequestAccepted> {
		const validId = validateIdentifier(resourceId, 'accountId');
		const now = new Date().toISOString();
		const operationId = this.nextIdentifier('0199c8d0-9900-7a00-8b00');

		if (this.account.resourceId !== validId) {
			throw new Error('Conta não encontrada.');
		}

		if (this.account.desired.deletionProtection !== false) {
			const protectedOp: OperationTitleInfo = {
				title: 'Exclusão de Conta',
				subtitle: 'A conta está protegida contra exclusão.',
				operation: {
					operationId,
					operationType: 'delete',
					module: 'core',
					resourceType: 'account',
					resourceId: validId,
					operationStatus: 'rejected',
					operationStatusReason: 'conflict',
					createdAt: now,
					updatedAt: now,
					completedAt: now
				}
			};
			this.operations.unshift(protectedOp);
			return { resourceId: validId, operationId };
		}

		if (this.organizations.length > 0 || this.services.length > 0) {
			const remainingOp: OperationTitleInfo = {
				title: 'Exclusão de Conta',
				subtitle: 'A conta possui organizações ou serviços ativos.',
				operation: {
					operationId,
					operationType: 'delete',
					module: 'core',
					resourceType: 'account',
					resourceId: validId,
					operationStatus: 'rejected',
					operationStatusReason: 'conflict',
					createdAt: now,
					updatedAt: now,
					completedAt: now
				}
			};
			this.operations.unshift(remainingOp);
			return { resourceId: validId, operationId };
		}

		const successOp: OperationTitleInfo = {
			title: 'Exclusão de Conta',
			subtitle: 'A conta foi agendada para exclusão.',
			operation: {
				operationId,
				operationType: 'delete',
				module: 'core',
				resourceType: 'account',
				resourceId: validId,
				operationStatus: 'completed',
				createdAt: now,
				updatedAt: now,
				completedAt: now
			}
		};
		this.operations.unshift(successOp);

		return { resourceId: validId, operationId };
	}
}
