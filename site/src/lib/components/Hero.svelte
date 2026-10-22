<script lang="ts">
	import {
		ArrowRight,
		ArrowUpRight,
		CheckCircle2,
		Cpu,
		ShieldCheck,
		Terminal
	} from 'lucide-svelte';
</script>

<section class="relative overflow-hidden pt-12 pb-20 sm:pt-20 sm:pb-28">
	<!-- Efeitos Visuais de Fundo -->
	<div class="pointer-events-none absolute inset-0 -z-10 grid-pattern opacity-40"></div>
	<div
		class="pointer-events-none absolute top-1/4 left-1/2 -z-10 h-96 w-96 -translate-x-1/2 -translate-y-1/2 rounded-full glow-emerald blur-3xl"
	></div>

	<div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
		<div class="mx-auto max-w-4xl text-center">
			<!-- Badge de Lançamento / Arquitetura -->
			<div
				class="inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-950/40 px-3.5 py-1 text-xs text-emerald-300 backdrop-blur-md"
			>
				<span class="flex h-2 w-2 rounded-full bg-emerald-400 animate-pulse"></span>
				<span class="font-medium">Smarkee Cloud Architecture</span>
				<span class="text-emerald-500">•</span>
				<span class="text-emerald-200">Reconciliação Declarativa Ativa</span>
			</div>

			<!-- Título Principal -->
			<h1 class="mt-6 text-3xl font-extrabold tracking-tight text-white sm:text-5xl lg:text-6xl">
				A Plataforma de Nuvem que Reconcilia
				<span
					class="block bg-gradient-to-r from-emerald-400 via-teal-300 to-emerald-500 bg-clip-text text-transparent"
				>
					Intenção em Realidade
				</span>
			</h1>

			<!-- Subtítulo -->
			<p class="mx-auto mt-6 max-w-2xl text-base leading-relaxed text-slate-300 sm:text-lg">
				Controle de identidade multi-tenant (<strong>IPM</strong>), habilitação sob demanda (<strong
					>SUM</strong
				>), auditoria imutável (<strong>AEM</strong>) e observabilidade aberta (<strong>ODM</strong
				>) unificados por contratos declarativos e confirmação assíncrona HTTP 202.
			</p>

			<!-- Botões de Ação -->
			<div class="mt-8 flex flex-wrap items-center justify-center gap-3">
				<a
					href="http://localhost:5173"
					target="_blank"
					rel="noreferrer"
					class="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-6 py-3 text-sm font-semibold text-white shadow-lg shadow-emerald-950/50 transition hover:bg-emerald-500 hover:shadow-emerald-900/60"
				>
					<span>Entrar no Console</span>
					<ArrowUpRight class="h-4 w-4" aria-hidden="true" />
				</a>

				<a
					href="#loop-de-controle"
					class="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900/80 px-5 py-3 text-sm font-semibold text-slate-200 backdrop-blur-md transition hover:border-slate-600 hover:bg-slate-800"
				>
					<span>Ver Loop de Controle</span>
					<ArrowRight class="h-4 w-4 text-slate-400" aria-hidden="true" />
				</a>

				<a
					href="/produtos#cli"
					class="inline-flex items-center gap-2 rounded-xl border border-slate-800 bg-slate-950/60 px-5 py-3 text-sm font-semibold text-slate-300 transition hover:border-slate-700 hover:text-white"
				>
					<Terminal class="h-4 w-4 text-emerald-400" aria-hidden="true" />
					<span>CLI sk</span>
				</a>
			</div>

			<!-- Indicadores de Confiança / Pilares -->
			<div
				class="mt-12 flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-xs text-slate-400"
			>
				<div class="flex items-center gap-1.5">
					<CheckCircle2 class="h-4 w-4 text-emerald-400" aria-hidden="true" />
					<span>HTTP 202 Accepted & Assíncrono</span>
				</div>
				<div class="flex items-center gap-1.5">
					<ShieldCheck class="h-4 w-4 text-emerald-400" aria-hidden="true" />
					<span>OIDC & Zero Secrets no Browser</span>
				</div>
				<div class="flex items-center gap-1.5">
					<Cpu class="h-4 w-4 text-emerald-400" aria-hidden="true" />
					<span>NATS JetStream & Event-driven</span>
				</div>
			</div>
		</div>

		<!-- Preview Interativo do Console e Loop de Controle -->
		<div
			class="relative mt-14 rounded-2xl border border-slate-800 bg-slate-900/40 p-2 shadow-2xl backdrop-blur-xl sm:p-4"
		>
			<div class="flex items-center justify-between border-b border-slate-800/80 pb-3 px-3">
				<div class="flex items-center gap-2">
					<span class="h-3 w-3 rounded-full bg-red-500/80"></span>
					<span class="h-3 w-3 rounded-full bg-amber-500/80"></span>
					<span class="h-3 w-3 rounded-full bg-emerald-500/80"></span>
					<span class="ml-2 font-mono text-[11px] text-slate-400"
						>console.smarkee.internal • Estado Ativo</span
					>
				</div>
				<div class="hidden sm:flex items-center gap-2 text-[11px] text-emerald-400">
					<span class="h-1.5 w-1.5 rounded-full bg-emerald-400 animate-ping"></span>
					<span>Reconciliação Contínua • Ready (True)</span>
				</div>
			</div>

			<!-- Mock da Janela do Console -->
			<div class="overflow-hidden rounded-xl bg-slate-950 p-4 sm:p-6">
				<div class="grid grid-cols-1 gap-4 md:grid-cols-4">
					<!-- Card 1: IPM -->
					<div class="rounded-xl border border-slate-800/80 bg-slate-900/50 p-4">
						<div class="flex items-center justify-between">
							<span class="font-mono text-xs font-bold text-emerald-400">IPM</span>
							<span
								class="rounded bg-emerald-950/80 px-1.5 py-0.5 font-mono text-[10px] text-emerald-300"
								>Ready</span
							>
						</div>
						<p class="mt-2 text-xs font-semibold text-white">Identity Provider Manager</p>
						<p class="mt-1 text-[11px] text-slate-400">
							Organizações, Contas e Usuários com menor privilégio.
						</p>
					</div>

					<!-- Card 2: SUM -->
					<div class="rounded-xl border border-slate-800/80 bg-slate-900/50 p-4">
						<div class="flex items-center justify-between">
							<span class="font-mono text-xs font-bold text-emerald-400">SUM</span>
							<span
								class="rounded bg-emerald-950/80 px-1.5 py-0.5 font-mono text-[10px] text-emerald-300"
								>Ready</span
							>
						</div>
						<p class="mt-2 text-xs font-semibold text-white">Service Usage Manager</p>
						<p class="mt-1 text-[11px] text-slate-400">
							Habilitação declarativa e catálogo de serviços vinculados.
						</p>
					</div>

					<!-- Card 3: AEM -->
					<div class="rounded-xl border border-slate-800/80 bg-slate-900/50 p-4">
						<div class="flex items-center justify-between">
							<span class="font-mono text-xs font-bold text-emerald-400">AEM</span>
							<span class="rounded bg-blue-950/80 px-1.5 py-0.5 font-mono text-[10px] text-blue-300"
								>Preview</span
							>
						</div>
						<p class="mt-2 text-xs font-semibold text-white">Audit Event Manager</p>
						<p class="mt-1 text-[11px] text-slate-400">
							Registro imutável de operações e digests criptográficos.
						</p>
					</div>

					<!-- Card 4: ODM -->
					<div class="rounded-xl border border-slate-800/80 bg-slate-900/50 p-4">
						<div class="flex items-center justify-between">
							<span class="font-mono text-xs font-bold text-emerald-400">ODM</span>
							<span class="rounded bg-blue-950/80 px-1.5 py-0.5 font-mono text-[10px] text-blue-300"
								>Preview</span
							>
						</div>
						<p class="mt-2 text-xs font-semibold text-white">Observability Data Manager</p>
						<p class="mt-1 text-[11px] text-slate-400">
							Logs estruturados, métricas e traces em padrão OpenTelemetry.
						</p>
					</div>
				</div>

				<!-- Barra de reconciliação em tempo real -->
				<div
					class="mt-4 flex flex-col items-start justify-between gap-3 rounded-lg border border-slate-800 bg-slate-900/30 p-3 sm:flex-row sm:items-center"
				>
					<div class="flex items-center gap-2">
						<span class="font-mono text-xs text-slate-300">Intenção Declarativa</span>
						<span class="font-mono text-xs text-slate-500">→</span>
						<span
							class="rounded border border-emerald-500/30 bg-emerald-950/50 px-2 py-0.5 font-mono text-xs text-emerald-300"
						>
							202 Accepted
						</span>
						<span class="font-mono text-xs text-slate-500">→</span>
						<span class="font-mono text-xs text-slate-300">NATS JetStream</span>
						<span class="font-mono text-xs text-slate-500">→</span>
						<span class="font-mono text-xs font-bold text-emerald-400">Ready: True</span>
					</div>
					<span class="font-mono text-[11px] text-slate-500">Idempotência garantida</span>
				</div>
			</div>
		</div>
	</div>
</section>
