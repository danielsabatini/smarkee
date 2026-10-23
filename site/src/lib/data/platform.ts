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
	{ label: 'Blog', href: '/blog' },
	{ label: 'Sobre', href: '/sobre' },
	{ label: 'Contato', href: '/contato' }
];

export const PLATFORM_MODULES: PlatformModule[] = [
	{
		code: 'IPM',
		name: 'Gestão de Identidade e Acessos',
		tagline: 'Segurança desde o primeiro clique',
		description:
			'Organize contas, gerencie permissões de equipes e garanta o acesso seguro a todos os recursos da nuvem sem dor de cabeça.',
		href: '/produtos#ipm',
		status: 'GA',
		iconName: 'ShieldCheck',
		highlights: [
			'Autenticação segura via padrão aberto OIDC',
			'Isolamento completo entre diferentes organizações',
			'Controle de permissões com menor privilégio por padrão'
		],
		metrics: 'Menor privilégio por padrão'
	},
	{
		code: 'SUM',
		name: 'Catálogo de Serviços',
		tagline: 'Infraestrutura sob demanda em segundos',
		description:
			'Habilite e gerencie seus recursos de nuvem de forma unificada. Um catálogo centralizado onde a ativação de serviços é instantânea e previsível.',
		href: '/produtos#sum',
		status: 'GA',
		iconName: 'Layers',
		highlights: [
			'Ativação de serviços com 1 clique no Console',
			'Previsibilidade de faturamento sem surpresas',
			'Controle atômico de dependências e recursos'
		],
		metrics: '100% sob demanda'
	},
	{
		code: 'AEM',
		name: 'Auditoria de Operações',
		tagline: 'Rastreabilidade e compliance contínuo',
		description:
			'Mantenha um registro seguro e inalterável de tudo que acontece na sua organização, garantindo conformidade com regulações e total transparência.',
		href: '/produtos#aem',
		status: 'GA',
		iconName: 'FileText',
		highlights: [
			'Registro seguro (append-only) de cada operação',
			'Garantia criptográfica anti-violação',
			'Histórico detalhado por usuário e organização'
		],
		metrics: 'Auditoria contínua'
	},
	{
		code: 'ODM',
		name: 'Observabilidade Integrada',
		tagline: 'Visibilidade total da sua aplicação',
		description:
			'Acompanhe a saúde dos seus sistemas com logs, métricas e alertas em tempo real. Tudo baseado em padrões abertos, para você nunca ficar preso.',
		href: '/produtos#odm',
		status: 'GA',
		iconName: 'Activity',
		highlights: [
			'Compatível com padrão aberto OpenTelemetry',
			'Proteção automática de dados sensíveis (redação de logs)',
			'Monitoramento contínuo de saúde dos componentes'
		],
		metrics: 'Padrão aberto OTel'
	}
];

export const PILLARS = [
	{
		title: 'Produtos Prontos para Produção',
		description:
			'A plataforma Smarkee oferece módulos completos e integrados, projetados para entregar valor imediato sem precisar de configurações exaustivas.'
	},
	{
		title: 'Foco na Operação (Sem Lock-in)',
		description:
			'Desenvolva em padrões abertos. Nossa plataforma apoia o seu crescimento usando ferramentas como OpenTelemetry e infraestrutura não-proprietária.'
	},
	{
		title: 'Catálogo de Serviços Integrado',
		description:
			'De identidade a auditoria, ative capacidades sob demanda. A plataforma cuida da complexidade, você cuida do crescimento do produto.'
	},
	{
		title: 'Segurança por Padrão',
		description:
			'Seus dados são protegidos por arquiteturas avançadas, com mascaramento automático e rastreabilidade rigorosa de todos os acessos.'
	}
];
