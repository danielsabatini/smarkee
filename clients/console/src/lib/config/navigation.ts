/**
 * Configuração tipada única de navegação lateral e catálogo de módulos do Smarkee Console.
 * Conforme docs/console/CONSOLE.md §5.3, §6.1 e §6.2.
 */

import type { ModuleCode, ServiceCatalogItem } from '../types/console';

export interface NavItem {
	id: string;
	label: string;
	href: string;
	iconName:
		| 'home'
		| 'user-check'
		| 'building-2'
		| 'users'
		| 'settings'
		| 'layout-grid'
		| 'shield-check'
		| 'file-text'
		| 'bar-chart-3'
		| 'list-filter'
		| 'activity'
		| 'bell'
		| 'bot'
		| 'server'
		| 'wrench';
	isDemo?: boolean;
	moduleCode?: ModuleCode;
	description?: string;
}

export interface NavSection {
	id: string;
	title: string;
	shortTitle?: string;
	moduleCode?: ModuleCode;
	isDemo?: boolean;
	collapsible: boolean;
	items: NavItem[];
}

export const NAVIGATION_SECTIONS: NavSection[] = [
	{
		id: 'home',
		title: 'Início',
		shortTitle: 'Início',
		collapsible: false,
		items: [
			{
				id: 'dashboard',
				label: 'Início',
				href: '/',
				iconName: 'home',
				description: 'Visão geral da organização e estado dos serviços'
			}
		]
	},
	{
		id: 'ipm',
		title: 'Identity Provider Manager (IPM)',
		shortTitle: 'Identidade (IPM)',
		moduleCode: 'IPM',
		collapsible: true,
		items: [
			{
				id: 'ipm-accounts',
				label: 'Contas',
				href: '/identity/accounts',
				iconName: 'user-check',
				moduleCode: 'IPM',
				description: 'Conta titular autenticada (core.account)'
			},
			{
				id: 'ipm-organizations',
				label: 'Organizações',
				href: '/identity/organizations',
				iconName: 'building-2',
				moduleCode: 'IPM',
				description: 'Organizações do titular (ipm.organization)'
			},
			{
				id: 'ipm-users',
				label: 'Usuários',
				href: '/identity/users',
				iconName: 'users',
				moduleCode: 'IPM',
				description: 'Usuários na organização ativa (ipm.user)'
			},
			{
				id: 'ipm-settings',
				label: 'Configurações',
				href: '/identity/settings',
				iconName: 'settings',
				moduleCode: 'IPM',
				isDemo: true,
				description: 'Políticas de autenticação e federação OIDC'
			}
		]
	},
	{
		id: 'sum',
		title: 'Service Usage Manager (SUM)',
		shortTitle: 'Serviços (SUM)',
		moduleCode: 'SUM',
		collapsible: true,
		items: [
			{
				id: 'sum-catalog',
				label: 'Catálogo de Serviços',
				href: '/services/catalog',
				iconName: 'layout-grid',
				moduleCode: 'SUM',
				description: 'Explore os módulos disponíveis na plataforma'
			},
			{
				id: 'sum-enabled',
				label: 'Serviços Habilitados',
				href: '/services/enabled',
				iconName: 'shield-check',
				moduleCode: 'SUM',
				description: 'Ligações de serviços ativas na conta (sum.service)'
			}
		]
	},
	{
		id: 'aem',
		title: 'Audit Event Manager (AEM)',
		shortTitle: 'Auditoria (AEM)',
		moduleCode: 'AEM',
		isDemo: true,
		collapsible: true,
		items: [
			{
				id: 'aem-events',
				label: 'Eventos de Auditoria',
				href: '/audit/events',
				iconName: 'file-text',
				moduleCode: 'AEM',
				isDemo: true,
				description: 'Trilha de auditoria de comandos e reconciliação'
			}
		]
	},
	{
		id: 'odm',
		title: 'Observability Data Manager (ODM)',
		shortTitle: 'Observabilidade (ODM)',
		moduleCode: 'ODM',
		isDemo: true,
		collapsible: true,
		items: [
			{
				id: 'odm-metrics',
				label: 'Métricas',
				href: '/observability/metrics',
				iconName: 'bar-chart-3',
				moduleCode: 'ODM',
				isDemo: true,
				description: 'Séries temporais e indicadores operacionais'
			},
			{
				id: 'odm-logs',
				label: 'Logs',
				href: '/observability/logs',
				iconName: 'list-filter',
				moduleCode: 'ODM',
				isDemo: true,
				description: 'Registros estruturados OpenTelemetry'
			},
			{
				id: 'odm-traces',
				label: 'Traces',
				href: '/observability/traces',
				iconName: 'activity',
				moduleCode: 'ODM',
				isDemo: true,
				description: 'Rastreamento distribuído entre serviços'
			},
			{
				id: 'odm-alerts',
				label: 'Alertas',
				href: '/observability/alerts',
				iconName: 'bell',
				moduleCode: 'ODM',
				isDemo: true,
				description: 'Regras de alerta e SLOs de reconciliação'
			}
		]
	},
	{
		id: 'admin',
		title: 'Administração',
		shortTitle: 'Administração',
		collapsible: true,
		items: [
			{
				id: 'admin-settings',
				label: 'Configurações',
				href: '/settings',
				iconName: 'settings',
				description: 'Preferências do console, sessão OIDC e integrações'
			}
		]
	}
];

export const PLATFORM_SERVICE_CATALOG: ServiceCatalogItem[] = [
	{
		code: 'IPM',
		serviceKey: 'ipm',
		name: 'Identity Provider Manager',
		shortName: 'Identity Provider',
		description: 'Gerencie identidades, organizações e controle de acesso.',
		href: '/identity/organizations',
		isDemo: false,
		rolesGranted: [
			'ipm.organization.create',
			'ipm.organization.delete',
			'ipm.organization.get',
			'ipm.organization.list',
			'ipm.organization.update'
		]
	},
	{
		code: 'SUM',
		serviceKey: 'sum',
		name: 'Service Usage Manager',
		shortName: 'Service Usage',
		description: 'Controle o uso e a habilitação de serviços da plataforma.',
		href: '/services/enabled',
		isDemo: false,
		rolesGranted: ['sum.ipm.create', 'sum.ipm.delete', 'sum.ipm.get']
	},
	{
		code: 'AEM',
		serviceKey: 'aem',
		name: 'Audit Event Manager',
		shortName: 'Audit Event',
		description: 'Explore eventos de auditoria e histórico de operações.',
		href: '/audit/events',
		isDemo: true,
		rolesGranted: ['aem.event.get', 'aem.event.list']
	},
	{
		code: 'ODM',
		serviceKey: 'odm',
		name: 'Observability Data Manager',
		shortName: 'Observability',
		description: 'Métricas, logs, traces e alertas unificados.',
		href: '/observability/metrics',
		isDemo: true,
		rolesGranted: ['odm.telemetry.get', 'odm.telemetry.list']
	}
];
