<script lang="ts">
	import { Trash2, Plus, Users, Lock, LockOpen, Pencil, X } from 'lucide-svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';
	import type { GrantableRole, OrganizationUserResource } from '$lib/types/resources';

	const consoleState = getConsoleState();

	let givenName = $state('');
	let familyName = $state('');
	let email = $state('');
	let selectedRoles = $state<GrantableRole[]>([
		'ipm.organization.get',
		'ipm.user.get',
		'ipm.user.list'
	]);
	let isSubmitting = $state(false);

	interface RoleDefinition {
		role: GrantableRole;
		label: string;
		description: string;
	}

	const organizationRoles: RoleDefinition[] = [
		{
			role: 'ipm.organization.get',
			label: 'Visualizar Organização',
			description: 'Permite consultar os dados e metadados da organização.'
		},
		{
			role: 'ipm.organization.list',
			label: 'Listar Organizações',
			description: 'Permite listar as organizações associadas à conta.'
		},
		{
			role: 'ipm.organization.update',
			label: 'Editar Organização',
			description: 'Permite alterar configurações, slug e políticas da organização.'
		}
	];

	const userRoles: RoleDefinition[] = [
		{
			role: 'ipm.user.get',
			label: 'Visualizar Usuários',
			description: 'Permite consultar o perfil de membros e usuários.'
		},
		{
			role: 'ipm.user.list',
			label: 'Listar Usuários',
			description: 'Permite visualizar a listagem completa de membros.'
		},
		{
			role: 'ipm.user.create',
			label: 'Criar / Convidar Usuários',
			description: 'Permite adicionar e convidar novos membros para a organização.'
		},
		{
			role: 'ipm.user.update',
			label: 'Editar Membros',
			description: 'Permite alterar permissões e dados cadastrais dos usuários.'
		},
		{
			role: 'ipm.user.delete',
			label: 'Remover Usuários',
			description: 'Permite excluir ou revogar o acesso de membros.'
		},
		{
			role: 'ipm.user.bind',
			label: 'Vincular à Organização',
			description: 'Permite associar usuários existentes a esta organização.'
		}
	];

	const allRoles: GrantableRole[] = [
		...organizationRoles.map((r) => r.role),
		...userRoles.map((r) => r.role)
	];

	function toggleRole(role: GrantableRole): void {
		if (selectedRoles.includes(role)) {
			selectedRoles = selectedRoles.filter((r) => r !== role);
		} else {
			selectedRoles = [...selectedRoles, role];
		}
	}

	function selectAllRoles(): void {
		selectedRoles = [...allRoles];
	}

	function selectBasicRoles(): void {
		selectedRoles = ['ipm.organization.get', 'ipm.user.get', 'ipm.user.list'];
	}

	function clearRoles(): void {
		selectedRoles = [];
	}

	async function handleCreateUser(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		if (!consoleState.activeOrganizationId || selectedRoles.length === 0) {
			return;
		}
		isSubmitting = true;
		try {
			await consoleState.createUser({
				organizationId: consoleState.activeOrganizationId,
				givenName,
				familyName,
				email,
				roles: [...selectedRoles],
				deletionProtection: false
			});
			givenName = '';
			familyName = '';
			email = '';
			selectBasicRoles();
		} finally {
			isSubmitting = false;
		}
	}
	async function handleDeleteUser(resourceId: string): Promise<void> {
		if (confirm('Tem certeza de que deseja excluir este usuário?')) {
			await consoleState.deleteUser(resourceId);
		}
	}
	async function handleToggleUserProtection(user: OrganizationUserResource): Promise<void> {
		await consoleState.updateUser({
			resourceId: user.resourceId,
			deletionProtection: user.desired.deletionProtection === false
		});
	}

	// Edição
	let editingUser = $state<OrganizationUserResource | null>(null);
	let editSelectedRoles = $state<GrantableRole[]>([]);
	let isUpdatingUser = $state(false);

	function startEditUser(user: OrganizationUserResource): void {
		editingUser = user;
		editSelectedRoles = [...user.desired.roles];
	}

	function cancelEditUser(): void {
		editingUser = null;
	}

	function toggleEditRole(role: GrantableRole): void {
		if (editSelectedRoles.includes(role)) {
			editSelectedRoles = editSelectedRoles.filter((r) => r !== role);
		} else {
			editSelectedRoles = [...editSelectedRoles, role];
		}
	}

	function selectBasicEditRoles(): void {
		editSelectedRoles = ['ipm.organization.get', 'ipm.user.get', 'ipm.user.list'];
	}

	function selectAllEditRoles(): void {
		editSelectedRoles = [...allRoles];
	}

	function clearEditRoles(): void {
		editSelectedRoles = [];
	}

	async function handleUpdateUserRoles(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		if (!editingUser) return;

		isUpdatingUser = true;
		try {
			await consoleState.updateUser({
				resourceId: editingUser.resourceId,
				roles: editSelectedRoles
			});
			editingUser = null;
		} finally {
			isUpdatingUser = false;
		}
	}
