<script lang="ts">
	import { Building2, Check, ChevronDown, PlusCircle, RefreshCw, Search } from 'lucide-svelte';
	import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';

	const consoleState = getConsoleState();

	let isOpen = $state(false);
	let searchQuery = $state('');

	let filteredOrganizations = $derived.by(() => {
		const q = searchQuery.trim().toLowerCase();
		if (!q) {
			return consoleState.organizations;
		}
		return consoleState.organizations.filter((org) => {
			const demoTitle = consoleState.adapter
				.getOrganizationMetadataDemo(org.resourceId)
				.displayName.toLowerCase();
			return (
				org.desired.name.toLowerCase().includes(q) ||
				org.resourceId.toLowerCase().includes(q) ||
				demoTitle.includes(q)
			);
		});
	});

	let activeDisplayName = $derived.by(() => {
		if (consoleState.activeOrganizationDemoMeta) {
			return consoleState.activeOrganizationDemoMeta.displayName;
		}
		return consoleState.activeOrganization?.desired.name ?? 'Selecionar Organização';
	});

	function togglePopover(): void {
		isOpen = !isOpen;
		if (isOpen) {
			searchQuery = '';
		}
	}

	function closePopover(): void {
		isOpen = false;
	}

	async function handleSelect(organizationId: string): Promise<void> {
		isOpen = false;
		await consoleState.selectOrganization(organizationId);
	}

	function handleKeydown(event: KeyboardEvent): void {
		if (event.key === 'Escape' && isOpen) {
			event.stopPropagation();
			closePopover();
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<div class="relative min-w-0">
	<button
		type="button"
		onclick={togglePopover}
		aria-haspopup="dialog"
		aria-expanded={isOpen}
		data-testid="organization-selector-trigger"
		class="flex max-w-full min-h-[44px] items-center gap-1.5 rounded-lg border border-slate-200 bg-slate-50/90 px-2.5 py-1 text-left transition hover:border-brand-300 hover:bg-white sm:min-h-0 sm:gap-2.5 sm:px-3 sm:py-1.5"
	>
		<div
			class="flex h-6 w-6 shrink-0 items-center justify-center rounded-md bg-brand-100 text-brand-700 sm:h-7 sm:w-7"
		>
			<Building2 class="h-3.5 w-3.5 sm:h-4 sm:w-4" aria-hidden="true" />
		</div>
		<div class="min-w-0">
			<div class="text-[9px] leading-tight font-medium text-slate-600 sm:text-[10px]">
				Organização
			</div>
			<div
				class="max-w-[120px] truncate text-[11px] font-semibold text-slate-900 sm:max-w-[240px] sm:text-xs"
				data-testid="active-organization-name"
			>
				{activeDisplayName}
			</div>
		</div>
		<ChevronDown
			class="ml-0.5 h-3.5 w-3.5 shrink-0 text-slate-500 transition-transform sm:ml-1 sm:h-4 sm:w-4 {isOpen
				? 'rotate-180'
				: ''}"
			aria-hidden="true"
		/>
	</button>

	{#if isOpen}
		<div class="fixed inset-0 z-40" aria-hidden="true" onclick={closePopover}></div>

		<div
			role="dialog"
			aria-label="Seletor de Organização"
			data-testid="organization-selector-popover"
			class="absolute left-0 z-50 mt-2 w-80 rounded-xl border border-slate-200 bg-white p-3 shadow-xl sm:w-96"
		>
			<div class="mb-2 flex items-center justify-between">
				<span class="text-xs font-semibold tracking-wide text-slate-700 uppercase">
					Alternar Organização
				</span>
				<span class="text-[11px] text-slate-500">
					{consoleState.organizations.length} disponíveis
				</span>
			</div>

			<div class="relative mb-2.5">
				<Search
					class="pointer-events-none absolute top-1/2 left-2.5 h-3.5 w-3.5 -translate-y-1/2 text-slate-400"
					aria-hidden="true"
				/>
				<input
					type="search"
					bind:value={searchQuery}
					placeholder="Filtrar por nome..."
					aria-label="Filtrar organizações por nome"
					data-testid="organization-selector-search"
					class="w-full rounded-lg border border-slate-200 bg-slate-50 py-1.5 pr-3 pl-8 text-xs text-slate-900 placeholder:text-slate-400 focus:border-brand-600 focus:bg-white focus:outline-none"
				/>
			</div>

			{#if consoleState.isBootstrapping}
				<div class="flex items-center justify-center gap-2 py-6 text-xs text-slate-600">
					<RefreshCw class="h-4 w-4 animate-spin text-brand-600" aria-hidden="true" />
					<span>Carregando organizações...</span>
				</div>
			{:else if filteredOrganizations.length === 0}
				<div class="rounded-lg border border-dashed border-slate-200 p-4 text-center">
					<p class="text-xs font-medium text-slate-700">Nenhuma organização encontrada</p>
					<p class="mt-0.5 text-[11px] text-slate-500">
						Verifique o termo pesquisado ou crie uma nova organização.
					</p>
				</div>
			{:else}
				<ul class="max-h-64 space-y-1 overflow-y-auto pr-0.5" role="listbox">
					{#each filteredOrganizations as org (org.resourceId)}
						{@const isSelected = org.resourceId === consoleState.activeOrganizationId}
						{@const demoMeta = consoleState.adapter.getOrganizationMetadataDemo(org.resourceId)}
						<li role="option" aria-selected={isSelected}>
							<button
								type="button"
								onclick={() => handleSelect(org.resourceId)}
								data-testid="org-option-{org.desired.name}"
								class="flex w-full items-center justify-between gap-3 rounded-lg px-3 py-2 text-left transition {isSelected
									? 'bg-brand-50/90 text-brand-950 ring-1 ring-brand-200'
									: 'hover:bg-slate-100'}"
							>
								<span class="min-w-0 flex-1 text-xs font-semibold text-slate-900">
									{demoMeta.displayName}
								</span>

								<div class="flex shrink-0 items-center gap-2">
									<StatusBadge phase={org.phase} size="sm" />
									{#if isSelected}
										<Check class="h-4 w-4 text-brand-700" aria-label="Organização selecionada" />
									{/if}
								</div>
							</button>
						</li>
					{/each}
				</ul>
			{/if}

			<div class="mt-2.5 flex items-center justify-between border-t border-slate-100 pt-2 text-xs">
				<a
					href="/identity/organizations"
					onclick={closePopover}
					class="inline-flex items-center gap-1.5 font-medium text-brand-700 hover:text-brand-800"
				>
					<PlusCircle class="h-3.5 w-3.5" aria-hidden="true" />
					<span>Gerenciar organizações</span>
				</a>
			</div>
		</div>
	{/if}
</div>
