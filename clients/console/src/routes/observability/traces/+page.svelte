<script lang="ts">
	import { Activity } from 'lucide-svelte';
	import DemoBadge from '$lib/components/ui/DemoBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';

	const consoleState = getConsoleState();
</script>

<svelte:head>
	<title>Smarkee Console — Traces (ODM Preview)</title>
</svelte:head>

<div class="mx-auto max-w-5xl space-y-6">
	<div class="flex flex-wrap items-center justify-between gap-2">
		<div>
			<span class="font-mono text-xs font-semibold text-emerald-700 uppercase">
				Observability Data Manager (ODM)
			</span>
			<h1 class="mt-0.5 text-2xl font-bold text-slate-900">Rastreamento Distribuído (Traces)</h1>
		</div>
		<DemoBadge label="Preview / Demonstrativo" />
	</div>

	<div class="rounded-2xl border border-slate-200 bg-white p-6 shadow-2xs">
		<div class="flex items-start gap-3">
			<div
				class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700"
			>
				<Activity class="h-5 w-5" aria-hidden="true" />
			</div>
			<div>
				<h2 class="text-sm font-bold text-slate-900">
					Spans do Loop de Reconciliação ({consoleState.activeOrganization?.desired.name ?? '—'})
				</h2>
				<p class="mt-1 text-xs leading-relaxed text-slate-600">
					Módulo demonstrativo para inspeção de traces ponta a ponta entre Receiver, Manager,
					Reconciler, Executor e Observer.
				</p>
			</div>
		</div>
	</div>
</div>