</script>

<svelte:head>
	<title>Smarkee Console — Usuários da Organização</title>
</svelte:head>

<div class="mx-auto max-w-6xl space-y-6">
	<div class="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
		<div>
			<span class="text-xs font-semibold uppercase text-emerald-700"> Identidade (IPM) </span>
			<h1 class="mt-0.5 text-2xl font-bold text-slate-900">
				Usuários da Organização ({consoleState.activeOrganization?.desired.name ?? '—'})
			</h1>
			<p class="mt-1 text-xs text-slate-600">
				Usuários vinculados exclusivamente à organização ativa.
			</p>
		</div>
	</div>

	<!-- Formulário para criação de usuário na organização ativa -->
	<form
		onsubmit={handleCreateUser}
		class="rounded-2xl border border-slate-200 bg-white p-5 shadow-2xs"
	>
		<div>
			<h2 class="text-sm font-bold text-slate-900">Novo Usuário</h2>
			<p class="mt-0.5 text-xs text-slate-500">
				Adicione um membro informando seus dados e as permissões de acesso desejadas.
			</p>
		</div>

		<!-- Dados Pessoais -->
		<div class="mt-4 grid grid-cols-1 gap-3 sm:grid-cols-3">
			<div>
				<label for="user-given-name" class="block text-xs font-semibold text-slate-700">
					Nome
				</label>
				<input
					id="user-given-name"
					type="text"
					required
					bind:value={givenName}
					placeholder="ex: Mariana"
					class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-emerald-600 focus:outline-none"
				/>
			</div>
			<div>
				<label for="user-family-name" class="block text-xs font-semibold text-slate-700">
					Sobrenome
				</label>
				<input
					id="user-family-name"
					type="text"
					required
					bind:value={familyName}
					placeholder="ex: Silva"
					class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-emerald-600 focus:outline-none"
				/>
			</div>
			<div>
				<label for="user-email" class="block text-xs font-semibold text-slate-700"> E-mail </label>
				<input
					id="user-email"
					type="email"
					required
					bind:value={email}
					placeholder="ex: mariana.silva@example.com"
					class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-emerald-600 focus:outline-none"
				/>
			</div>
		</div>

		<!-- Permissões / Roles (Multi-Role Selecionável) -->
		<div class="mt-5 border-t border-slate-100 pt-4">
			<div class="flex flex-wrap items-center justify-between gap-2">
				<div>
					<span class="block text-xs font-semibold text-slate-900">
						Permissões na Organização
					</span>
					<p class="mt-0.5 text-[11px] text-slate-500">
						Selecione as ações permitidas ({selectedRoles.length} selecionada{selectedRoles.length ===
						1
							? ''
							: 's'}).
					</p>
				</div>

				<div class="flex items-center gap-2 text-xs">
					<button
						type="button"
						onclick={selectBasicRoles}
						class="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-100"
					>
						Perfil Básico
					</button>
					<button
						type="button"
						onclick={selectAllRoles}
						class="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-800 hover:bg-emerald-100"
					>
						Todas as Permissões
					</button>
					{#if selectedRoles.length > 0}
						<button
							type="button"
							onclick={clearRoles}
							class="text-[11px] font-medium text-slate-500 hover:text-slate-800 hover:underline"
						>
							Limpar
						</button>
					{/if}
				</div>
			</div>

			<!-- Grid dos grupos de permissões -->
			<div class="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
				<!-- Grupo Organização -->
				<div class="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
					<span class="text-xs font-bold text-slate-800">Organização</span>
					<div class="mt-2 space-y-1.5">
						{#each organizationRoles as item (item.role)}
							{@const isChecked = selectedRoles.includes(item.role)}
							<label
								class="flex cursor-pointer items-start gap-2.5 rounded-lg border p-2 transition {isChecked
									? 'border-emerald-300 bg-emerald-50/80 shadow-2xs'
									: 'border-slate-200 bg-white hover:border-slate-300'}"
							>
								<input
									type="checkbox"
									checked={isChecked}
									onchange={() => toggleRole(item.role)}
									class="mt-0.5 h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
								/>
								<div class="min-w-0 flex-1">
									<div class="flex items-center justify-between gap-1">
										<span class="text-xs font-semibold text-slate-900">{item.label}</span>
										<span class="font-mono text-[10px] text-slate-500">{item.role}</span>
									</div>
									<p class="mt-0.5 text-[11px] leading-snug text-slate-500">{item.description}</p>
								</div>
							</label>
						{/each}
					</div>
				</div>

				<!-- Grupo Usuários -->
				<div class="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
					<span class="text-xs font-bold text-slate-800">Membros e Usuários</span>
					<div class="mt-2 space-y-1.5">
						{#each userRoles as item (item.role)}
							{@const isChecked = selectedRoles.includes(item.role)}
							<label
								class="flex cursor-pointer items-start gap-2.5 rounded-lg border p-2 transition {isChecked
									? 'border-emerald-300 bg-emerald-50/80 shadow-2xs'
									: 'border-slate-200 bg-white hover:border-slate-300'}"
							>
								<input
									type="checkbox"
									checked={isChecked}
									onchange={() => toggleRole(item.role)}
									class="mt-0.5 h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
								/>
								<div class="min-w-0 flex-1">
									<div class="flex items-center justify-between gap-1">
										<span class="text-xs font-semibold text-slate-900">{item.label}</span>
										<span class="font-mono text-[10px] text-slate-500">{item.role}</span>
									</div>
									<p class="mt-0.5 text-[11px] leading-snug text-slate-500">{item.description}</p>
								</div>
							</label>
						{/each}
					</div>
				</div>
			</div>
		</div>

		<div class="mt-4 flex items-center justify-end border-t border-slate-100 pt-3">
			<button
				type="submit"
				disabled={isSubmitting || !consoleState.activeOrganizationId || selectedRoles.length === 0}
				class="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50"
			>
				<Plus class="h-4 w-4" aria-hidden="true" />
				<span>Adicionar Usuário</span>
			</button>
		</div>
	</form>

	<!-- Tabela de usuários da organização ativa -->
	<div
		data-testid="organization-users-table"
		class="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xs"
	>
		{#if consoleState.isSwitchingOrganization}
			<div class="p-8 text-center text-xs text-slate-500">Alternando organização...</div>
		{:else if consoleState.organizationUsers.length === 0}
			<div class="p-6">
				<EmptyState
					title="Nenhum usuário nesta organização"
					description="Utilize o formulário acima para adicionar um usuário à organização ativa."
				/>
			</div>
		{:else}
			<div class="overflow-x-auto">
				<table class="w-full text-left text-xs">
					<thead>
						<tr
							class="border-b border-slate-200 bg-slate-50 text-[11px] font-semibold text-slate-500"
						>
							<th class="px-4 py-3">Nome</th>
							<th class="px-4 py-3">ID</th>
							<th class="px-4 py-3">Organização</th>
							<th class="px-4 py-3">Status</th>
							<th class="px-4 py-3">Permissões</th>
							<th class="px-4 py-3 text-right">Ações</th>
						</tr>
					</thead>
					<tbody class="divide-y divide-slate-100">
						{#each consoleState.organizationUsers as user (user.resourceId)}
							<tr data-testid="user-row-{user.resourceId}" class="hover:bg-slate-50/80">
								<td class="px-4 py-3">
									<div class="flex items-center gap-2.5">
										<Users class="h-4 w-4 shrink-0 text-emerald-700" aria-hidden="true" />
										<div>
											<div class="font-bold text-slate-900">
												{user.desired.givenName}
												{user.desired.familyName}
											</div>
											{#if user.desired.email}
												<div class="mt-0.5 text-[11px] text-slate-500">
													{user.desired.email}
												</div>
											{/if}
										</div>
									</div>
								</td>
								<td class="px-4 py-3 font-mono text-[11px] text-slate-600">{user.resourceId}</td>
								<td class="px-4 py-3 text-[11px] text-slate-700">
									<span class="font-medium"
										>{consoleState.activeOrganization?.desired.name ?? '—'}</span
									>
								</td>
								<td class="px-4 py-3">
									<StatusBadge phase={user.phase} size="sm" />
								</td>
								<td class="px-4 py-3">
									<div class="flex flex-wrap gap-1">
										{#each user.desired.roles as role (role)}
											<span
												class="rounded border border-slate-200 bg-slate-50 px-1.5 py-0.5 font-mono text-[10px] text-slate-700"
											>
												{role}
											</span>
										{/each}
									</div>
								</td>
								<td class="px-4 py-3 text-right text-xs">
									<div class="inline-flex gap-1.5">
										<button
											type="button"
											onclick={() => startEditUser(user)}
											title="Editar Permissões"
											class="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-transparent text-slate-400 hover:text-emerald-700"
										>
											<Pencil class="h-3.5 w-3.5" aria-hidden="true" />
										</button>

										<button
											type="button"
											onclick={() => handleToggleUserProtection(user)}
											title={user.desired.deletionProtection !== false
												? 'Desativar Proteção'
												: 'Ativar Proteção'}
											class="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-transparent text-slate-400 hover:text-emerald-700"
										>
											{#if user.desired.deletionProtection !== false}
												<Lock class="h-3.5 w-3.5 text-emerald-700" aria-hidden="true" />
											{:else}
												<LockOpen class="h-3.5 w-3.5" aria-hidden="true" />
											{/if}
										</button>

										<button
											type="button"
											onclick={() => handleDeleteUser(user.resourceId)}
											disabled={user.desired.deletionProtection !== false}
											aria-label="Excluir Usuário"
											title="Excluir Usuário"
											class="inline-flex h-7 w-7 items-center justify-center rounded-lg border border-transparent text-slate-400 hover:border-red-200 hover:bg-red-50 hover:text-red-600 disabled:opacity-50 disabled:hover:bg-transparent disabled:hover:border-transparent disabled:hover:text-slate-400"
										>
											<Trash2 class="h-3.5 w-3.5" aria-hidden="true" />
										</button>
									</div>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
</div>

{#if editingUser}
	<div
		role="dialog"
		aria-modal="true"
		class="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-0"
	>
		<!-- Backdrop -->
		<button
			type="button"
			class="fixed inset-0 cursor-default bg-slate-900/50 backdrop-blur-xs transition-opacity"
			onclick={cancelEditUser}
			aria-label="Fechar modal"
		></button>

		<!-- Modal Panel -->
		<div
			class="relative w-full max-w-2xl max-h-[90vh] overflow-y-auto rounded-2xl bg-white shadow-xl"
		>
			<div class="flex items-center justify-between border-b border-slate-100 px-5 py-4">
				<div>
					<h3 class="text-lg font-bold text-slate-900">Editar Permissões</h3>
					<p class="mt-0.5 text-xs text-slate-500">
						{editingUser.desired.givenName}
						{editingUser.desired.familyName}
						{#if editingUser.desired.email}
							<span class="mx-1.5 inline-block h-1 w-1 rounded-full bg-slate-300 align-middle"
							></span>
							{editingUser.desired.email}
						{/if}
						<span class="mx-1.5 inline-block h-1 w-1 rounded-full bg-slate-300 align-middle"></span>
						<span class="font-mono text-[11px]">{editingUser.resourceId}</span>
					</p>
				</div>
				<button
					type="button"
					onclick={cancelEditUser}
					class="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition"
				>
					<X class="h-5 w-5" aria-hidden="true" />
				</button>
			</div>

			<form onsubmit={handleUpdateUserRoles} class="p-5">
				<!-- Permissões / Roles -->
				<div class="flex flex-wrap items-center justify-between gap-2">
					<div>
						<span class="block text-xs font-semibold text-slate-900">
							Permissões na Organização
						</span>
						<p class="mt-0.5 text-[11px] text-slate-500">
							Selecione as ações permitidas ({editSelectedRoles.length} selecionada{editSelectedRoles.length ===
							1
								? ''
								: 's'}).
						</p>
					</div>

					<div class="flex items-center gap-2 text-xs">
						<button
							type="button"
							onclick={selectBasicEditRoles}
							class="rounded-md border border-slate-200 bg-slate-50 px-2 py-1 text-[11px] font-medium text-slate-700 hover:bg-slate-100"
						>
							Perfil Básico
						</button>
						<button
							type="button"
							onclick={selectAllEditRoles}
							class="rounded-md border border-emerald-200 bg-emerald-50 px-2 py-1 text-[11px] font-semibold text-emerald-800 hover:bg-emerald-100"
						>
							Todas as Permissões
						</button>
						{#if editSelectedRoles.length > 0}
							<button
								type="button"
								onclick={clearEditRoles}
								class="text-[11px] font-medium text-slate-500 hover:text-slate-800 hover:underline"
							>
								Limpar
							</button>
						{/if}
					</div>
				</div>

				<!-- Grid dos grupos de permissões -->
				<div class="mt-3 grid grid-cols-1 gap-3 md:grid-cols-2">
					<!-- Grupo Organização -->
					<div class="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
						<span class="text-xs font-bold text-slate-800">Organização</span>
						<div class="mt-2 space-y-1.5">
							{#each organizationRoles as item (item.role)}
								{@const isChecked = editSelectedRoles.includes(item.role)}
								<label
									class="flex cursor-pointer items-start gap-2.5 rounded-lg border p-2 transition {isChecked
										? 'border-emerald-300 bg-emerald-50/80 shadow-2xs'
										: 'border-slate-200 bg-white hover:border-slate-300'}"
								>
									<input
										type="checkbox"
										checked={isChecked}
										onchange={() => toggleEditRole(item.role)}
										class="mt-0.5 h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
									/>
									<div class="min-w-0 flex-1">
										<div class="flex items-center justify-between gap-1">
											<span class="text-xs font-semibold text-slate-900">{item.label}</span>
											<span class="font-mono text-[10px] text-slate-500">{item.role}</span>
										</div>
										<p class="mt-0.5 text-[11px] leading-snug text-slate-500">{item.description}</p>
									</div>
								</label>
							{/each}
						</div>
					</div>

					<!-- Grupo Usuários -->
					<div class="rounded-xl border border-slate-200 bg-slate-50/60 p-3">
						<span class="text-xs font-bold text-slate-800">Membros e Usuários</span>
						<div class="mt-2 space-y-1.5">
							{#each userRoles as item (item.role)}
								{@const isChecked = editSelectedRoles.includes(item.role)}
								<label
									class="flex cursor-pointer items-start gap-2.5 rounded-lg border p-2 transition {isChecked
										? 'border-emerald-300 bg-emerald-50/80 shadow-2xs'
										: 'border-slate-200 bg-white hover:border-slate-300'}"
								>
									<input
										type="checkbox"
										checked={isChecked}
										onchange={() => toggleEditRole(item.role)}
										class="mt-0.5 h-4 w-4 rounded border-slate-300 text-emerald-600 focus:ring-emerald-500"
									/>
									<div class="min-w-0 flex-1">
										<div class="flex items-center justify-between gap-1">
											<span class="text-xs font-semibold text-slate-900">{item.label}</span>
											<span class="font-mono text-[10px] text-slate-500">{item.role}</span>
										</div>
										<p class="mt-0.5 text-[11px] leading-snug text-slate-500">{item.description}</p>
									</div>
								</label>
							{/each}
						</div>
					</div>
				</div>

				<div class="mt-6 flex justify-end gap-3 border-t border-slate-100 pt-4">
					<button
						type="button"
						onclick={cancelEditUser}
						class="rounded-xl border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 transition"
					>
						Cancelar
					</button>
					<button
						type="submit"
						disabled={isUpdatingUser || editSelectedRoles.length === 0}
						class="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50"
					>
						Salvar Alterações
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}
