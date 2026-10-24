<script lang="ts">
	import { Activity, ArrowUpRight, FileText, Layers, ShieldCheck, Terminal } from 'lucide-svelte';
	import { CONSOLE_URL } from '$lib/data/platform';
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
		<span class="text-sm font-semibold uppercase tracking-wider text-emerald-700">
			Capacidades de Plataforma
		</span>
		<h1 class="mt-2 text-3xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
			Arquitetura Modular
		</h1>
		<p class="mt-4 text-sm leading-relaxed text-slate-600 sm:text-base">
			Cada módulo foi desenvolvido para entregar capacidades prontas para produção. Segurança,
			isolamento e confiabilidade já estão integrados para que você construa o seu negócio em cima
			deles.
		</p>
	</div>

	<!-- Módulos Detalhados -->
	<div class="mt-16 space-y-16">
		<!-- IPM -->
		<section id="ipm" class="rounded-2xl border border-slate-200 bg-white shadow-sm p-8 sm:p-10">
			<div class="flex flex-wrap items-center justify-between gap-4">
				<div class="flex items-center gap-3">
					<div
						class="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-700"
					>
						<ShieldCheck class="h-6 w-6" aria-hidden="true" />
					</div>
					<div>
						<div class="flex items-center gap-2">
							<h2 class="text-xl font-bold text-slate-900">IPM — Identity Provider Manager</h2>
							<span
								class="rounded bg-emerald-50 px-2 py-0.5 font-mono text-sm text-emerald-800 border border-emerald-200"
								>GA</span
							>
						</div>
						<p class="text-sm text-slate-600">
							Gestão de Identidades, Organizações e Controle de Acesso
						</p>
					</div>
				</div>

				<a
					href="{CONSOLE_URL}/identity/organizations"
					target="_blank"
					rel="noreferrer"
					class="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-slate-900 hover:bg-emerald-700 transition"
				>
					<span>Abrir IPM no Console</span>
					<ArrowUpRight class="h-3.5 w-3.5" aria-hidden="true" />
				</a>
			</div>

			<p class="mt-6 text-sm text-slate-700 leading-relaxed">
				O IPM é o guardião de identidade da nuvem Smarkee. Ele oferece federação OIDC moderna
				através do Zitadel, suportando autenticação baseada em PKCE público para clientes web e SPA
				sem retenção de segredos no navegador. Com isolamento multi-tenant real, organizações e
				contas são estritamente particionadas.
			</p>

			<div class="mt-6 grid grid-cols-1 gap-4 sm:grid-cols-3">
				<div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
					<h3 class="text-sm font-bold text-slate-900">Organizações Multi-Tenant</h3>
					<p class="mt-1 text-sm text-slate-600">
						Cada organização é um contêiner administrativo isolado com ciclo de vida gerenciado.
					</p>
				</div>
				<div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
					<h3 class="text-sm font-bold text-slate-900">Menor Privilégio Estrito</h3>
					<p class="mt-1 text-sm text-slate-600">
						Papéis e escopos granulares atribuídos exclusivamente às necessidades de cada membro.
					</p>
				</div>
				<div class="rounded-xl border border-slate-200 bg-slate-50 p-4">
					<h3 class="text-sm font-bold text-slate-900">Mascaramento de Dados</h3>
					<p class="mt-1 text-sm text-slate-600">
						E-mails e dados de contato mascarados por padrão para prevenir exfiltração inadvertida.
					</p>
				</div>
			</div>
		</section>

		<!-- SUM -->
		<section id="sum" class="rounded-2xl border border-slate-200 bg-white shadow-sm p-8 sm:p-10">
			<div class="flex flex-wrap items-center justify-between gap-4">
				<div class="flex items-center gap-3">
					<div
						class="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-700"
					>
						<Layers class="h-6 w-6" aria-hidden="true" />
					</div>
					<div>
						<div class="flex items-center gap-2">
							<h2 class="text-xl font-bold text-slate-900">SUM — Service Usage Manager</h2>
							<span
								class="rounded bg-emerald-50 px-2 py-0.5 font-mono text-sm text-emerald-800 border border-emerald-200"
								>GA</span
							>
						</div>
						<p class="text-sm text-slate-600">
							Habilitação Declarativa e Catálogo Unificado de Serviços
						</p>
					</div>
				</div>

				<a
					href="{CONSOLE_URL}/services/catalog"
					target="_blank"
					rel="noreferrer"
					class="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-slate-900 hover:bg-emerald-700 transition"
				>
					<span>Abrir SUM no Console</span>
					<ArrowUpRight class="h-3.5 w-3.5" aria-hidden="true" />
				</a>
			</div>

			<p class="mt-6 text-sm text-slate-700 leading-relaxed">
				O SUM gerencia a ativação granular de serviços da plataforma para cada organização. Em vez
				de disponibilizar tudo de forma estática e insegura, o SUM exige habilitação declarativa (<code
					class="font-mono text-emerald-700">lifecycle: present</code
				>). Ao habilitar um serviço, o SUM dispara a concessão atômica de roles correspondentes.
			</p>
		</section>

		<!-- AEM -->
		<section id="aem" class="rounded-2xl border border-slate-200 bg-white shadow-sm p-8 sm:p-10">
			<div class="flex flex-wrap items-center justify-between gap-4">
				<div class="flex items-center gap-3">
					<div
						class="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50 border border-blue-200 text-blue-700"
					>
						<FileText class="h-6 w-6" aria-hidden="true" />
					</div>
					<div>
						<div class="flex items-center gap-2">
							<h2 class="text-xl font-bold text-slate-900">AEM — Audit Event Manager</h2>
							<span
								class="rounded bg-blue-50 px-2 py-0.5 font-mono text-sm text-blue-800 border border-blue-200"
								>Preview</span
							>
						</div>
						<p class="text-sm text-slate-600">
							Rastreabilidade Imutável e Conformidade Regulatória
						</p>
					</div>
				</div>

				<a
					href="{CONSOLE_URL}/audit/events"
					target="_blank"
					rel="noreferrer"
					class="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 transition"
				>
					<span>Explorar AEM Preview</span>
					<ArrowUpRight class="h-3.5 w-3.5" aria-hidden="true" />
				</a>
			</div>

			<p class="mt-6 text-sm text-slate-700 leading-relaxed">
				Toda operação disparada na Smarkee recebe um registro de auditoria inalterável. Isso garante
				um histórico transparente sobre quem fez o que e quando, facilitando comprovações de
				compliance regulatório.
			</p>
		</section>

		<!-- ODM -->
		<section id="odm" class="rounded-2xl border border-slate-200 bg-white shadow-sm p-8 sm:p-10">
			<div class="flex flex-wrap items-center justify-between gap-4">
				<div class="flex items-center gap-3">
					<div
						class="flex h-12 w-12 items-center justify-center rounded-xl bg-blue-50 border border-blue-200 text-blue-700"
					>
						<Activity class="h-6 w-6" aria-hidden="true" />
					</div>
					<div>
						<div class="flex items-center gap-2">
							<h2 class="text-xl font-bold text-slate-900">ODM — Observability Data Manager</h2>
							<span
								class="rounded bg-blue-50 px-2 py-0.5 font-mono text-sm text-blue-800 border border-blue-200"
								>Preview</span
							>
						</div>
						<p class="text-sm text-slate-600">Telemetria Aberta, Métricas e Traces OpenTelemetry</p>
					</div>
				</div>

				<a
					href="{CONSOLE_URL}/observability/logs"
					target="_blank"
					rel="noreferrer"
					class="inline-flex items-center gap-1.5 rounded-xl border border-slate-300 bg-white px-4 py-2 text-sm font-semibold text-slate-700 hover:bg-slate-100 transition"
				>
					<span>Explorar ODM Preview</span>
					<ArrowUpRight class="h-3.5 w-3.5" aria-hidden="true" />
				</a>
			</div>

			<p class="mt-6 text-sm text-slate-700 leading-relaxed">
				Construído sem tecnologias proprietárias, o ODM agrega logs em JSON estruturado, métricas
				RED/USE e rastreamento distribuído W3C. Integrável com Prometheus, Grafana, OpenSearch e
				coletores OpenTelemetry padrão.
			</p>
		</section>

		<!-- CLI sk -->
		<section id="cli" class="rounded-2xl border border-emerald-200 bg-white shadow-sm p-8 sm:p-10">
			<div class="flex items-center gap-3">
				<div
					class="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-50 border border-emerald-200 text-emerald-700"
				>
					<Terminal class="h-6 w-6" aria-hidden="true" />
				</div>
				<div>
					<h2 class="text-xl font-bold text-slate-900">
						CLI Smarkee (<code class="font-mono text-emerald-700">sk</code>)
					</h2>
					<p class="text-sm text-slate-600">
						A ferramenta definitiva para desenvolvedores e automação em CI/CD
					</p>
				</div>
			</div>

			<p class="mt-6 text-sm text-slate-700 leading-relaxed">
				A CLI oficial <code class="font-mono text-emerald-700">sk</code> foi projetada em inglês para
				consistência com ecossistemas UNIX, oferecendo login automático com PKCE via navegador local,
				suporte a contextos de organização, saída formatada em tabela, JSON ou YAML, e integração sem
				fricção com esteiras de implantação contínua.
			</p>

			<div class="mt-6 rounded-xl bg-slate-50 p-4 font-mono text-sm text-slate-700 overflow-x-auto">
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
