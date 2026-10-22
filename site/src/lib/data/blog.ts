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
		slug: 'reconciliacao-continua-o-loop-declarativo-na-smarkee',
		title: 'Por que a Smarkee adota o modelo de Reconciliação Contínua em Nuvem',
		summary:
			'Como o desacoplamento entre intenção (Desired State) e realidade (Observed State) resolve de ponta a ponta as fragilidades de chamadas síncronas e provisionamentos tradicionais.',
		date: '2026-10-20',
		readTimeMinutes: 7,
		category: 'Engenharia de Plataforma',
		featured: true,
		tags: ['Control Loop', 'Kubernetes-like', 'NATS JetStream', 'Arquitetura'],
		author: {
			name: 'Equipe de Plataforma Smarkee',
			role: 'Platform & Infrastructure Engineering',
			avatar: '/brand/s-small.png'
		},
		content: `
## O Desafio dos Ambientes de Nuvem Tradicionais

Na maioria das plataformas e esteiras de automação de nuvem, uma requisição de provisionamento é síncrona ou parcialmente bloqueante. Se um timeout de rede acontece no meio do caminho, ou se um serviço terceiro responde com erro transitório, o operador se depara com estados fantasmas: o recurso foi criado pela metade? Pode ser reexecutado sem gerar duplicidade?

Na **Smarkee IT Solutions**, nós adotamos o princípio fundamental de **Sistemas Distribuídos e Idempotência** inspirado nos controladores mais resilientes do mundo (como o ecossistema Kubernetes).

## Intenção (Desired) versus Realidade (Observed)

O coração da Smarkee é o desacoplamento formal entre dois contratos estritos:

1. **Estado Desejado (\`desired\`):** O que o usuário ou sistema declarou que quer que exista (ex.: uma nova Organização com determinado nome e proteção contra exclusão).
2. **Estado Observado (\`observed\`):** O que os subsistemas e controladores realmente inspecionaram e validaram em produção.

Quando uma alteração é enviada via API REST, CLI ou Console, ela nunca tenta "fazer tudo na hora". A API valida o schema da solicitação e responde imediatamente com **HTTP 202 Accepted** acompanhado de um identificador rastreável da operação (\`operationId\`).

\`\`\`json
{
  "operationId": "0199c8d0-9900-7a00-8b00-112233445566",
  "operationType": "create",
  "resourceType": "organization",
  "operationStatus": "accepted"
}
\`\`\`

## O Papel do NATS JetStream e Reconciliação Concorrente

A solicitação é persistida no Single Source of Truth (PostgreSQL) e um evento é emitido na stream durável do **NATS JetStream**. O controlador dedicado do módulo (como o Receiver do IPM) consome o evento e orquestra a transição de estado:

* **Pending / Reconciling:** O controlador verifica as pré-condições, invoca os provedores (como o IdP corporativo) e prepara os recursos.
* **Ready:** O estado observado alcança a geração desejada (\`observedGeneration == desiredGeneration\`). A condição \`Ready = True\` é carimbada com timestamp ISO e o recurso passa a responder prontamente.

Se houver uma pane de servidor, o controlador simplesmente retoma a mensagem a partir da stream persistente, garantindo idempotência perfeita sem duplicação de dados.
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
