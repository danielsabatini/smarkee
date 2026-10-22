/**
 * Estado reativo de contexto do Smarkee Console (Svelte 5 Runes).
 * Instanciado dentro de +layout.svelte e distribuído via setContext / getContext
 * para garantir isolamento completo em SSR (AGENTS.md e frontend.md §2.1).
 */

import { getContext, setContext } from 'svelte';
import type {
	ConsoleDataAdapter,
	CreateOrganizationInput,
	CreateUserInput,
	EnableServiceInput
} from '../services/adapter';
import { OperationWatcher } from '../services/operation-watcher';
import { validateIdentifier, type Operation, type RequestAccepted } from '../types/common';
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

const CONSOLE_CONTEXT_KEY = Symbol('smarkee.console.context');

export class ConsoleState {
	readonly adapter: ConsoleDataAdapter;
	readonly watcher: OperationWatcher;

	isBootstrapping = $state<boolean>(true);
	isSwitchingOrganization = $state<boolean>(false);
	errorMessage = $state<string | null>(null);

	userContext = $state<UserContext | null>(null);
	account = $state<AccountResource | null>(null);
	organizations = $state<OrganizationResource[]>([]);
	activeOrganizationId = $state<string | null>(null);

	organizationUsers = $state<OrganizationUserResource[]>([]);
	recentResources = $state<ResourceSummary[]>([]);
	services = $state<ServiceLinkResource[]>([]);
	operations = $state<OperationTitleInfo[]>([]);
	notifications = $state<ConsoleNotification[]>([]);

	isSidebarCompact = $state<boolean>(false);
	isMobileDrawerOpen = $state<boolean>(false);
	isOperationsPanelOpen = $state<boolean>(true);
	activePanelTab = $state<'notifications' | 'operations'>('operations');
	isGlobalSearchOpen = $state<boolean>(false);
	selectedOperationForModal = $state<OperationTitleInfo | null>(null);

	activeOrganization = $derived.by(
		() => this.organizations.find((org) => org.resourceId === this.activeOrganizationId) ?? null
	);

	activeOrganizationDemoMeta = $derived.by<OrganizationMetadataDemo | null>(() => {
		if (!this.activeOrganizationId) {
			return null;
		}
		return this.adapter.getOrganizationMetadataDemo(this.activeOrganizationId);
	});

	serviceCatalog = $derived.by<ServiceCatalogItem[]>(() => this.adapter.getServiceCatalog());

	inProgressOperations = $derived.by(() =>
		this.operations.filter(
			(item) =>
				item.operation.operationStatus === 'accepted' ||
				item.operation.operationStatus === 'in_progress'
		)
	);

	completedOperations = $derived.by(() =>
		this.operations.filter(
			(item) =>
				item.operation.operationStatus === 'completed' ||
				item.operation.operationStatus === 'failed' ||
				item.operation.operationStatus === 'rejected'
		)
	);

	unreadNotificationsCount = $derived.by(() => this.notifications.filter((n) => !n.read).length);

	activeOperationsCount = $derived.by(() => this.inProgressOperations.length);

	constructor(adapter: ConsoleDataAdapter, watcher?: OperationWatcher) {
		this.adapter = adapter;
		this.watcher = watcher ?? new OperationWatcher(adapter, { initialIntervalMs: 350 });

		this.watcher.subscribe((updatedOp: Operation) => {
			void this.refreshAfterOperationUpdate(updatedOp);
		});
	}

	/**
	 * Carrega o estado inicial da conta, organizações e contexto da organização ativa.
	 */
	async initialize(): Promise<void> {
		this.isBootstrapping = true;
		this.errorMessage = null;

		try {
			const [context, orgs, svcLinks] = await Promise.all([
				this.adapter.getUserContext(),
				this.adapter.listOrganizations(),
				this.adapter.listServices()
			]);

			const accountResource = await this.adapter.getAccount(context.accountId);

			this.userContext = context;
			this.account = accountResource;
			this.organizations = orgs;
			this.services = svcLinks;

			const initialOrgId = context.activeOrganizationId ?? orgs[0]?.resourceId ?? null;
			if (initialOrgId) {
				await this.selectOrganization(initialOrgId);
			} else {
				this.activeOrganizationId = null;
				this.organizationUsers = [];
				this.recentResources = [];
				this.operations = await this.adapter.listOperations();
				this.notifications = await this.adapter.listNotifications();
			}
		} catch (err) {
			this.errorMessage =
				err instanceof Error
					? err.message
					: 'Não foi possível carregar os dados iniciais do Smarkee Console.';
		} finally {
			this.isBootstrapping = false;
		}
	}

	/**
	 * Alterna a Organization ativa limpando sincronicamente os dados da organização anterior
	 * para impedir qualquer vazamento visual entre organizações (docs/console/CONSOLE.md §5.2).
	 */
	async selectOrganization(organizationId: string): Promise<void> {
		const validId = validateIdentifier(organizationId, 'organizationId');

		// Limpeza síncrona imediata dos dados dependentes da organização anterior
		this.isSwitchingOrganization = true;
		this.errorMessage = null;
		this.activeOrganizationId = validId;
		this.organizationUsers = [];
		this.recentResources = [];
		this.operations = [];
		this.notifications = [];

		try {
			const [users, recent, ops, notifs, refreshedOrgs, refreshedServices] = await Promise.all([
				this.adapter.listUsers(validId),
				this.adapter.listRecentResources(validId),
				this.adapter.listOperations(validId),
				this.adapter.listNotifications(validId),
				this.adapter.listOrganizations(),
				this.adapter.listServices()
			]);

			// Verifica se o usuário não trocou novamente durante o carregamento
			if (this.activeOrganizationId !== validId) {
				return;
			}

			this.organizations = refreshedOrgs;
			this.services = refreshedServices;
			this.organizationUsers = users;
			this.recentResources = recent;
			this.operations = ops;
			this.notifications = notifs;
		} catch (err) {
			this.errorMessage =
				err instanceof Error
					? err.message
					: 'Falha ao carregar os recursos da organização selecionada.';
		} finally {
			if (this.activeOrganizationId === validId) {
				this.isSwitchingOrganization = false;
			}
		}
	}

