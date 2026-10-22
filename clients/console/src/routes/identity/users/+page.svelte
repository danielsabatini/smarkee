<script lang="ts">
	import { Plus, Users } from 'lucide-svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';
	import type { GrantableRole } from '$lib/types/resources';

	const consoleState = getConsoleState();

	let givenName = $state('');
	let familyName = $state('');
	let email = $state('');
	let selectedRole = $state<GrantableRole>('ipm.user.get');
	let isSubmitting = $state(false);

	const availableRoles: GrantableRole[] = [
		'ipm.organization.get',
		'ipm.organization.list',
		'ipm.organization.update',
		'ipm.user.bind',
		'ipm.user.create',
		'ipm.user.delete',
		'ipm.user.get',
		'ipm.user.list',
		'ipm.user.update'
	];

	async function handleCreateUser(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		if (!consoleState.activeOrganizationId) {
			return;
		}
		isSubmitting = true;
		try {
			await consoleState.createUser({
				organizationId: consoleState.activeOrganizationId,
				givenName,
				familyName,
				email,
				roles: ['ipm.organization.get', selectedRole],
				deletionProtection: false
			});
			givenName = '';
			familyName = '';
			email = '';
		} finally {
			isSubmitting = false;
		}
	}
</script>

<svelte:head>
	<title>Smarkee Console — Usuários da Organização</title>
</svelte:head>

<div class="mx-auto max-w-6xl space-y-6">
	<div class="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
		<div>
			<span class="text-xs font-semibold text-emerald-700 uppercase"> Identidade (IPM) </span>
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
		<h2 class="text-sm font-bold text-slate-900">Novo Usuário</h2>
		<div class="mt-3 grid grid-cols-1 gap-3 sm:grid-cols-4">
			<div>
				<label for="user-given-name" class="block text-xs font-semibold text-slate-700">
					Nome
				</label>
				<input
					id="user-given-name"
					type="text"
					required
					bind:value={givenName}
					placeholder="Mariana"
					class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs focus:border-emerald-600 focus:outline-none"
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
					placeholder="Silva"
					class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs focus:border-emerald-600 focus:outline-none"
				/>
			</div>
			<div>
				<label for="user-email" class="block text-xs font-semibold text-slate-700"> E-mail </label>
				<input
					id="user-email"
					type="email"
					required
					bind:value={email}
					placeholder="mariana.silva@example.com"
					class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-1.5 text-xs focus:border-emerald-600 focus:outline-none"
				/>
			</div>
			<div>
				<label for="user-role" class="block text-xs font-semibold text-slate-700">
					Permissão inicial
				</label>
				<select
					id="user-role"
					bind:value={selectedRole}
					class="mt-1 w-full rounded-lg border border-slate-300 bg-white px-3 py-1.5 font-mono text-xs focus:border-emerald-600 focus:outline-none"
				>
					{#each availableRoles as role (role)}
						<option value={role}>{role}</option>
					{/each}
				</select>
			</div>
		</div>

		<div class="mt-3 flex justify-end">
			<button
				type="submit"
				disabled={isSubmitting || !consoleState.activeOrganizationId}
				class="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-semibold text-white hover:bg-emerald-700 disabled:opacity-50"
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
						</tr>
					</thead>
					<tbody class="divide-y divide-slate-100">
						{#each consoleState.organizationUsers as user (user.resourceId)}
							<tr data-testid="user-row-{user.resourceId}" class="hover:bg-slate-50/80">
								<td class="px-4 py-3">
									<div class="flex items-center gap-2">
										<Users class="h-4 w-4 text-emerald-700" aria-hidden="true" />
										<span class="font-bold text-slate-900">
											{user.desired.givenName}
											{user.desired.familyName}
										</span>
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
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</div>
</div>
