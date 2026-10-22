<script lang="ts">
	import { Lock, LockOpen, ShieldCheck, UserCheck, Trash2 } from 'lucide-svelte';
	import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';

	const consoleState = getConsoleState();

	let account = $derived(consoleState.account);
	let isUpdating = $state(false);

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
						<p class="font-mono text-xs text-slate-500">{account.resourceId}</p>
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
					{#each account.desired.platformRoles as role (role)}
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