	/**
	 * Dispara a criação assíncrona de uma Organization (202 Accepted) e inicia o acompanhamento.
	 */
	async createOrganization(input: CreateOrganizationInput): Promise<RequestAccepted> {
		const accepted = await this.adapter.createOrganization(input);
		await this.refreshCurrentContext();
		this.openOperationsPanel('operations');
		this.watcher.watch(accepted.operationId);
		return accepted;
	}

	/**
	 * Dispara a criação assíncrona de um User na Organization ativa (202 Accepted).
	 */
	async createUser(input: CreateUserInput): Promise<RequestAccepted> {
		const accepted = await this.adapter.createUser(input);
		await this.refreshCurrentContext();
		this.openOperationsPanel('operations');
		this.watcher.watch(accepted.operationId);
		return accepted;
	}

	/**
	 * Solicita a habilitação assíncrona de um serviço no SUM (202 Accepted).
	 */
	async enableService(input: EnableServiceInput): Promise<RequestAccepted> {
		const accepted = await this.adapter.enableService(input);
		await this.refreshCurrentContext();
		this.openOperationsPanel('operations');
		this.watcher.watch(accepted.operationId);
		return accepted;
	}

	/**
	 * Solicita a desabilitação assíncrona de um serviço no SUM (202 Accepted).
	 */
	async disableService(resourceId: string): Promise<RequestAccepted> {
		const accepted = await this.adapter.disableService(resourceId);
		await this.refreshCurrentContext();
		this.openOperationsPanel('operations');
		this.watcher.watch(accepted.operationId);
		return accepted;
	}

	/**
	 * Solicita a exclusão assíncrona de uma Organization (respeitando deletionProtection).
	 */
	async deleteOrganization(resourceId: string): Promise<RequestAccepted> {
		const accepted = await this.adapter.deleteOrganization(resourceId);
		await this.refreshCurrentContext();
		this.openOperationsPanel('operations');
		this.watcher.watch(accepted.operationId);
		return accepted;
	}

	async markNotificationAsRead(notificationId: string): Promise<void> {
		await this.adapter.markNotificationAsRead(notificationId);
		this.notifications = await this.adapter.listNotifications(
			this.activeOrganizationId ?? undefined
		);
	}

	async markAllNotificationsAsRead(): Promise<void> {
		await this.adapter.markAllNotificationsAsRead(this.activeOrganizationId ?? undefined);
		this.notifications = await this.adapter.listNotifications(
			this.activeOrganizationId ?? undefined
		);
	}

	toggleSidebarCompact(): void {
		this.isSidebarCompact = !this.isSidebarCompact;
	}

	setMobileDrawerOpen(open: boolean): void {
		this.isMobileDrawerOpen = open;
	}

	openOperationsPanel(tab: 'notifications' | 'operations' = 'operations'): void {
		this.activePanelTab = tab;
		this.isOperationsPanelOpen = true;
	}

	closeOperationsPanel(): void {
		this.isOperationsPanelOpen = false;
	}

	toggleOperationsPanel(tab?: 'notifications' | 'operations'): void {
		if (tab && this.isOperationsPanelOpen && this.activePanelTab !== tab) {
			this.activePanelTab = tab;
			return;
		}
		if (tab) {
			this.activePanelTab = tab;
		}
		this.isOperationsPanelOpen = !this.isOperationsPanelOpen;
	}

	async refreshCurrentContext(): Promise<void> {
		const orgId = this.activeOrganizationId;
		const [orgs, svcLinks, ops, notifs] = await Promise.all([
			this.adapter.listOrganizations(),
			this.adapter.listServices(),
			this.adapter.listOperations(orgId ?? undefined),
			this.adapter.listNotifications(orgId ?? undefined)
		]);

		this.organizations = orgs;
		this.services = svcLinks;
		this.operations = ops;
		this.notifications = notifs;

		if (orgId) {
			const [users, recent] = await Promise.all([
				this.adapter.listUsers(orgId),
				this.adapter.listRecentResources(orgId)
			]);
			if (this.activeOrganizationId === orgId) {
				this.organizationUsers = users;
				this.recentResources = recent;
			}
		}
	}

	private async refreshAfterOperationUpdate(updatedOp: Operation): Promise<void> {
		await this.refreshCurrentContext();
		if (
			this.selectedOperationForModal &&
			this.selectedOperationForModal.operation.operationId === updatedOp.operationId
		) {
			const updatedEntry = this.operations.find(
				(item) => item.operation.operationId === updatedOp.operationId
			);
			if (updatedEntry) {
				this.selectedOperationForModal = updatedEntry;
			}
		}
	}

	dispose(): void {
		this.watcher.dispose();
	}
}

export function setConsoleState(state: ConsoleState): ConsoleState {
	return setContext(CONSOLE_CONTEXT_KEY, state);
}

export function getConsoleState(): ConsoleState {
	const state = getContext<ConsoleState | undefined>(CONSOLE_CONTEXT_KEY);
	if (!state) {
		throw new Error(
			'ConsoleState ausente no contexto do Svelte. Certifique-se de chamar setConsoleState no +layout.svelte.'
		);
	}
	return state;
}
