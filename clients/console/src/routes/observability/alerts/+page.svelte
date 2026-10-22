<script lang="ts">
	import { Bell } from 'lucide-svelte';
	import DemoBadge from '$lib/components/ui/DemoBadge.svelte';
</script>

<svelte:head>
	<title>Smarkee Console — Alertas (ODM Preview)</title>
</svelte:head>

<div class="mx-auto max-w-5xl space-y-6">
	<div class="flex flex-wrap items-center justify-between gap-2">
		<div>
			<span class="text-xs font-semibold text-emerald-700 uppercase"> Observabilidade (ODM) </span>
			<h1 class="mt-0.5 text-2xl font-bold text-slate-900">Alertas e SLOs</h1>
		</div>
		<DemoBadge label="Preview / Demonstrativo" />
	</div>

	<div class="rounded-2xl border border-slate-200 bg-white p-6 shadow-2xs">
		<div class="flex items-start gap-3">
			<div
				class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700"
			>
				<Bell class="h-5 w-5" aria-hidden="true" />
			</div>
			<div>
				<h2 class="text-sm font-bold text-slate-900">Monitoramento de Convergência</h2>
				<p class="mt-1 text-xs leading-relaxed text-slate-600">
					Módulo demonstrativo para configuração de alertas operacionais e indicadores de nível de
					serviço.
				</p>
			</div>
		</div>
	</div>
</div>
