<script lang="ts">
	import { ArrowRight, ArrowUpRight, CheckCircle2, Cpu, ShieldCheck } from 'lucide-svelte';
</script>

<section class="relative overflow-hidden pt-12 pb-20 sm:pt-20 sm:pb-28 bg-slate-50">
	<div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
		<div class="mx-auto max-w-4xl text-center">
			<!-- Badge de Lançamento / Arquitetura -->
			<div
				class="inline-flex items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-3.5 py-1 text-xs text-emerald-800 shadow-2xs"
			>
				<span class="flex h-2 w-2 rounded-full bg-emerald-600 animate-pulse"></span>
				<span class="font-medium">Smarkee Plataforma</span>
				<span class="text-emerald-400">•</span>
				<span class="font-semibold text-emerald-900">Ecossistema Integrado</span>
			</div>

			<!-- Título Principal -->
			<h1
				class="mt-6 text-3xl font-extrabold tracking-tight text-slate-900 sm:text-5xl lg:text-6xl"
			>
				Hospedagem e Gestão
				<span class="block text-emerald-700"> Focada no seu Produto </span>
			</h1>

			<!-- Subtítulo -->
			<p class="mx-auto mt-6 max-w-2xl text-base leading-relaxed text-slate-600 sm:text-lg">
				Controle de acessos, infraestrutura sob demanda e observabilidade integrados em uma suíte
				simples. <strong>Acelere seu desenvolvimento</strong>, sem gastar tempo com operações e
				complexidade de infraestrutura.
			</p>

			<!-- Botões de Ação -->
			<div class="mt-8 flex flex-wrap items-center justify-center gap-4">
				<a
					href="http://localhost:5173"
					target="_blank"
					rel="noreferrer"
					class="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-8 py-3.5 text-sm font-bold text-white shadow-sm shadow-emerald-700/20 transition hover:bg-emerald-700 hover:shadow-md"
				>
					<span>Criar conta gratuita</span>
					<ArrowUpRight class="h-4 w-4" aria-hidden="true" />
				</a>

				<a
					href="#plataforma"
					class="inline-flex items-center gap-2 rounded-xl px-5 py-3 text-sm font-semibold text-slate-600 transition hover:text-slate-900 hover:bg-slate-100"
				>
					<span>Conheça os produtos</span>
					<ArrowRight class="h-4 w-4 text-slate-400" aria-hidden="true" />
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

		<!-- Preview Interativo do Console -->
		<div class="relative mt-14 rounded-2xl border border-slate-200 bg-white p-2 shadow-xl sm:p-4">
			<div class="flex items-center justify-between border-b border-slate-100 pb-3 px-3">
				<div class="flex items-center gap-2">
					<span class="h-3 w-3 rounded-full bg-slate-200"></span>
					<span class="h-3 w-3 rounded-full bg-slate-200"></span>
					<span class="h-3 w-3 rounded-full bg-slate-200"></span>
					<span class="ml-2 font-mono text-xs font-medium text-slate-400"
						>console.smarkee.com.br</span
					>
				</div>
			</div>

			<!-- Mock da Janela do Console (Padrão visual do Console) -->
			<div class="overflow-hidden rounded-xl bg-slate-50 p-4 sm:p-6 border border-slate-100">
				<div class="grid grid-cols-1 gap-4 md:grid-cols-4">
					<!-- Card 1: IPM -->
					<div class="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs">
						<span class="font-mono text-xs font-bold text-slate-800">Identidade</span>
						<p class="mt-2 text-xs font-semibold text-slate-900">Gestão de Acessos</p>
						<p class="mt-1 text-xs text-slate-500">Organizações e usuários.</p>
					</div>

					<!-- Card 2: SUM -->
					<div class="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs">
						<span class="font-mono text-xs font-bold text-slate-800">Serviços</span>
						<p class="mt-2 text-xs font-semibold text-slate-900">Recursos sob Demanda</p>
						<p class="mt-1 text-xs text-slate-500">Habilitação simplificada.</p>
					</div>

					<!-- Card 3: AEM -->
					<div class="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs">
						<span class="font-mono text-xs font-bold text-slate-800">Auditoria</span>
						<p class="mt-2 text-xs font-semibold text-slate-900">Registro Imutável</p>
						<p class="mt-1 text-xs text-slate-500">Segurança e compliance.</p>
					</div>

					<!-- Card 4: ODM -->
					<div class="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs">
						<span class="font-mono text-xs font-bold text-slate-800">Métricas</span>
						<p class="mt-2 text-xs font-semibold text-slate-900">Observabilidade</p>
						<p class="mt-1 text-xs text-slate-500">Monitoramento integrado.</p>
					</div>
				</div>
			</div>
		</div>
	</div>
</section>
