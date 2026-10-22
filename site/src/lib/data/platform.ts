export interface NavItem {
	label: string;
	href: string;
	badge?: string;
}

export interface PlatformModule {
	code: string;
	name: string;
	tagline: string;
	description: string;
	href: string;
	status: 'GA' | 'Beta' | 'Preview';
	iconName: 'ShieldCheck' | 'Layers' | 'FileText' | 'Activity' | 'Terminal' | 'Cpu';
	highlights: string[];
	metrics?: string;
}

export const MAIN_NAV: NavItem[] = [
	{ label: 'Plataforma', href: '/#plataforma' },
	{ label: 'Módulos', href: '/produtos' },
	{ label: 'Soluções', href: '/solucoes' },
	{ label: 'Loop de Controle', href: '/#loop-de-controle' },
	{ label: 'Blog', href: '/blog' },
	{ label: 'Sobre', href: '/sobre' },
	{ label: 'Contato', href: '/contato' }
];

export const PLATFORM_MODULES: PlatformModule[] = [
	{
		code: 'IPM',
		name: 'Identity Provider Manager',
		tagline: 'Gestão Unificada de Identidade e Acesso Multi-tenant',
		description:
			'Orquestração centralizada de contas titulares, organizações isoladas, usuários e permissões de granularidade fina com menor privilégio por padrão.',
		href: '/produtos#ipm',
		status: 'GA',
		iconName: 'ShieldCheck',
		highlights: [
			'Federação OIDC com PKCE público nativo',
			'Isolamento multi-tenant estrito por organização',
			'Controle de papéis e escopos com zero vazamento entre tenants'
		],
		metrics: 'Menor privilégio por padrão'
	},
	{
		code: 'SUM',
		name: 'Service Usage Manager',
		tagline: 'Habilitação Declarativa e Catálogo de Serviços',
		description:
			'Catálogo centralizado de serviços em nuvem ativados sob demanda com ciclo de vida declarativo (`present` / `absent`) e concessão atômica de acessos.',
		href: '/produtos#sum',
		status: 'GA',
		iconName: 'Layers',
		highlights: [
			'Habilitação e desabilitação com 1 clique ou via CLI',
			'Reconciliação assíncrona com confirmação HTTP 202',
			'Ativação atômica de papéis de serviço vinculados'
		],
		metrics: '100% sob demanda'
	},
	{
		code: 'AEM',
		name: 'Audit Event Manager',
		tagline: 'Rastreabilidade Imutável e Auditoria de Operações',
		description:
			'Trilha de auditoria criptograficamente referenciável de toda transição de estado, chamada de API e intenção solicitada, em total conformidade regulatória.',
		href: '/produtos#aem',
		status: 'Preview',
		iconName: 'FileText',
		highlights: [
			'Registro append-only de cada operação e operador',
			'Digest criptográfico sha256 de requisição',
			'Correlação ponta a ponta com trace IDs e resource IDs'
		],
		metrics: 'Auditoria contínua'
	},
	{
		code: 'ODM',
		name: 'Observability Data Manager',
		tagline: 'Telemetria Aberta e Métricas em Tempo Real',
		description:
			'Coleta e agregação de logs estruturados, métricas e traces com convenção semântica OpenTelemetry, alertas preditivos e monitoramento de saúde.',
		href: '/produtos#odm',
		status: 'Preview',
		iconName: 'Activity',
		highlights: [
			'Compatível com OpenTelemetry (OTel) sem lock-in',
			'Logs estruturados com redação de dados sensíveis',
			'Health checks em tempo real de componentes e filas'
		],
		metrics: 'Padrão aberto OTel'
	}
];

export const PILLARS = [
	{
		title: 'Segurança por Padrão',
		description:
			'Menor privilégio estrito, tokens de curta duração, máscaras automáticas de dados sensíveis e autenticação baseada em padrões abertos.'
	},
	{
		title: 'Reconciliação Contínua',
		description:
			'Modelo kubernetes-like com estado desejado (Desired), estado observado (Observed) e reconciliação ativa orientada a eventos.'
	},
	{
		title: 'Resiliência e Idempotência',
		description:
			'Toda operação é segura para ser repetida. Tolerância nativa a quedas de rede, concorrência e mensagens duplicadas com NATS JetStream.'
	},
	{
		title: 'Zero Vendor Lock-in',
		description:
			'Contratos abertos em JSON Schema versionados, OpenTelemetry e armazenamento relacional com SSOT PostgreSQL.'
	}
];
