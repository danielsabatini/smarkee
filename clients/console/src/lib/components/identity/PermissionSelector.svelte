<script lang="ts">
	import { Search, X } from 'lucide-svelte';
	import type { GrantableRole } from '$lib/types/resources';

	export interface RoleItem {
		role: GrantableRole;
		label: string;
		description: string;
		category: 'organization' | 'user';
	}

	export const ROLE_DEFINITIONS: RoleItem[] = [
		{
			role: 'ipm.organization.get',
			label: 'Visualizar Organização',
			description: 'Permite consultar dados e metadados da organização.',
			category: 'organization'
		},
		{
			role: 'ipm.organization.list',
			label: 'Listar Organizações',
			description: 'Permite listar as organizações associadas à conta.',
			category: 'organization'
		},
		{
			role: 'ipm.organization.update',
			label: 'Editar Organização',
			description: 'Permite alterar configurações, identificador único e políticas da organização.',
			category: 'organization'
		},
		{
			role: 'ipm.user.get',
			label: 'Visualizar Usuários',
			description: 'Permite consultar o perfil de membros e usuários.',
			category: 'user'
		},
		{
			role: 'ipm.user.list',
			label: 'Listar Usuários',
			description: 'Permite visualizar a listagem completa de membros.',
			category: 'user'
		},
		{
			role: 'ipm.user.create',
			label: 'Criar / Convidar Usuários',
			description: 'Permite adicionar e convidar novos membros para a organização.',
			category: 'user'
		},
		{
			role: 'ipm.user.update',
			label: 'Editar Membros',
			description: 'Permite alterar permissões e dados cadastrais dos usuários.',
			category: 'user'
		},
		{
			role: 'ipm.user.delete',
			label: 'Remover Usuários',
			description: 'Permite excluir ou revogar o acesso de membros.',
			category: 'user'
		},
		{
			role: 'ipm.user.bind',
			label: 'Vincular à Organização',
			description: 'Permite associar usuários existentes a esta organização.',
			category: 'user'
		}
	];

	interface Props {
		selectedRoles: GrantableRole[];
		maxHeightClass?: string;
	}

	let { selectedRoles = $bindable([]), maxHeightClass = 'max-h-56' }: Props = $props();

	let searchQuery = $state('');
	let selectedCategory = $state<'all' | 'organization' | 'user' | 'selected'>('all');

	const basicRoles: GrantableRole[] = ['ipm.organization.get', 'ipm.user.get', 'ipm.user.list'];

	const allRoles = ROLE_DEFINITIONS.map((r) => r.role);

	function toggleRole(role: GrantableRole): void {
		if (selectedRoles.includes(role)) {
			selectedRoles = selectedRoles.filter((r) => r !== role);
		} else {
			selectedRoles = [...selectedRoles, role];
		}
	}

	function selectAll(): void {
		selectedRoles = [...allRoles];
	}

	function selectBasic(): void {
		selectedRoles = [...basicRoles];
	}

	function clearAll(): void {
		selectedRoles = [];
	}

	let filteredRoles = $derived.by(() => {
		const query = searchQuery.trim().toLowerCase();
		return ROLE_DEFINITIONS.filter((item) => {
			if (selectedCategory === 'organization' && item.category !== 'organization') return false;
			if (selectedCategory === 'user' && item.category !== 'user') return false;
			if (selectedCategory === 'selected' && !selectedRoles.includes(item.role)) return false;

			if (!query) return true;
			return (
				item.role.toLowerCase().includes(query) ||
				item.label.toLowerCase().includes(query) ||
				item.description.toLowerCase().includes(query)
			);
		});
	});

	let organizationCount = $derived(
		ROLE_DEFINITIONS.filter((r) => r.category === 'organization').length
	);
	let userCount = $derived(ROLE_DEFINITIONS.filter((r) => r.category === 'user').length);
	let selectedCount = $derived(selectedRoles.length);
</script>

