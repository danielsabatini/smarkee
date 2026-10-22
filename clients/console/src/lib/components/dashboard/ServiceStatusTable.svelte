<script lang="ts">
	import { ArrowRight, CheckCircle2, CircleDashed, Play, ShieldCheck } from 'lucide-svelte';
	import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';
	import type { ResourcePhase } from '$lib/types/common';

	const consoleState = getConsoleState();

	let triggeringService = $state<string | null>(null);

	interface ServiceRowView {
		serviceKey: string;
		name: string;
		code: string;
		isEnabled: boolean;
		phase?: ResourcePhase;
		updatedAt: string;
		isDemo: boolean;
		canTriggerEnable: boolean;
	}

	let rows = $derived.by<ServiceRowView[]>(() => {
		const ipmLink = consoleState.services.find((s) => s.desired.service === 'ipm');
		const aemLink = consoleState.services.find((s) => s.desired.service === 'aem');
		const odmLink = consoleState.services.find((s) => s.desired.service === 'odm');

		return [
			{
				serviceKey: 'ipm',
				name: 'Identity Provider',
				code: 'IPM',
				isEnabled: ipmLink?.desired.lifecycle === 'present',
				phase: ipmLink?.phase ?? 'Ready',
				updatedAt: ipmLink ? 'há 2 horas' : '—',
				isDemo: false,
				canTriggerEnable: true
			},
			{
				serviceKey: 'sum',
				name: 'Service Usage',
				code: 'SUM',
				isEnabled: true,
				phase: 'Ready',
				updatedAt: 'há 3 horas',
				isDemo: false,
				canTriggerEnable: false
			},
			{
				serviceKey: 'aem',
				name: 'Audit Event',
				code: 'AEM',
				isEnabled: aemLink?.desired.lifecycle === 'present' || true,
				phase: aemLink?.phase ?? 'Ready',
				updatedAt: aemLink ? 'agora' : 'há 5 horas',
				isDemo: true,
				canTriggerEnable: true
			},
			{
				serviceKey: 'odm',
				name: 'Observability',
				code: 'ODM',
				isEnabled: odmLink?.desired.lifecycle === 'present',
				phase: odmLink?.phase,
				updatedAt: odmLink ? 'agora' : '—',
				isDemo: true,
				canTriggerEnable: true
			}
		];
	});

	async function handleEnableService(serviceKey: string): Promise<void> {
		triggeringService = serviceKey;
		try {
			await consoleState.enableService({ service: serviceKey });
		} finally {
			triggeringService = null;
		}
	}
</script>

<section
	aria-labelledby="service-status-heading"
	data-testid="service-status-section"
	class="flex flex-col justify-between rounded-2xl border border-slate-200 bg-white p-4 shadow-2xs sm:p-5"
>
	<div>
		<div class="mb-3 flex items-center justify-between gap-2">
			<div>
				<h2 id="service-status-heading" class="text-sm font-bold text-slate-900">
					Estado dos serviços
				</h2>
				<p class="text-xs text-slate-500">Serviços ativos na conta titular.</p>
			</div>

			<a
				href="/services/enabled"
				class="inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-xs font-semibold text-emerald-700 hover:text-emerald-800"
			>
				<span>Ver todos</span>
				<ArrowRight class="h-3.5 w-3.5" aria-hidden="true" />
			</a>
		</div>

		<div class="overflow-x-auto">
			<table class="w-full table-fixed text-left text-xs">
				<thead>
					<tr
						class="border-b border-slate-200 bg-slate-50/80 text-[11px] font-semibold text-slate-600"
					>
						<th class="w-[44%] rounded-tl-lg px-2 py-2 whitespace-nowrap">Serviço</th>
						<th class="w-[27%] px-1.5 py-2 whitespace-nowrap">Status</th>
						<th class="w-[29%] rounded-tr-lg px-2 py-2 text-right whitespace-nowrap">
							Última atualização
						</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-slate-100">
					{#each rows as row (row.serviceKey)}
						<tr
							data-testid="service-status-row-{row.serviceKey}"
							class="transition hover:bg-slate-50/80"
						>
							<td class="px-2 py-2.5">
								<div class="flex min-w-0 items-center gap-1.5">
									<ShieldCheck class="h-3.5 w-3.5 shrink-0 text-slate-500" aria-hidden="true" />
									<span class="whitespace-nowrap font-semibold text-slate-900">{row.name}</span>
									<span
										class="shrink-0 rounded bg-slate-100 px-1 py-0.5 font-mono text-[10px] font-bold text-slate-600"
									>
										{row.code}
									</span>
								</div>
							</td>

							<td class="px-1.5 py-2.5">
								<div class="flex items-center gap-1 whitespace-nowrap">
									{#if row.phase && (row.phase === 'Pending' || row.phase === 'Reconciling')}
										<StatusBadge phase={row.phase} size="sm" />
									{:else if row.isEnabled}
										<span class="inline-flex items-center gap-1 font-semibold text-emerald-700">
											<CheckCircle2
												class="h-3.5 w-3.5 shrink-0 text-emerald-600"
												aria-hidden="true"
											/>
											<span>Habilitado</span>
										</span>
									{:else}
										<span class="inline-flex items-center gap-1 font-medium text-slate-600">
											<CircleDashed
												class="h-3.5 w-3.5 shrink-0 text-slate-500"
												aria-hidden="true"
											/>
											<span>Desabilitado</span>
										</span>
									{/if}
								</div>
							</td>

							<td class="px-2 py-2.5 text-right text-[11px] whitespace-nowrap text-slate-600">
								<div class="flex items-center justify-end gap-1">
									{#if !row.isEnabled && row.canTriggerEnable}
										<button
											type="button"
											disabled={triggeringService === row.serviceKey}
											onclick={() => handleEnableService(row.serviceKey)}
											data-testid="reconcile-service-{row.serviceKey}"
											class="inline-flex items-center gap-1 rounded border border-emerald-200 bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-800 transition hover:bg-emerald-100 disabled:opacity-50"
										>
											<Play class="h-2.5 w-2.5" aria-hidden="true" />
											<span>Habilitar</span>
										</button>
									{:else}
										<span>{row.updatedAt}</span>
									{/if}
								</div>
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
</section>
