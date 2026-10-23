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

<section class="relative overflow-hidden pt-12 pb-20 sm:pt-20 sm:pb-28 bg-slate-50">
	<!-- Efeitos Visuais de Fundo Sutis -->
	<div class="pointer-events-none absolute inset-0 -z-10 grid-pattern opacity-60"></div>
	<div
		class="pointer-events-none absolute top-1/4 left-1/2 -z-10 h-96 w-96 -translate-x-1/2 -translate-y-1/2 rounded-full glow-emerald blur-3xl"
	></div>

	<div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
		<div class="mx-auto max-w-4xl text-center">
			<!-- Badge de Lançamento / Arquitetura -->
			<div
				class="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3.5 py-1 text-xs text-emerald-800 shadow-2xs"
			>
				<span class="flex h-2 w-2 rounded-full bg-emerald-600 animate-pulse"></span>
				<span class="font-medium">Smarkee Cloud Architecture</span>
				<span class="text-emerald-400">•</span>
				<span class="font-semibold text-emerald-900">Reconciliação Declarativa Ativa</span>
			</div>

			<!-- Título Principal -->
			<h1
				class="mt-6 text-3xl font-extrabold tracking-tight text-slate-900 sm:text-5xl lg:text-6xl"
			>
				A Nuvem Brasileira
				<span
					class="block bg-gradient-to-r from-emerald-700 via-emerald-600 to-teal-700 bg-clip-text text-transparent"
				>
					Simples, Segura e Previsível
				</span>
			</h1>

			<!-- Subtítulo -->
			<p class="mx-auto mt-6 max-w-2xl text-base leading-relaxed text-slate-600 sm:text-lg">
				Hospedagem, controle de acessos, infraestrutura sob demanda e observabilidade integrados em
				uma plataforma robusta. <strong>Fatura previsível em Reais</strong>, sem lock-in e com
				suporte especializado no Brasil.
			</p>

			<!-- Botões de Ação -->
			<div class="mt-8 flex flex-wrap items-center justify-center gap-3">
				<a
					href="http://localhost:5173"
					target="_blank"
					rel="noreferrer"
					class="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-6 py-3 text-sm font-semibold text-white shadow-sm shadow-emerald-700/20 transition hover:bg-emerald-700 hover:shadow-md"
				>
					<span>Entrar no Console</span>
					<ArrowUpRight class="h-4 w-4" aria-hidden="true" />
				</a>

				<a
					href="#loop-de-controle"
					class="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-5 py-3 text-sm font-semibold text-slate-700 shadow-2xs transition hover:border-slate-400 hover:bg-slate-50"
				>
					<span>Ver Loop de Controle</span>
					<ArrowRight class="h-4 w-4 text-slate-500" aria-hidden="true" />
				</a>

				<a
					href="/produtos#cli"
					class="inline-flex items-center gap-2 rounded-xl border border-slate-200 bg-white px-5 py-3 text-sm font-semibold text-slate-700 shadow-2xs transition hover:border-slate-300 hover:bg-slate-50 hover:text-slate-900"
				>
					<Terminal class="h-4 w-4 text-emerald-700" aria-hidden="true" />
					<span>CLI sk</span>
				</a>
			</div>

			<!-- Indicadores de Confiança / Pilares -->
			<div
				class="mt-12 flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-xs text-slate-600"
			>
				<div class="flex items-center gap-1.5 font-medium">
					<CheckCircle2 class="h-4 w-4 text-emerald-600" aria-hidden="true" />
					<span>Sem Custos Ocultos (Em BRL)</span>
				</div>
				<div class="flex items-center gap-1.5 font-medium">
					<ShieldCheck class="h-4 w-4 text-emerald-600" aria-hidden="true" />
					<span>Suporte Especializado Local</span>
				</div>
				<div class="flex items-center gap-1.5 font-medium">
					<Cpu class="h-4 w-4 text-emerald-600" aria-hidden="true" />
					<span>Performance e Segurança Enterprise</span>
				</div>
			</div>
		</div>

		<!-- Preview Interativo do Console e Loop de Controle -->
		<div class="relative mt-14 rounded-2xl border border-slate-200 bg-white p-2 shadow-xl sm:p-4">
			<div class="flex items-center justify-between border-b border-slate-100 pb-3 px-3">
				<div class="flex items-center gap-2">
					<span class="h-3 w-3 rounded-full bg-red-400"></span>
					<span class="h-3 w-3 rounded-full bg-amber-400"></span>
					<span class="h-3 w-3 rounded-full bg-emerald-400"></span>
					<span class="ml-2 font-mono text-[11px] font-medium text-slate-500"
						>console.smarkee.internal • Estado Ativo</span
					>
				</div>
				<div class="hidden sm:flex items-center gap-2 text-[11px] font-semibold text-emerald-800">
					<span class="h-2 w-2 rounded-full bg-emerald-600 animate-ping"></span>
					<span>Reconciliação Contínua • Ready (True)</span>
				</div>
			</div>

			<!-- Mock da Janela do Console (Padrão visual do Console) -->
			<div class="overflow-hidden rounded-xl bg-slate-50 p-4 sm:p-6 border border-slate-100">
				<div class="grid grid-cols-1 gap-4 md:grid-cols-4">
					<!-- Card 1: IPM -->
					<div class="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs">
						<div class="flex items-center justify-between">
							<span class="font-mono text-xs font-bold text-emerald-700">Identidade</span>
							<span
								class="rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-emerald-800"
								>Ativo</span
							>
						</div>
						<p class="mt-2 text-xs font-bold text-slate-900">Gestão de Acessos (IPM)</p>
						<p class="mt-1 text-[11px] text-slate-500">
							Organizações, contas e usuários com menor privilégio por padrão.
						</p>
					</div>

					<!-- Card 2: SUM -->
					<div class="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs">
						<div class="flex items-center justify-between">
							<span class="font-mono text-xs font-bold text-emerald-700">Serviços</span>
							<span
								class="rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-emerald-800"
								>Ativo</span
							>
						</div>
						<p class="mt-2 text-xs font-bold text-slate-900">Recursos sob Demanda</p>
						<p class="mt-1 text-[11px] text-slate-500">
							Habilitação simplificada e catálogo de serviços vinculados.
						</p>
					</div>

					<!-- Card 3: AEM -->
					<div class="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs">
						<div class="flex items-center justify-between">
							<span class="font-mono text-xs font-bold text-emerald-700">Auditoria</span>
							<span
								class="rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-emerald-800"
								>Ativo</span
							>
						</div>
						<p class="mt-2 text-xs font-bold text-slate-900">Registro Imutável</p>
						<p class="mt-1 text-[11px] text-slate-500">
							Segurança e compliance com auditoria nativa das operações.
						</p>
					</div>

					<!-- Card 4: ODM -->
					<div class="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs">
						<div class="flex items-center justify-between">
							<span class="font-mono text-xs font-bold text-emerald-700">Métricas</span>
							<span
								class="rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 font-mono text-[10px] font-semibold text-emerald-800"
								>Ativo</span
							>
						</div>
						<p class="mt-2 text-xs font-bold text-slate-900">Observabilidade (ODM)</p>
						<p class="mt-1 text-[11px] text-slate-500">
							Logs, métricas e monitoramento integrados de ponta a ponta.
						</p>
					</div>
				</div>

				<!-- Barra de reconciliação em tempo real -->
				<div
					class="mt-4 flex flex-col items-start justify-between gap-3 rounded-xl border border-slate-200 bg-white p-3.5 shadow-2xs sm:flex-row sm:items-center"
				>
					<div class="flex items-center gap-2">
						<span class="font-mono text-xs font-medium text-slate-700">Configuração</span>
						<span class="font-mono text-xs text-slate-400">→</span>
						<span
							class="rounded border border-emerald-200 bg-emerald-50 px-2 py-0.5 font-mono text-xs font-bold text-emerald-800"
						>
							Validada
						</span>
						<span class="font-mono text-xs text-slate-400">→</span>
						<span class="font-mono text-xs font-medium text-slate-700">Deploy Ativo</span>
						<span class="font-mono text-xs text-slate-400">→</span>
						<span class="font-mono text-xs font-bold text-emerald-700">Online</span>
					</div>
					<span class="font-mono text-[11px] text-slate-500">Zero tempo de inatividade</span>
				</div>
			</div>
		</div>
	</div>
</section>
