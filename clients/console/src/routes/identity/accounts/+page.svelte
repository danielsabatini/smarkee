<script lang="ts">
	import {
		Lock,
		LockOpen,
		ShieldCheck,
		UserCheck,
		Trash2,
		CheckCircle2,
		AlertCircle,
		Pencil,
		X
	} from 'lucide-svelte';
	import CopyableId from '$lib/components/ui/CopyableId.svelte';
	import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';

	const consoleState = getConsoleState();

	let account = $derived(consoleState.account);
	let isUpdating = $state(false);

	// Edição de Perfil
	let isEditModalOpen = $state(false);
	let editGivenName = $state('');
	let editFamilyName = $state('');
	let editEmail = $state('');
	let editFormError = $state<string | null>(null);

	function openEditModal(): void {
		if (!account) return;
		editGivenName = account.desired.givenName ?? '';
		editFamilyName = account.desired.familyName ?? '';
		editEmail = account.desired.email ?? '';
		editFormError = null;
		isEditModalOpen = true;
	}

	function closeEditModal(): void {
		isEditModalOpen = false;
	}

	async function handleUpdateProfile(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		if (!account) return;

		isUpdating = true;
		editFormError = null;
		try {
			await consoleState.updateAccount({
				resourceId: account.resourceId,
				givenName: editGivenName,
				familyName: editFamilyName,
				email: editEmail
			});
			isEditModalOpen = false;
		} catch (err) {
			editFormError = err instanceof Error ? err.message : 'Erro ao atualizar a conta.';
		} finally {
			isUpdating = false;
		}
	}

	async function handleToggleProtection(): Promise<void> {
		if (!account) return;
		isUpdating = true;
		try {
			await consoleState.updateAccount({
				resourceId: account.resourceId,
				deletionProtection: account.desired.deletionProtection === false
			});
		} finally {
			isUpdating = false;
		}
	}

	async function handleDeleteAccount(): Promise<void> {
		if (!account) return;
		if (account.desired.deletionProtection !== false) {
			alert('Desative a proteção contra exclusão antes de excluir a conta.');
			return;
		}
		if (
			confirm(
				'Atenção: A exclusão da conta apagará todo o seu acesso à plataforma. Deseja continuar?'
			)
		) {
			await consoleState.deleteAccount(account.resourceId);
		}
	}
</script>

<svelte:head>
	<title>Smarkee Console — Contas</title>
</svelte:head>

