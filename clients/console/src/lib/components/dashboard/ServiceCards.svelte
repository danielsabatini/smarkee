<script lang="ts">
	import { ArrowRight, BarChart3, CheckCircle2, FileText, ShieldCheck, Users } from 'lucide-svelte';
	import DemoBadge from '$lib/components/ui/DemoBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';
	import type { ModuleCode } from '$lib/types/console';

	const consoleState = getConsoleState();

	function isServiceEnabled(serviceKey: string): boolean {
		if (serviceKey === 'sum') {
			return true;
		}
		return consoleState.services.some(
			(s) => s.desired.service === serviceKey && s.desired.lifecycle === 'present'
		);
	}
</script>

{#snippet moduleIcon(code: ModuleCode)}
	{#if code === 'IPM'}
		<Users class="h-5 w-5" aria-hidden="true" />
	{:else if code === 'SUM'}
		<ShieldCheck class="h-5 w-5" aria-hidden="true" />
	{:else if code === 'AEM'}
		<FileText class="h-5 w-5" aria-hidden="true" />
	{:else}
		<BarChart3 class="h-5 w-5" aria-hidden="true" />
	{/if}
{/snippet}

<section aria-labelledby="platform-services-heading">
	<div class="mb-3 flex items-center justify-between gap-2">
		<div>
			<h2 id="platform-services-heading" class="text-base font-bold text-slate-900">
				Serviços da plataforma
			</h2>
			<p class="text-xs text-slate-600">Principais serviços disponíveis para a sua organização.</p>
		</div>

		<a
			href="/services/catalog"
			class="inline-flex items-center gap-1 text-xs font-semibold text-brand-700 hover:text-brand-800"
		>
			<span>Ver todos os serviços</span>
			<ArrowRight class="h-3.5 w-3.5" aria-hidden="true" />
		</a>
	</div>

	<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 xl:grid-cols-4">
		{#each consoleState.serviceCatalog as service (service.code)}
			{@const enabled = isServiceEnabled(service.serviceKey)}
			<a
				href={service.href}
				data-testid="service-card-{service.code}"
				class="group relative flex h-full flex-col justify-between rounded-xl border border-slate-200 bg-white p-3.5 shadow-2xs transition hover:border-brand-300 hover:shadow-sm"
			>
				{#if service.isDemo}
					<div class="absolute right-1.5 bottom-1.5">
						<DemoBadge label="Preview" variant="icon" />
					</div>
				{/if}

				<div class="flex items-start gap-2.5">
					<div
						class="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700 transition group-hover:bg-brand-100"
					>
						{@render moduleIcon(service.code)}
					</div>

					<div class="min-w-0 flex-1">
						<div class="flex items-center justify-between gap-1">
							<h3 class="whitespace-nowrap text-xs font-bold text-slate-900" title={service.name}>
								{service.shortName}
							</h3>

							<span
								class="shrink-0 rounded bg-slate-100 px-1.5 py-0.5 font-mono text-[10px] font-bold text-slate-700"
							>
								{service.code}
							</span>
						</div>

						<p class="mt-1 text-[11px] leading-snug text-slate-600">
							{service.description}
						</p>
					</div>
				</div>

				<div class="mt-3 flex items-center">
					{#if enabled || service.isDemo}
						<span
							class="inline-flex items-center gap-1 rounded-full border border-brand-200 bg-brand-50 px-2 py-0.5 text-[11px] font-semibold text-brand-800"
						>
							<CheckCircle2 class="h-3 w-3 text-brand-600" aria-hidden="true" />
							<span>Habilitado</span>
						</span>
					{:else}
						<span
							class="inline-flex items-center gap-1 rounded-full border border-slate-200 bg-slate-100 px-2 py-0.5 text-[11px] font-medium text-slate-600"
						>
							<span>Disponível no SUM</span>
						</span>
					{/if}
				</div>
			</a>
		{/each}
	</div>
</section>
