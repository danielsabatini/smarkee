<script lang="ts">
	import { Activity, ArrowUpRight, FileText, Layers, ShieldCheck, Terminal } from 'lucide-svelte';
</script>

<svelte:head>
	<title>Módulos & Capacidades de Nuvem — Smarkee IT Solutions</title>
	<meta
		name="description"
		content="Conheça os módulos centrais da Smarkee IT Solutions: IPM (Identidade), SUM (Catálogo & Habilitação), AEM (Auditoria), ODM (Observabilidade) e a CLI sk."
	/>
</svelte:head>

<div class="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
	<!-- Hero da Seção de Produtos -->
	<div class="mx-auto max-w-3xl text-center">
		<span class="text-xs font-semibold uppercase tracking-wider text-emerald-400">
			Capacidades de Plataforma
		</span>
		<h1 class="mt-2 text-3xl font-extrabold tracking-tight text-white sm:text-5xl">
			Arquitetura Modular Declarativa
		</h1>
		<p class="mt-4 text-sm leading-relaxed text-slate-400 sm:text-base">
			Cada módulo opera com limites de domínio estritos, contratos JSON Schema versionados (V1) e
			integração contínua através do barramento de eventos NATS JetStream.
		</p>
	</div>

	<!-- Módulos Detalhados -->
	<div class="mt-16 space-y-16">
		<!-- IPM -->
		<section
			id="ipm"
			class="rounded-2xl border border-slate-800 bg-slate-900/40 p-8 sm:p-10 backdrop-blur-md"
		>
			<div class="flex flex-wrap items-center justify-between gap-4">
				<div class="flex items-center gap-3">
					<div
						class="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-950 border border-emerald-800 text-emerald-400"
					>
						<ShieldCheck class="h-6 w-6" aria-hidden="true" />
					</div>
					<div>
						<div class="flex items-center gap-2">
							<h2 class="text-xl font-bold text-white">IPM — Identity Provider Manager</h2>
							<span
								class="rounded bg-emerald-950 px-2 py-0.5 font-mono text-[10px] text-emerald-300 border border-emerald-800"
								>GA</span
							>
						</div>
						<p class="text-xs text-slate-400">
							Gestão de Identidades, Organizações e Controle de Acesso
						</p>
					</div>
				</div>

				<a
					href="http://localhost:5173/identity/organizations"
					target="_blank"
					rel="noreferrer"
					class="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-500 transition"
				>
					<span>Abrir IPM no Console</span>
					<ArrowUpRight class="h-3.5 w-3.5" aria-hidden="true" />
				</a>
			</div>

			<p class="mt-6 text-sm text-slate-300 leading-relaxed">
				O IPM é o guardião de identidade da nuvem Smarkee. Ele oferece federação OIDC moderna
				através do Zitadel, suportando autenticação baseada em PKCE público para clientes web e SPA
				sem retenção de segredos no navegador. Com isolamento multi-tenant real, organizações e
				contas são estritamente particionadas.
			</p>

			<div class="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
				<div class="rounded-xl border border-slate-800/80 bg-slate-950 p-4">
					<h3 class="text-xs font-bold text-white">Organizações Multi-Tenant</h3>
					<p class="mt-1 text-[11px] text-slate-400">
						Cada organização é um contêiner administrativo isolado com ciclo de vida gerenciado.
					</p>
				</div>
				<div class="rounded-xl border border-slate-800/80 bg-slate-950 p-4">
					<h3 class="text-xs font-bold text-white">Menor Privilégio Estrito</h3>
					<p class="mt-1 text-[11px] text-slate-400">
						Papéis e escopos granulares atribuídos exclusivamente às necessidades de cada membro.
					</p>
				</div>
				<div class="rounded-xl border border-slate-800/80 bg-slate-950 p-4">
					<h3 class="text-xs font-bold text-white">Mascaramento de Dados</h3>
					<p class="mt-1 text-[11px] text-slate-400">
						E-mails e dados de contato mascarados por padrão para prevenir exfiltração inadvertida.
					</p>
				</div>
			</div>
		</section>

		<!-- SUM -->
		<section
			id="sum"
			class="rounded-2xl border border-slate-800 bg-slate-900/40 p-8 sm:p-10 backdrop-blur-md"
		>
			<div class="flex flex-wrap items-center justify-between gap-4">
				<div class="flex items-center gap-3">
					<div
						class="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-950 border border-emerald-800 text-emerald-400"
					>
						<Layers class="h-6 w-6" aria-hidden="true" />
					</div>
					<div>
						<div class="flex items-center gap-2">
							<h2 class="text-xl font-bold text-white">SUM — Service Usage Manager</h2>
							<span
								class="rounded bg-emerald-950 px-2 py-0.5 font-mono text-[10px] text-emerald-300 border border-emerald-800"
								>GA</span
							>
						</div>
						<p class="text-xs text-slate-400">
							Habilitação Declarativa e Catálogo Unificado de Serviços
						</p>
					</div>
				</div>

				<a
					href="http://localhost:5173/services/catalog"
					target="_blank"
					rel="noreferrer"
					class="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-500 transition"
				>
					<span>Abrir SUM no Console</span>
					<ArrowUpRight class="h-3.5 w-3.5" aria-hidden="true" />
				</a>
			</div>

			<p class="mt-6 text-sm text-slate-300 leading-relaxed">
				O SUM gerencia a ativação granular de serviços da plataforma para cada organização. Em vez
				de disponibilizar tudo de forma estática e insegura, o SUM exige habilitação declarativa (<code
					class="font-mono text-emerald-400">lifecycle: present</code
				>). Ao habilitar um serviço, o SUM dispara a concessão atômica de roles correspondentes.
			</p>
		</section>

		<!-- AEM -->
		<section
			id="aem"
			class="rounded-2xl border border-slate-800 bg-slate-900/40 p-8 sm:p-10 backdrop-blur-md"
		>
			<div class="flex flex-wrap items-center justify-between gap-4">
				<div class="flex items-center gap-3">
					<div
						class="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-950 border border-blue-800 text-blue-400"
					>
						<FileText class="h-6 w-6" aria-hidden="true" />
					</div>
					<div>
						<div class="flex items-center gap-2">
							<h2 class="text-xl font-bold text-white">AEM — Audit Event Manager</h2>
							<span
								class="rounded bg-blue-950 px-2 py-0.5 font-mono text-[10px] text-blue-300 border border-blue-800"
								>Preview</span
							>
						</div>
						<p class="text-xs text-slate-400">
							Rastreabilidade Imutável e Conformidade Regulatória
						</p>
					</div>
				</div>

				<a
					href="http://localhost:5173/audit/events"
					target="_blank"
					rel="noreferrer"
					class="inline-flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-900 px-4 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 transition"
				>
					<span>Explorar AEM Preview</span>
					<ArrowUpRight class="h-3.5 w-3.5" aria-hidden="true" />
				</a>
			</div>

			<p class="mt-6 text-sm text-slate-300 leading-relaxed">
				Toda operação disparada na Smarkee recebe um registro de auditoria imutável (append-only),
				com SHA-256 digest do payload original da requisição, identificador do operador autenticado,
				carimbo de data/hora ISO e resultado da reconciliação.
			</p>
		</section>

		<!-- ODM -->
		<section
			id="odm"
			class="rounded-2xl border border-slate-800 bg-slate-900/40 p-8 sm:p-10 backdrop-blur-md"
		>
			<div class="flex flex-wrap items-center justify-between gap-4">
				<div class="flex items-center gap-3">
					<div
						class="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-950 border border-blue-800 text-blue-400"
					>
						<Activity class="h-6 w-6" aria-hidden="true" />
					</div>
					<div>
						<div class="flex items-center gap-2">
							<h2 class="text-xl font-bold text-white">ODM — Observability Data Manager</h2>
							<span
								class="rounded bg-blue-950 px-2 py-0.5 font-mono text-[10px] text-blue-300 border border-blue-800"
								>Preview</span
							>
						</div>
						<p class="text-xs text-slate-400">Telemetria Aberta, Métricas e Traces OpenTelemetry</p>
					</div>
				</div>

				<a
					href="http://localhost:5173/observability/logs"
					target="_blank"
					rel="noreferrer"
					class="inline-flex items-center gap-1.5 rounded-xl border border-slate-700 bg-slate-900 px-4 py-2 text-xs font-semibold text-slate-200 hover:bg-slate-800 transition"
				>
					<span>Explorar ODM Preview</span>
					<ArrowUpRight class="h-3.5 w-3.5" aria-hidden="true" />
				</a>
			</div>

			<p class="mt-6 text-sm text-slate-300 leading-relaxed">
				Construído sem tecnologias proprietárias, o ODM agrega logs em JSON estruturado, métricas
				RED/USE e rastreamento distribuído W3C. Integrável com Prometheus, Grafana, OpenSearch e
				coletores OpenTelemetry padrão.
			</p>
		</section>

		<!-- CLI sk -->
		<section
			id="cli"
			class="rounded-2xl border border-emerald-900/40 bg-slate-900/40 p-8 sm:p-10 backdrop-blur-md"
		>
			<div class="flex items-center gap-3">
				<div
					class="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-950 border border-emerald-800 text-emerald-400"
				>
					<Terminal class="h-6 w-6" aria-hidden="true" />
				</div>
				<div>
					<h2 class="text-xl font-bold text-white">
						CLI Smarkee (<code class="font-mono text-emerald-400">sk</code>)
					</h2>
					<p class="text-xs text-slate-400">
						A ferramenta definitiva para desenvolvedores e automação em CI/CD
					</p>
				</div>
			</div>

			<p class="mt-6 text-sm text-slate-300 leading-relaxed">
				A CLI oficial <code class="font-mono text-emerald-400">sk</code> foi projetada em inglês para
				consistência com ecossistemas UNIX, oferecendo login automático com PKCE via navegador local,
				suporte a contextos de organização, saída formatada em tabela, JSON ou YAML, e integração sem
				fricção com esteiras de implantação contínua.
			</p>

			<div
				class="mt-6 rounded-xl bg-slate-950 p-4 font-mono text-xs text-slate-300 overflow-x-auto"
			>
				<pre><code
						># Instalação rápida e verificação de versão
sk --version

# Autenticação interativa com PKCE
sk login

# Listagem de organizações no tenant ativo
sk ipm org list

# Habilitação do módulo IPM
sk sum enable ipm</code
					></pre>
			</div>
		</section>
	</div>
</div>
