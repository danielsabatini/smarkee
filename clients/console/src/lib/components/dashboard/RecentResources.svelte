<script lang="ts">
	import { ArrowRight, Building2, ShieldCheck, User, UserCheck } from 'lucide-svelte';
	import DemoBadge from '$lib/components/ui/DemoBadge.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';

	const consoleState = getConsoleState();
</script>

<section
	aria-labelledby="recent-resources-heading"
	data-testid="recent-resources-section"
	class="flex flex-col justify-between rounded-2xl border border-slate-200 bg-white p-4 shadow-2xs sm:p-5"
>
	<div>
		<div class="mb-3 flex items-center justify-between gap-2">
			<div>
				<h2 id="recent-resources-heading" class="text-sm font-bold text-slate-900">
					Recursos recentes
				</h2>
				<p class="text-xs text-slate-500">
					Últimos recursos criados e status na organização atual.
				</p>
			</div>

			<a
				href="/identity/organizations"
				class="inline-flex shrink-0 items-center gap-1 whitespace-nowrap text-xs font-semibold text-brand-700 hover:text-brand-800"
			>
				<span>Ver todos</span>
				<ArrowRight class="h-3.5 w-3.5" aria-hidden="true" />
			</a>
		</div>

		{#if consoleState.isBootstrapping || consoleState.isSwitchingOrganization}
			<div class="space-y-2 py-4">
				<div class="h-9 animate-pulse rounded-lg bg-slate-100"></div>
				<div class="h-9 animate-pulse rounded-lg bg-slate-100"></div>
				<div class="h-9 animate-pulse rounded-lg bg-slate-100"></div>
			</div>
		{:else if consoleState.recentResources.length === 0}
			<EmptyState
				title="Nenhum recurso recente"
				description="Os recursos criados na organização selecionada aparecerão aqui."
			/>
		{:else}
			<div class="overflow-x-auto">
				<table class="w-full table-fixed text-left text-xs">
					<thead>
						<tr
							class="border-b border-slate-200 bg-slate-50/80 text-[11px] font-semibold text-slate-600"
						>
							<th class="w-[36%] rounded-tl-lg px-2 py-2 whitespace-nowrap">Nome</th>
							<th class="w-[22%] px-1.5 py-2 whitespace-nowrap">Tipo</th>
							<th class="w-[22%] px-1.5 py-2 whitespace-nowrap">Fase</th>
							<th class="w-[20%] rounded-tr-lg px-2 py-2 text-right whitespace-nowrap">
								Atualizado em
							</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-slate-100">
						{#each consoleState.recentResources as item (item.resourceId)}
							<tr
								data-testid="recent-resource-row-{item.resourceId}"
								class="transition hover:bg-slate-50/80"
							>
								<td class="px-2 py-2.5">
									<a
										href={item.href}
										title={item.displayName}
										class="flex min-w-0 items-center gap-1.5 font-semibold text-brand-700 hover:underline"
									>
										{#if item.resourceType === 'ipm.organization'}
											<Building2 class="h-3.5 w-3.5 shrink-0 text-slate-500" aria-hidden="true" />
										{:else if item.resourceType === 'ipm.user'}
											<User class="h-3.5 w-3.5 shrink-0 text-slate-500" aria-hidden="true" />
										{:else if item.resourceType === 'sum.service'}
											<ShieldCheck class="h-3.5 w-3.5 shrink-0 text-slate-500" aria-hidden="true" />
										{:else}
											<UserCheck class="h-3.5 w-3.5 shrink-0 text-slate-500" aria-hidden="true" />
										{/if}
										<span class="truncate">{item.displayName}</span>
									</a>
								</td>
								<td class="px-1.5 py-2.5">
									<div class="flex items-center gap-1">
										<span class="truncate font-medium text-slate-700" title={item.typeLabel}>
											{item.typeLabel}
										</span>
										{#if item.isDemo}
											<DemoBadge label="Demo" />
										{/if}
									</div>
								</td>
								<td class="px-1.5 py-2.5">
									<StatusBadge phase={item.phase} size="sm" />
								</td>
								<td class="px-2 py-2.5 text-right text-[11px] whitespace-nowrap text-slate-600">
									{item.updatedAt}
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
</section>
