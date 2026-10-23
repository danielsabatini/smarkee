export interface BlogPost {
	slug: string;
	title: string;
	summary: string;
	date: string;
	readTimeMinutes: number;
	author: {
		name: string;
		role: string;
		avatar: string;
	};
	category:
		| 'Engenharia de Plataforma'
		| 'Segurança e Identidade'
		| 'Observabilidade'
		| 'Arquitetura';
	tags: string[];
	featured?: boolean;
	content: string;
}

export const BLOG_POSTS: BlogPost[] = [
	{
		slug: 'simplificando-a-gestao-de-produtos-na-smarkee',
		title: 'Por que a Smarkee foca na simplicidade de gestão de produtos',
		summary:
			'Descubra como nossa plataforma remove a complexidade da infraestrutura e permite que seu time foque exclusivamente no crescimento e na evolução do seu negócio.',
		date: '2026-10-20',
		readTimeMinutes: 5,
		category: 'Engenharia de Plataforma',
		featured: true,
		tags: ['Gestão', 'Simplicidade', 'Produto', 'Eficiência'],
		author: {
			name: 'Equipe de Produto Smarkee',
			role: 'Product Management',
			avatar: '/brand/s-small.png'
		},
		content: `
## O Desafio da Complexidade Operacional

Na maioria das plataformas tradicionais, uma grande parte do tempo da equipe técnica é consumida por tarefas operacionais repetitivas e gerenciamento de servidores. Se a sua empresa quer crescer rápido, gastar energia com configurações de baixo nível é um obstáculo significativo.

Na **Smarkee**, acreditamos que a tecnologia deve ser um facilitador invisível, não uma barreira.

## Foco no Seu Negócio, Não na Infraestrutura

O coração da Smarkee é permitir que os times de desenvolvimento se preocupem apenas com as funcionalidades que agregam valor aos clientes. Nós entregamos um ecossistema integrado que oferece:

1. **Agilidade:** Provisionamento e configuração em poucos cliques ou através de uma CLI intuitiva.
2. **Segurança:** Controles de acesso nativos e protegidos por padrão.
3. **Visibilidade:** Você sempre sabe exatamente como seus serviços estão performando, sem precisar configurar integrações complexas.

## Menos Ferramentas, Mais Produtividade

Com os módulos integrados da Smarkee, você não precisa assinar múltiplas plataformas diferentes de identidade, auditoria, monitoramento e hospedagem. Tudo funciona perfeitamente em conjunto desde o primeiro dia.
		`
	},
	{
		slug: 'menor-privilegio-multi-tenant-com-ipm-e-oidc',
		title: 'Controle de Acesso com Menor Privilégio em Ambientes Multi-Tenant',
		summary:
			'Uma análise prática sobre como o Smarkee IPM orquestra federação OIDC com PKCE público, projetos isolados e permissões granulares por organização sem vazamento de dados.',
		date: '2026-10-18',
		readTimeMinutes: 5,
		category: 'Segurança e Identidade',
		featured: false,
		tags: ['IPM', 'OIDC', 'Zitadel', 'Multi-tenant', 'Segurança'],
		author: {
			name: 'Segurança de Infraestrutura',
			role: 'Security & Identity Architect',
			avatar: '/brand/s-small.png'
		},
		content: `
## Segurança Nunca É uma Etapa Posterior

Segurança é o primeiro e mais inegociável pilar na Smarkee. Plataformas em nuvem que deixam a segregação de dados para camadas superficiais de aplicação acabam sofrendo com incidentes de vazamento lateral ou escalada de privilégios.

O módulo **IPM (Identity Provider Manager)** da Smarkee foi projetado desde o primeiro rascunho com o conceito de **Zero Trust** e **Menor Privilégio Estrito**.

## Como o IPM Segrega Organizações

Cada organização criada no Smarkee possui seu próprio identificador imutável e uma demarcação de contexto rigorosa:

* **Conta Titular (\`core.account\`):** O vínculo mestre do cliente na plataforma.
* **Organização (\`ipm.organization\`):** O contêiner de tenant isolado.
* **Usuário da Organização (\`ipm.user\`):** Membros convidados que recebem papéis restritos exclusivamente àquela organização.

\`\`\`bash
# Listando usuários com escopo explícito na CLI sk
sk ipm user list --organization 0199c8a4-8a01-7b01-9c01-1a2b3c4d5e01
\`\`\`

## Federação com PKCE Público

Para o Smarkee Console, utilizamos o fluxo **Authorization Code com PKCE (Proof Key for Code Exchange)**. Nenhum secret de cliente é mantido no navegador do usuário, e todos os tokens de acesso possuem curta duração, renovados transparentemente através de canais seguros.
		`
	},
	{
		slug: 'observabilidade-sem-lock-in-com-opentelemetry-odm',
		title: 'Observabilidade Moderna sem Lock-in: A Abordagem do Smarkee ODM',
		summary:
			'Unificando logs estruturados, métricas de taxa/erro/duração e traces distribuídos usando especificações semânticas abertas da CNCF.',
		date: '2026-10-15',
		readTimeMinutes: 6,
		category: 'Observabilidade',
		featured: false,
		tags: ['ODM', 'OpenTelemetry', 'OTel', 'Logs', 'Traces'],
		author: {
			name: 'Engenharia de Observabilidade',
			role: 'Observability Specialist',
			avatar: '/brand/s-small.png'
		},
		content: `
## Por Que Evitar Formatos Proprietários de Telemetria?

Tradicionalmente, contratar um provedor de nuvem ou SaaS de APM significava reescrever todos os seus agentes de coleta e formatadores de log para casar com bibliotecas proprietárias. Se você decidisse mudar de ferramenta, o custo de migração era proibitivo.

O módulo **ODM (Observability Data Manager)** da Smarkee adota o padrão **OpenTelemetry (OTel)** como fonte de verdade em toda a pilha.

## Os Três Pilares da Observabilidade no ODM

1. **Logs Estruturados em JSON:** Cada linha de log emitida por qualquer microsserviço ou worker do Smarkee carrega atributos canônicos: \`timestamp\`, \`level\`, \`service.name\`, \`trace_id\`, \`span_id\` e contexto de recurso.
2. **Métricas RED e USE:** Taxa de requisições (Rate), erros (Errors) e latência percentílica (Duration), além de utilização e saturação de componentes.
3. **Traces Distribuídos:** Propagação de contexto W3C Trace Context através de todas as bordas: do Console Web até a mensageria assíncrona do NATS e o banco de dados.
		`
	}
];
