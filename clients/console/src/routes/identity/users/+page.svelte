<script lang="ts">
	import { Trash2, Plus, Users, Lock, LockOpen, Pencil, X } from 'lucide-svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
	import PermissionSelector from '$lib/components/identity/PermissionSelector.svelte';
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
			selectedRoles = ['ipm.organization.get', 'ipm.user.get', 'ipm.user.list'];
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
	let editGivenName = $state('');
	let editFamilyName = $state('');
	let editEmail = $state('');
	let editSelectedRoles = $state<GrantableRole[]>([]);
	let isUpdatingUser = $state(false);

	function startEditUser(user: OrganizationUserResource): void {
		editingUser = user;
		editGivenName = user.desired.givenName ?? '';
		editFamilyName = user.desired.familyName ?? '';
		editEmail = user.desired.email ?? '';
		editSelectedRoles = [...user.desired.roles];
	}

	function cancelEditUser(): void {
		editingUser = null;
	}

	async function handleUpdateUser(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		if (!editingUser) return;

		isUpdatingUser = true;
		try {
			await consoleState.updateUser({
				resourceId: editingUser.resourceId,
				givenName: editGivenName,
				familyName: editFamilyName,
				email: editEmail,
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

		<!-- Permissões / Roles (Compacto e Escalável) -->
		<div class="mt-5 border-t border-slate-100 pt-4">
			<div class="mb-2.5">
				<span class="block text-xs font-semibold text-slate-900"> Permissões na Organização </span>
				<p class="mt-0.5 text-[11px] text-slate-500">
					Selecione as permissões que este usuário terá na organização.
				</p>
			</div>
			<PermissionSelector bind:selectedRoles maxHeightClass="max-h-48" />
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
							<th class="px-4 py-3">Fase</th>
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
					<h3 class="text-lg font-bold text-slate-900">Editar Usuário</h3>
					<p class="mt-0.5 text-xs text-slate-500 font-mono">
						ID: {editingUser.resourceId}
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

			<form onsubmit={handleUpdateUser} class="p-5">
				<!-- Dados Cadastrais -->
				<div class="mb-5 grid grid-cols-1 gap-3 sm:grid-cols-3">
					<div>
						<label for="edit-user-given-name" class="block text-xs font-semibold text-slate-700">
							Nome
						</label>
						<input
							id="edit-user-given-name"
							type="text"
							required
							bind:value={editGivenName}
							placeholder="ex: Mariana"
							class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-emerald-600 focus:outline-none"
						/>
					</div>
					<div>
						<label for="edit-user-family-name" class="block text-xs font-semibold text-slate-700">
							Sobrenome
						</label>
						<input
							id="edit-user-family-name"
							type="text"
							required
							bind:value={editFamilyName}
							placeholder="ex: Silva"
							class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-emerald-600 focus:outline-none"
						/>
					</div>
					<div>
						<label for="edit-user-email" class="block text-xs font-semibold text-slate-700">
							E-mail
						</label>
						<input
							id="edit-user-email"
							type="email"
							required
							bind:value={editEmail}
							placeholder="ex: mariana.silva@example.com"
							class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs focus:border-emerald-600 focus:outline-none"
						/>
					</div>
				</div>

				<!-- Permissões / Roles (Compacto e Escalável) -->
				<div class="border-t border-slate-100 pt-4">
					<div class="mb-2.5">
						<span class="block text-xs font-semibold text-slate-900">
							Permissões na Organização
						</span>
						<p class="mt-0.5 text-[11px] text-slate-500">
							Selecione as ações permitidas para o usuário na organização.
						</p>
					</div>
					<PermissionSelector bind:selectedRoles={editSelectedRoles} maxHeightClass="max-h-56" />
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
