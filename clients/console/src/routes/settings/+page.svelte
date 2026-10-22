<script lang="ts">
	import { Settings, ShieldCheck } from 'lucide-svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';

	const consoleState = getConsoleState();
</script>

<svelte:head>
	<title>Smarkee Console — Configurações e Sessão OIDC</title>
</svelte:head>

<div class="mx-auto max-w-5xl space-y-6">
	<div>
		<span class="text-xs font-semibold text-emerald-700 uppercase">Administração</span>
		<h1 class="mt-0.5 text-2xl font-bold text-slate-900">Configurações do Console e Integração</h1>
		<p class="mt-1 text-xs text-slate-600">
			Parâmetros de integração do provedor de identidade e roteamento.
		</p>
	</div>

	{#if consoleState.userContext}
		{@const auth = consoleState.userContext.authConfig}
		<div class="rounded-2xl border border-slate-200 bg-white p-6 shadow-2xs">
			<div class="flex items-center gap-2.5 border-b border-slate-100 pb-4">
				<div
					class="flex h-10 w-10 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700"
				>
					<ShieldCheck class="h-5 w-5" aria-hidden="true" />
				</div>
				<div>
					<h2 class="text-sm font-bold text-slate-900">Parâmetros de Autenticação Públicos</h2>
					<p class="text-xs text-slate-500">
						Configurações locais do Console. Nenhum segredo é armazenado no navegador.
					</p>
				</div>
			</div>

			<dl class="mt-4 grid grid-cols-1 gap-3 text-xs sm:grid-cols-3">
				<div class="rounded-xl bg-slate-50 p-3">
					<dt class="text-[11px] font-medium text-slate-500">Issuer</dt>
					<dd class="mt-1 break-all font-mono font-semibold text-slate-900">{auth.issuer}</dd>
				</div>
				<div class="rounded-xl bg-slate-50 p-3">
					<dt class="text-[11px] font-medium text-slate-500">Client ID</dt>
					<dd class="mt-1 break-all font-mono font-semibold text-slate-900">{auth.clientId}</dd>
				</div>
				<div class="rounded-xl bg-slate-50 p-3">
					<dt class="text-[11px] font-medium text-slate-500">Redirect URI</dt>
					<dd class="mt-1 break-all font-mono font-semibold text-slate-900">{auth.redirectUri}</dd>
				</div>
			</dl>

			<div class="mt-4">
				<h3 class="text-xs font-bold text-slate-900">Escopos de Acesso Requisitados</h3>
				<div class="mt-2 flex flex-wrap gap-1.5">
					{#each auth.scopes as scope (scope)}
						<span
							class="rounded-md border border-slate-200 bg-slate-50 px-2.5 py-1 font-mono text-[11px] text-slate-700"
						>
							{scope}
						</span>
					{/each}
				</div>
			</div>
		</div>
	{/if}

	<div class="rounded-2xl border border-slate-200 bg-white p-6 shadow-2xs">
		<div class="flex items-center gap-2.5">
			<Settings class="h-5 w-5 text-emerald-700" aria-hidden="true" />
			<h2 class="text-sm font-bold text-slate-900">Adaptador de Dados Ativo</h2>
		</div>
		<p class="mt-2 text-xs leading-relaxed text-slate-600">
			O Console está operando em modo demonstrativo isolado, simulando as operações do backend
			localmente.
		</p>
	</div>
</div>
