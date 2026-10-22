<script lang="ts">
	import { CheckCircle2, Play, ShieldCheck } from 'lucide-svelte';
	import DemoBadge from '$lib/components/ui/DemoBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';

	const consoleState = getConsoleState();

	function isEnabled(serviceKey: string): boolean {
		if (serviceKey === 'sum') {
			return true;
		}
		return consoleState.services.some(
			(s) => s.desired.service === serviceKey && s.desired.lifecycle === 'present'
		);
	}
</script>

<svelte:head>
	<title>Smarkee Console — Catálogo de Serviços (SUM)</title>
</svelte:head>

<div class="mx-auto max-w-7xl space-y-6">
	<div>
		<span class="text-xs font-semibold text-emerald-700 uppercase"> Serviços (SUM) </span>
		<h1 class="mt-0.5 text-2xl font-bold text-slate-900">Catálogo de Serviços</h1>
		<p class="mt-1 text-xs text-slate-600">
			Habilite os serviços disponíveis para utilizar os módulos na plataforma.
		</p>
	</div>

	<div class="grid grid-cols-1 gap-4 md:grid-cols-2">
		{#each consoleState.serviceCatalog as item (item.code)}
			{@const enabled = isEnabled(item.serviceKey)}
			<div
				class="flex flex-col justify-between rounded-2xl border border-slate-200 bg-white p-5 shadow-2xs"
			>
				<div>
					<div class="flex items-start justify-between gap-2">
						<div class="flex items-center gap-2.5">
							<div
								class="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700"
							>
								<ShieldCheck class="h-5 w-5" aria-hidden="true" />
							</div>
							<div>
								<h2 class="text-sm font-bold text-slate-900">{item.name}</h2>
								<span class="font-mono text-xs text-slate-500">{item.serviceKey}</span>
							</div>
						</div>
						<div class="flex items-center gap-1.5">
							<span
								class="rounded-md bg-slate-100 px-2 py-0.5 font-mono text-xs font-bold text-slate-700"
							>
								{item.code}
							</span>
							{#if item.isDemo}
								<DemoBadge label="Preview" />
							{/if}
						</div>
					</div>

					<p class="mt-3 text-xs leading-relaxed text-slate-600">{item.description}</p>
				</div>

				<div class="mt-5 flex items-center justify-between border-t border-slate-100 pt-3">
					{#if enabled}
						<span class="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700">
							<CheckCircle2 class="h-4 w-4 text-emerald-600" aria-hidden="true" />
							<span>Serviço Habilitado</span>
						</span>
					{:else}
						<span class="text-xs text-slate-500">Não habilitado na organização</span>
					{/if}

					{#if !enabled && item.serviceKey !== 'sum'}
						<button
							type="button"
							onclick={() => consoleState.enableService({ service: item.serviceKey })}
							class="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-3.5 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-700"
						>
							<Play class="h-3.5 w-3.5" aria-hidden="true" />
							<span>Habilitar Serviço</span>
						</button>
					{/if}
				</div>
			</div>
		{/each}
	</div>
</div>