<div class="space-y-2.5">
	<!-- Barra de Controles: Busca + Filtro por Categoria + Presets -->
	<div class="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
		<!-- Campo de Busca -->
		<div class="relative flex-1">
			<Search class="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400" />
			<input
				type="text"
				bind:value={searchQuery}
				placeholder="Filtrar por nome, código (ex: ipm.user) ou ação..."
				class="w-full rounded-lg border border-slate-200 bg-white py-1.5 pl-8 pr-7 text-xs text-slate-900 placeholder:text-slate-400 focus:border-brand-600 focus:outline-none"
			/>
			{#if searchQuery}
				<button
					type="button"
					onclick={() => (searchQuery = '')}
					class="absolute right-2 top-1/2 -translate-y-1/2 text-slate-400 hover:text-slate-600"
					aria-label="Limpar filtro"
				>
					<X class="h-3.5 w-3.5" />
				</button>
			{/if}
		</div>

		<!-- Atalhos de Perfil -->
		<div class="flex items-center gap-1.5 self-end sm:self-auto text-xs">
			<button
				type="button"
				onclick={selectBasic}
				class="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-100 transition"
			>
				Perfil Básico
			</button>
			<button
				type="button"
				onclick={selectAll}
				class="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-100 transition"
			>
				Todas
			</button>
			{#if selectedRoles.length > 0}
				<button
					type="button"
					onclick={clearAll}
					class="px-1 text-[11px] font-medium text-slate-500 hover:text-slate-800 hover:underline"
				>
					Limpar
				</button>
			{/if}
		</div>
	</div>

	<!-- Filtro Rápido por Abas/Pills -->
	<div class="flex flex-wrap items-center gap-1.5 text-[11px]">
		<button
			type="button"
			onclick={() => (selectedCategory = 'all')}
			class="rounded-md px-2 py-0.5 font-medium transition {selectedCategory === 'all'
				? 'bg-slate-900 text-white'
				: 'bg-slate-100 text-slate-600 hover:bg-slate-200'}"
		>
			Todas <span class="ml-0.5 opacity-70">({ROLE_DEFINITIONS.length})</span>
		</button>
		<button
			type="button"
			onclick={() => (selectedCategory = 'organization')}
			class="rounded-md px-2 py-0.5 font-medium transition {selectedCategory === 'organization'
				? 'bg-brand-700 text-white'
				: 'bg-slate-100 text-slate-600 hover:bg-slate-200'}"
		>
			Organização <span class="ml-0.5 opacity-70">({organizationCount})</span>
		</button>
		<button
			type="button"
			onclick={() => (selectedCategory = 'user')}
			class="rounded-md px-2 py-0.5 font-medium transition {selectedCategory === 'user'
				? 'bg-brand-700 text-white'
				: 'bg-slate-100 text-slate-600 hover:bg-slate-200'}"
		>
			Usuários <span class="ml-0.5 opacity-70">({userCount})</span>
		</button>
		{#if selectedCount > 0}
			<button
				type="button"
				onclick={() => (selectedCategory = selectedCategory === 'selected' ? 'all' : 'selected')}
				class="rounded-md border px-2 py-0.5 font-semibold transition {selectedCategory ===
				'selected'
					? 'border-brand-600 bg-brand-600 text-white'
					: 'border-brand-200 bg-brand-50 text-brand-800 hover:bg-brand-100'}"
			>
				✓ Apenas Selecionadas <span class="ml-0.5 opacity-90">({selectedCount})</span>
			</button>
		{/if}
	</div>

	<!-- Lista Compacta Rolável (Container com altura controlada e scroll suave) -->
	<div class="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-2xs">
		<div class="{maxHeightClass} overflow-y-auto divide-y divide-slate-100">
			{#if filteredRoles.length === 0}
				<div class="p-6 text-center text-xs text-slate-500">
					Nenhuma permissão encontrada para os filtros aplicados.
				</div>
			{:else}
				{#each filteredRoles as item (item.role)}
					{@const isChecked = selectedRoles.includes(item.role)}
					<!-- Linha compacta clicável -->
					<label
						class="flex cursor-pointer items-center gap-3 px-3 py-2 text-xs transition select-none {isChecked
							? 'bg-brand-50/60 hover:bg-brand-50'
							: 'hover:bg-slate-50'}"
					>
						<input
							type="checkbox"
							checked={isChecked}
							onchange={() => toggleRole(item.role)}
							class="h-4 w-4 shrink-0 rounded border-slate-300 text-brand-600 focus:ring-brand-500"
						/>

						<!-- Código da Permissão -->
						<span
							class="shrink-0 rounded border px-1.5 py-0.5 font-mono text-[10px] transition {isChecked
								? 'border-brand-300 bg-brand-100/70 font-semibold text-brand-900'
								: 'border-slate-200 bg-slate-100 text-slate-700'}"
						>
							{item.role}
						</span>

						<!-- Rótulo e Descrição condensada -->
						<div class="min-w-0 flex-1 truncate">
							<span class="font-semibold text-slate-900">{item.label}</span>
							<span class="mx-1 text-slate-300 hidden sm:inline">—</span>
							<span class="text-[11px] text-slate-500 hidden sm:inline truncate">
								{item.description}
							</span>
						</div>
					</label>
				{/each}
			{/if}
		</div>
	</div>

	<!-- Rodapé Informativo Compacto -->
	<div class="flex items-center justify-between text-[11px] text-slate-500 px-1">
		<span>
			Mostrando {filteredRoles.length} de {ROLE_DEFINITIONS.length} permissões disponíveis
		</span>
		<span class="font-medium {selectedRoles.length > 0 ? 'text-brand-700' : 'text-slate-500'}">
			{selectedRoles.length} selecionada{selectedRoles.length === 1 ? '' : 's'}
		</span>
	</div>
</div>
