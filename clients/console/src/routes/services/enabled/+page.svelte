<script lang="ts">
	import { Play, PowerOff, ShieldCheck } from 'lucide-svelte';
	import CopyableId from '$lib/components/ui/CopyableId.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';

	const consoleState = getConsoleState();
</script>

<svelte:head>
	<title>Smarkee Console — Serviços Habilitados</title>
</svelte:head>

<div class="mx-auto max-w-7xl space-y-6">
	<div>
		<span class="text-xs font-semibold text-brand-700 uppercase"> Serviços (SUM) </span>
		<h1 class="mt-0.5 text-2xl font-bold text-slate-900">Serviços Habilitados</h1>
		<p class="mt-1 text-xs text-slate-600">
			Serviços ativos e configurados para sua conta na plataforma.
		</p>
	</div>

	{#if consoleState.services.length === 0}
		<EmptyState
			title="Nenhum serviço habilitado"
			description="Acesse o Catálogo de Serviços para habilitar o módulo IPM ou outros serviços."
		/>
	{:else}
		<div class="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xs">
			<div class="overflow-x-auto">
				<table class="w-full text-left text-xs">
					<thead>
						<tr
							class="border-b border-slate-200 bg-slate-50 text-[11px] font-semibold text-slate-500"
						>
							<th class="px-4 py-3">Serviço</th>
							<th class="px-4 py-3">ID</th>
							<th class="px-4 py-3">Estado</th>
							<th class="px-4 py-3">Fase</th>
							<th class="px-4 py-3 text-center">Ações</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-slate-100">
						{#each consoleState.services as svc (svc.resourceId)}
							<tr
								data-testid="enabled-service-row-{svc.desired.service}"
								class="hover:bg-slate-50/80"
							>
								<td class="px-4 py-3">
									<div class="flex items-center gap-2">
										<ShieldCheck class="h-4 w-4 text-brand-700" aria-hidden="true" />
										<span class="font-mono font-bold text-slate-900 uppercase">
											{svc.desired.service}
										</span>
									</div>
								</td>
								<td class="px-4 py-3">
									<CopyableId id={svc.resourceId} idClass="font-mono text-[11px] text-slate-600" />
								</td>
								<td class="px-4 py-3 text-[11px] font-medium text-slate-700">
									{svc.desired.lifecycle === 'present' ? 'Habilitado' : 'Desabilitado'}
								</td>
								<td class="px-4 py-3">
									<StatusBadge phase={svc.phase} size="sm" />
								</td>
								<td class="px-4 py-3 text-center">
									{#if svc.desired.service === 'sum'}
										<span class="text-xs text-slate-400" title="Serviço essencial da plataforma"
											>—</span
										>
									{:else if svc.desired.lifecycle === 'present'}
										<button
											type="button"
											onclick={() => consoleState.disableService(svc.resourceId)}
											class="inline-flex items-center gap-1.5 rounded-lg border border-amber-200 bg-amber-50 px-2.5 py-1 text-[11px] font-semibold text-amber-800 transition hover:bg-amber-100"
										>
											<PowerOff class="h-3 w-3" aria-hidden="true" />
											<span>Desabilitar</span>
										</button>
									{:else}
										<button
											type="button"
											onclick={() => consoleState.enableService({ service: svc.desired.service })}
											class="inline-flex items-center gap-1.5 rounded-lg bg-brand-600 px-2.5 py-1 text-[11px] font-semibold text-white transition hover:bg-brand-700"
										>
											<Play class="h-3 w-3" aria-hidden="true" />
											<span>Habilitar</span>
										</button>
									{/if}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		</div>
	{/if}
</div>
