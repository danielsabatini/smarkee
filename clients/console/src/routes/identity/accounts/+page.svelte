<script lang="ts">
	import { Lock, ShieldCheck, UserCheck } from 'lucide-svelte';
	import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';

	const consoleState = getConsoleState();

	let account = $derived(consoleState.account);
</script>

<svelte:head>
	<title>Smarkee Console — Contas (core.account)</title>
</svelte:head>

<div class="mx-auto max-w-5xl space-y-6">
	<div class="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
		<div>
			<span class="font-mono text-xs font-semibold text-emerald-700 uppercase">
				Identity Provider Manager • core.account
			</span>
			<h1 class="mt-0.5 text-2xl font-bold text-slate-900">Conta Titular Autenticada</h1>
			<p class="mt-1 text-xs text-slate-600">
				Visão consolidada do recurso <code>/v1/core/accounts/&#123;resourceId&#125;</code> exposto pelo
				Receiver.
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
						<span>platformAccess: {account.desired.platformAccess}</span>
					</span>
				</div>
			</div>

			<div class="mt-5 grid grid-cols-1 gap-4 sm:grid-cols-3">
				<div class="rounded-xl bg-slate-50 p-3.5">
					<span class="text-[11px] font-medium text-slate-500">Estado Observado (accountState)</span
					>
					<p class="mt-1 font-mono text-xs font-semibold text-slate-900">
						{account.observed?.accountState ?? 'active'} (presence: {account.observed?.presence ??
							'present'})
					</p>
				</div>

				<div class="rounded-xl bg-slate-50 p-3.5">
					<span class="text-[11px] font-medium text-slate-500">Geração / Versão</span>
					<p class="mt-1 font-mono text-xs font-semibold text-slate-900">
						desiredGeneration: {account.desiredGeneration} • v{account.resourceVersion}
					</p>
				</div>

				<div class="rounded-xl bg-slate-50 p-3.5">
					<span class="text-[11px] font-medium text-slate-500">Proteção contra exclusão</span>
					<p class="mt-1 flex items-center gap-1.5 text-xs font-semibold text-slate-900">
						<Lock class="h-3.5 w-3.5 text-emerald-700" aria-hidden="true" />
						<span>deletionProtection: {String(account.desired.deletionProtection ?? true)}</span>
					</p>
				</div>
			</div>

			<div class="mt-5">
				<h3 class="text-xs font-bold text-slate-900">Roles de Plataforma (platformRoles)</h3>
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
		</div>
	{/if}
</div>
