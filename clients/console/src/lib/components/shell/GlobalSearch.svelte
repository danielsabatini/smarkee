<script lang="ts">
	import { ArrowRight, CornerDownLeft, Search, X } from 'lucide-svelte';
	import { goto } from '$app/navigation';
	import DemoBadge from '$lib/components/ui/DemoBadge.svelte';
	import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
	import { NAVIGATION_SECTIONS } from '$lib/config/navigation';
	import { getConsoleState } from '$lib/state/console-context.svelte';

	const consoleState = getConsoleState();

	let query = $state('');

	interface SearchResultItem {
		id: string;
		title: string;
		subtitle: string;
		href: string;
		category: 'Rota / Módulo' | 'Recurso' | 'Serviço';
		isDemo?: boolean;
		phase?: 'Pending' | 'Reconciling' | 'Ready' | 'Failed' | 'Deleting' | 'Degraded';
	}

	let searchResults = $derived.by<SearchResultItem[]>(() => {
		const q = query.trim().toLowerCase();
		const items: SearchResultItem[] = [];

		for (const section of NAVIGATION_SECTIONS) {
			for (const nav of section.items) {
				items.push({
					id: `nav-${nav.id}`,
					title: nav.label,
					subtitle: nav.description ?? section.title,
					href: nav.href,
					category: 'Rota / Módulo',
					isDemo: nav.isDemo
				});
			}
		}

		for (const resource of consoleState.recentResources) {
			items.push({
				id: `res-${resource.resourceId}`,
				title: resource.displayName,
				subtitle: `${resource.typeLabel} • ${resource.resourceId}`,
				href: resource.href,
				category: 'Recurso',
				isDemo: resource.isDemo,
				phase: resource.phase
			});
		}

		for (const svc of consoleState.serviceCatalog) {
			items.push({
				id: `svc-${svc.code}`,
				title: `${svc.name} (${svc.code})`,
				subtitle: svc.description,
				href: svc.href,
				category: 'Serviço',
				isDemo: svc.isDemo
			});
		}

		if (!q) {
			return items.slice(0, 8);
		}

		return items
			.filter(
				(item) =>
					item.title.toLowerCase().includes(q) ||
					item.subtitle.toLowerCase().includes(q) ||
					item.category.toLowerCase().includes(q)
			)
			.slice(0, 10);
	});

	function openDialog(): void {
		consoleState.isGlobalSearchOpen = true;
		query = '';
	}

	function closeDialog(): void {
		consoleState.isGlobalSearchOpen = false;
	}

	async function handleSelectResult(href: string): Promise<void> {
		closeDialog();
		await goto(href);
	}

	function handleWindowKeydown(event: KeyboardEvent): void {
		if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
			event.preventDefault();
			if (consoleState.isGlobalSearchOpen) {
				closeDialog();
			} else {
				openDialog();
			}
		} else if (event.key === 'Escape' && consoleState.isGlobalSearchOpen) {
			event.stopPropagation();
			closeDialog();
		}
	}
</script>

<svelte:window onkeydown={handleWindowKeydown} />

<div class="w-full max-w-xl">
	<button
		type="button"
		onclick={openDialog}
		data-testid="global-search-trigger"
		class="flex w-full items-center justify-between gap-3 rounded-full border border-slate-200 bg-slate-100/90 px-3.5 py-1.5 text-left text-xs text-slate-600 transition hover:border-slate-300 hover:bg-white"
	>
		<span class="flex items-center gap-2 truncate">
			<Search class="h-4 w-4 shrink-0 text-slate-500" aria-hidden="true" />
			<span class="truncate">Pesquise recursos, serviços, documentação e mais...</span>
		</span>
		<kbd
			aria-hidden="true"
			class="hidden shrink-0 rounded border border-slate-300 bg-white px-1.5 py-0.5 font-mono text-[10px] font-semibold text-slate-600 sm:inline-block"
		>
			⌘ K
		</kbd>
	</button>
</div>

{#if consoleState.isGlobalSearchOpen}
	<div
		class="fixed inset-0 z-50 flex items-start justify-center bg-slate-900/40 p-4 pt-16 backdrop-blur-[1px]"
		role="dialog"
		aria-modal="true"
		aria-label="Busca global da plataforma"
		data-testid="global-search-dialog"
	>
		<div
			class="w-full max-w-2xl overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xl"
		>
			<div class="flex items-center gap-2 border-b border-slate-100 px-4 py-3">
				<Search class="h-4 w-4 shrink-0 text-emerald-600" aria-hidden="true" />
				<input
					type="search"
					bind:value={query}
					placeholder="Digite o nome de uma Organization, User, serviço (IPM, SUM, AEM, ODM) ou rota..."
					aria-label="Campo de busca global"
					data-testid="global-search-input"
					class="w-full bg-transparent text-sm text-slate-900 placeholder:text-slate-400 focus:outline-none"
				/>
				<button
					type="button"
					onclick={closeDialog}
					aria-label="Fechar busca global"
					class="flex min-h-[44px] min-w-[44px] sm:min-h-0 sm:min-w-0 items-center justify-center rounded-lg p-2 sm:p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
				>
					<X class="h-4 w-4" aria-hidden="true" />
				</button>
			</div>

			<div class="max-h-96 overflow-y-auto p-2">
				{#if searchResults.length === 0}
					<div class="py-10 text-center text-xs text-slate-500">
						Nenhum recurso, módulo ou serviço encontrado para "{query}".
					</div>
				{:else}
					<ul class="space-y-1">
						{#each searchResults as item (item.id)}
							<li>
								<button
									type="button"
									onclick={() => handleSelectResult(item.href)}
									class="flex w-full items-center justify-between gap-3 rounded-xl px-3 py-2.5 text-left transition hover:bg-emerald-50/70"
								>
									<div class="min-w-0 flex-1">
										<div class="flex items-center gap-2">
											<span class="truncate text-xs font-semibold text-slate-900">
												{item.title}
											</span>
											<span
												class="rounded bg-slate-100 px-1.5 py-0.5 text-[10px] font-medium text-slate-600"
											>
												{item.category}
											</span>
											{#if item.isDemo}
												<DemoBadge label="Preview" />
											{/if}
											{#if item.phase}
												<StatusBadge phase={item.phase} size="sm" />
											{/if}
										</div>
										<p class="mt-0.5 truncate text-[11px] text-slate-500">{item.subtitle}</p>
									</div>
									<ArrowRight class="h-4 w-4 shrink-0 text-slate-400" aria-hidden="true" />
								</button>
							</li>
						{/each}
					</ul>
				{/if}
			</div>

			<div
				class="flex items-center justify-between border-t border-slate-100 bg-slate-50 px-4 py-2 text-[11px] text-slate-500"
			>
				<span class="flex items-center gap-1">
					<CornerDownLeft class="h-3 w-3" aria-hidden="true" />
					Selecione um item para navegar
				</span>
				<span>Pressione <kbd class="font-mono font-semibold">Esc</kbd> para fechar</span>
			</div>
		</div>
	</div>
{/if}