<div class="mx-auto max-w-5xl space-y-6">
	<div class="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
		<div>
			<span class="text-xs font-semibold text-emerald-700 uppercase"> Identidade (IPM) </span>
			<h1 class="mt-0.5 text-2xl font-bold text-slate-900">Conta Titular Autenticada</h1>
			<p class="mt-1 text-xs text-slate-600">
				Visão consolidada da sua conta titular na plataforma.
			</p>
		</div>
	</div>

	{#if account}
		<div class="rounded-2xl border border-slate-200 bg-white p-6 shadow-2xs">
			<div class="flex flex-wrap items-center justify-between gap-4 border-b border-slate-100 pb-4">
				<div class="flex items-center gap-3">
					<div
						class="flex h-12 w-12 items-center justify-center rounded-xl bg-emerald-100 text-emerald-800"
					>
						<UserCheck class="h-6 w-6" aria-hidden="true" />
					</div>
					<div>
						<h2 class="text-lg font-bold text-slate-900">
							{account.desired.givenName}
							{account.desired.familyName}
						</h2>
						{#if account.desired.email}
							<div class="mt-0.5 flex flex-wrap items-center gap-x-2 gap-y-1">
								<span class="text-sm font-medium text-slate-700">{account.desired.email}</span>
								{#if account.observed?.emailVerified}
									<span
										class="inline-flex items-center gap-1 rounded-md bg-emerald-50 px-1.5 py-0.5 text-[10px] font-semibold text-emerald-700 border border-emerald-200"
									>
										<CheckCircle2 class="h-3 w-3" aria-hidden="true" />
										Verificado
									</span>
								{:else}
									<span
										class="inline-flex items-center gap-1 rounded-md bg-amber-50 px-1.5 py-0.5 text-[10px] font-semibold text-amber-700 border border-amber-200"
									>
										<AlertCircle class="h-3 w-3" aria-hidden="true" />
										Não verificado
									</span>
								{/if}
							</div>
						{/if}
						<div class="mt-1">
							<CopyableId
								id={account.resourceId}
								label="ID:"
								idClass="font-mono text-[10px] text-slate-500"
							/>
						</div>
					</div>
				</div>

				<div class="flex items-center gap-2">
					<StatusBadge phase={account.phase} />
					<span
						class="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-xs font-medium text-emerald-800"
					>
						<ShieldCheck class="h-3.5 w-3.5" aria-hidden="true" />
						<span
							>Acesso: {account.desired.platformAccess === 'granted'
								? 'Liberado'
								: 'Bloqueado'}</span
						>
					</span>
					<button
						type="button"
						onclick={openEditModal}
						class="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-2xs transition hover:border-emerald-300 hover:text-emerald-800"
					>
						<Pencil class="h-3.5 w-3.5" aria-hidden="true" />
						<span>Editar Perfil</span>
					</button>
				</div>
			</div>

			<div class="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-2">
				<div class="rounded-xl bg-slate-50 p-3.5">
					<span class="text-[11px] font-medium text-slate-500">Estado da Conta</span>
					<p class="mt-1 text-xs font-semibold text-slate-900">
						{account.observed?.accountState === 'active' || !account.observed?.accountState
							? 'Ativa'
							: account.observed.accountState}
					</p>
				</div>

				<div class="rounded-xl bg-slate-50 p-3.5">
					<span class="text-[11px] font-medium text-slate-500">Proteção contra exclusão</span>
					<div class="mt-1 flex items-center justify-between">
						<p class="flex items-center gap-1.5 text-xs font-semibold text-slate-900">
							{#if account.desired.deletionProtection !== false}
								<Lock class="h-3.5 w-3.5 text-emerald-700" aria-hidden="true" />
								<span>Ativa</span>
							{:else}
								<LockOpen class="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
								<span>Desativada</span>
							{/if}
						</p>
						<button
							type="button"
							disabled={isUpdating}
							onclick={handleToggleProtection}
							class="text-[10px] font-semibold text-emerald-700 hover:underline disabled:opacity-50"
						>
							{account.desired.deletionProtection !== false ? 'Desativar' : 'Ativar'}
						</button>
					</div>
				</div>
			</div>

			<div class="mt-5 border-t border-slate-100 pt-5">
				<h3 class="text-xs font-bold text-slate-900">Permissões da Conta</h3>
				<div class="mt-2 flex flex-wrap gap-1.5">
					{#each account.desired.platformPermissions as role (role)}
						<span
							class="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 font-mono text-xs text-slate-700"
						>
							{role}
						</span>
					{/each}
				</div>
			</div>

			<div class="mt-6 flex justify-end border-t border-red-100 pt-4">
				<button
					type="button"
					onclick={handleDeleteAccount}
					disabled={account.desired.deletionProtection !== false}
					class="inline-flex items-center gap-1.5 rounded-lg border border-red-200 bg-white px-3 py-1.5 text-xs font-semibold text-red-600 transition hover:bg-red-50 disabled:opacity-50 disabled:hover:bg-white"
				>
					<Trash2 class="h-3.5 w-3.5" aria-hidden="true" />
					Excluir Conta
				</button>
			</div>
		</div>
	{/if}
</div>

{#if isEditModalOpen && account}
	<div
		role="dialog"
		aria-modal="true"
		class="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-0"
	>
		<!-- Backdrop -->
		<button
			type="button"
			class="fixed inset-0 cursor-default bg-slate-900/50 backdrop-blur-xs transition-opacity"
			onclick={closeEditModal}
			aria-label="Fechar modal"
		></button>

		<!-- Modal Panel -->
		<div class="relative w-full max-w-lg overflow-hidden rounded-2xl bg-white shadow-xl">
			<div class="flex items-center justify-between border-b border-slate-100 px-5 py-4">
				<div>
					<h3 class="text-lg font-bold text-slate-900">Editar Perfil da Conta</h3>
					<div class="mt-0.5">
						<CopyableId id={account.resourceId} label="ID:" />
					</div>
				</div>
				<button
					type="button"
					onclick={closeEditModal}
					class="rounded-lg p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-600 transition"
				>
					<X class="h-5 w-5" aria-hidden="true" />
				</button>
			</div>

			<form onsubmit={handleUpdateProfile} class="p-5">
				{#if editFormError}
					<div
						role="alert"
						class="mb-4 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800"
					>
						{editFormError}
					</div>
				{/if}

				<div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
					<div>
						<label for="account-given-name" class="block text-xs font-semibold text-slate-700">
							Nome
						</label>
						<input
							id="account-given-name"
							type="text"
							required
							bind:value={editGivenName}
							placeholder="ex: Daniel"
							class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs text-slate-900 focus:border-emerald-600 focus:outline-none"
						/>
					</div>

					<div>
						<label for="account-family-name" class="block text-xs font-semibold text-slate-700">
							Sobrenome
						</label>
						<input
							id="account-family-name"
							type="text"
							required
							bind:value={editFamilyName}
							placeholder="ex: Freitas"
							class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs text-slate-900 focus:border-emerald-600 focus:outline-none"
						/>
					</div>

					<div class="sm:col-span-2">
						<label for="account-email" class="block text-xs font-semibold text-slate-700">
							E-mail
						</label>
						<input
							id="account-email"
							type="email"
							required
							bind:value={editEmail}
							placeholder="ex: daniel.freitas@smarkee.example.com"
							class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs text-slate-900 focus:border-emerald-600 focus:outline-none"
						/>
						<p class="mt-1 text-[11px] text-slate-500">
							Alterar o e-mail exigirá uma nova confirmação para restabelecer a verificação da
							conta.
						</p>
					</div>
				</div>

				<div class="mt-6 flex justify-end gap-3 border-t border-slate-100 pt-4">
					<button
						type="button"
						onclick={closeEditModal}
						class="rounded-xl border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-50 transition"
					>
						Cancelar
					</button>
					<button
						type="submit"
						disabled={isUpdating || (!editGivenName.trim() && !editEmail.trim())}
						class="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50"
					>
						Salvar Alterações
					</button>
				</div>
			</form>
		</div>
	</div>
{/if}
