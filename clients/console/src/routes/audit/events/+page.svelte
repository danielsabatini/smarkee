<script lang="ts">
	import { FileText } from 'lucide-svelte';
	import CopyableId from '$lib/components/ui/CopyableId.svelte';
	import DemoBadge from '$lib/components/ui/DemoBadge.svelte';
	import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';
	import { formatResourceType, formatOperationAction } from '$lib/utils/formatters';

	const consoleState = getConsoleState();
</script>

<svelte:head>
	<title>Smarkee Console — Eventos de Auditoria (AEM Preview)</title>
</svelte:head>

<div class="mx-auto max-w-6xl space-y-6">
	<div class="flex flex-wrap items-center justify-between gap-2">
		<div>
			<span class="text-xs font-semibold text-brand-700 uppercase"> Auditoria (AEM) </span>
			<h1 class="mt-0.5 text-2xl font-bold text-slate-900">Eventos de Auditoria</h1>
			<p class="mt-1 text-xs text-slate-600">
				Histórico consolidado de operações e eventos da organização ativa.
			</p>
		</div>
		<DemoBadge label="Preview / Demonstrativo" />
	</div>

	<div class="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xs">
		<div class="overflow-x-auto">
			<table class="w-full text-left text-xs">
				<thead>
					<tr
						class="border-b border-slate-200 bg-slate-50 text-[11px] font-semibold text-slate-500"
					>
						<th class="px-4 py-3">Evento / Operação</th>
						<th class="px-4 py-3">ID da Operação</th>
						<th class="px-4 py-3">Recurso</th>
						<th class="px-4 py-3">Status</th>
						<th class="px-4 py-3 text-right">Data / Hora</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-slate-100">
					{#each consoleState.operations as entry (entry.operation.operationId)}
						<tr class="hover:bg-slate-50/80">
							<td class="px-4 py-3">
								<div class="flex items-center gap-2">
									<FileText class="h-4 w-4 text-brand-700" aria-hidden="true" />
									<div>
										<span class="font-bold text-slate-900">{entry.title}</span>
										<p class="text-[11px] text-slate-500">{entry.subtitle}</p>
									</div>
								</div>
							</td>
							<td class="px-4 py-3">
								<CopyableId id={entry.operation.operationId} />
							</td>
							<td class="px-4 py-3 font-medium text-[11px] text-slate-700">
								{formatResourceType(entry.operation.resourceType)} ({formatOperationAction(
									entry.operation.operationType
								)})
							</td>
							<td class="px-4 py-3">
								<StatusBadge operationStatus={entry.operation.operationStatus} size="sm" />
							</td>
							<td class="px-4 py-3 text-right font-mono text-[11px] text-slate-500">
								{entry.operation.updatedAt}
							</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	</div>
</div>
