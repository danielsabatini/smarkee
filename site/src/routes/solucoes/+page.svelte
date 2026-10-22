<script lang="ts">
	import { CheckCircle2, Lock, Network, Server } from 'lucide-svelte';
</script>

<svelte:head>
	<title>Soluções de Nuvem Corporativa — Smarkee IT Solutions</title>
	<meta
		name="description"
		content="Casos de uso da Smarkee IT Solutions: Internal Developer Platform (IDP), Ambientes Multi-tenant seguros e Governança Regulatória Contínua."
	/>
</svelte:head>

<div class="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
	<div class="mx-auto max-w-3xl text-center">
		<span class="text-xs font-semibold uppercase tracking-wider text-emerald-400">
			Casos de Uso Corporativos
		</span>
		<h1 class="mt-2 text-3xl font-extrabold tracking-tight text-white sm:text-5xl">
			Soluções Construídas para Escala e Resiliência
		</h1>
		<p class="mt-4 text-sm leading-relaxed text-slate-400 sm:text-base">
			Como grandes equipes e organizações utilizam a Smarkee para simplificar a operação de nuvem,
			garantir conformidade automática e acelerar a entrega de valor.
		</p>
	</div>

	<div class="mt-16 space-y-12">
		<!-- Solução 1: IDP -->
		<div
			id="idp"
			class="rounded-2xl border border-slate-800 bg-slate-900/40 p-8 sm:p-10 backdrop-blur-md"
		>
			<div class="flex items-center gap-3">
				<div
					class="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-950 border border-emerald-800 text-emerald-400"
				>
					<Server class="h-5 w-5" aria-hidden="true" />
				</div>
				<h2 class="text-xl font-bold text-white">Internal Developer Platform (IDP)</h2>
			</div>
			<p class="mt-4 text-sm leading-relaxed text-slate-300">
				Permita que equipes de produto provisionem e gerenciem recursos com autonomia, dentro de
				guardrails pré-definidos pela engenharia de plataforma. Reduza tickets manuais e acelere o
				time-to-market mantendo segurança inegociável.
			</p>
			<ul class="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 text-xs text-slate-300">
				<li class="flex items-center gap-2">
					<CheckCircle2 class="h-4 w-4 text-emerald-400 shrink-0" aria-hidden="true" />
					<span>Self-service seguro via Console Web ou CLI sk</span>
				</li>
				<li class="flex items-center gap-2">
					<CheckCircle2 class="h-4 w-4 text-emerald-400 shrink-0" aria-hidden="true" />
					<span>Políticas declarativas aplicadas antes da criação</span>
				</li>
				<li class="flex items-center gap-2">
					<CheckCircle2 class="h-4 w-4 text-emerald-400 shrink-0" aria-hidden="true" />
					<span>Isolamento automático de recursos por organização</span>
				</li>
				<li class="flex items-center gap-2">
					<CheckCircle2 class="h-4 w-4 text-emerald-400 shrink-0" aria-hidden="true" />
					<span>Trilha de auditoria completa de cada modificação</span>
				</li>
			</ul>
		</div>

		<!-- Solução 2: Multi-Tenant Cloud -->
		<div
			id="multi-tenant"
			class="rounded-2xl border border-slate-800 bg-slate-900/40 p-8 sm:p-10 backdrop-blur-md"
		>
			<div class="flex items-center gap-3">
				<div
					class="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-950 border border-emerald-800 text-emerald-400"
				>
					<Network class="h-5 w-5" aria-hidden="true" />
				</div>
				<h2 class="text-xl font-bold text-white">Nuvem Multi-Tenant Isolada</h2>
			</div>
			<p class="mt-4 text-sm leading-relaxed text-slate-300">
				Ideal para empresas SaaS e operadoras corporativas que precisam atender múltiplos clientes
				em uma única infraestrutura sem risco de vazamento de contexto ou acesso indevido.
			</p>
			<ul class="mt-6 grid grid-cols-1 gap-3 sm:grid-cols-2 text-xs text-slate-300">
				<li class="flex items-center gap-2">
					<CheckCircle2 class="h-4 w-4 text-emerald-400 shrink-0" aria-hidden="true" />
					<span>Federação OIDC com delimitação estrita por tenant</span>
				</li>
				<li class="flex items-center gap-2">
					<CheckCircle2 class="h-4 w-4 text-emerald-400 shrink-0" aria-hidden="true" />
					<span>Troca de contexto no Console sem persistência de estado anterior</span>
				</li>
				<li class="flex items-center gap-2">
					<CheckCircle2 class="h-4 w-4 text-emerald-400 shrink-0" aria-hidden="true" />
					<span>Métricas e telemetria segregadas por identificador de tenant</span>
				</li>
				<li class="flex items-center gap-2">
					<CheckCircle2 class="h-4 w-4 text-emerald-400 shrink-0" aria-hidden="true" />
					<span>Proteção contra deleção acidental com confirmação explícita</span>
				</li>
			</ul>
		</div>

		<!-- Solução 3: Governança & Auditoria -->
		<div
			id="governanca"
			class="rounded-2xl border border-slate-800 bg-slate-900/40 p-8 sm:p-10 backdrop-blur-md"
		>
			<div class="flex items-center gap-3">
				<div
					class="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-950 border border-emerald-800 text-emerald-400"
				>
					<Lock class="h-5 w-5" aria-hidden="true" />
				</div>
				<h2 class="text-xl font-bold text-white">Governança e Auditoria Contínua</h2>
			</div>
			<p class="mt-4 text-sm leading-relaxed text-slate-300">
				Conformidade regulatória (LGPD, GDPR, SOC2) simplificada. Toda alteração de estado no
				Smarkee possui carimbo de tempo ISO, autor, identificador de operação e digest criptográfico
				do payload.
			</p>
		</div>
	</div>
</div>
