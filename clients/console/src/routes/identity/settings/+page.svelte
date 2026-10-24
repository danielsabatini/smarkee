<script lang="ts">
	import { ShieldCheck } from 'lucide-svelte';
	import DemoBadge from '$lib/components/ui/DemoBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';

	const consoleState = getConsoleState();
</script>

<svelte:head>
	<title>Smarkee Console — Configurações de Identidade (Preview)</title>
</svelte:head>

<div class="mx-auto max-w-4xl space-y-6">
	<div class="flex flex-wrap items-center justify-between gap-2">
		<div>
			<span class="font-mono text-xs font-semibold text-brand-700 uppercase">
				Identity Provider Manager
			</span>
			<h1 class="mt-0.5 text-2xl font-bold text-slate-900">Configurações de Identidade</h1>
		</div>
		<DemoBadge label="Preview / Demonstrativo" />
	</div>

	<div class="rounded-2xl border border-slate-200 bg-white p-6 shadow-2xs">
		<div class="flex items-start gap-3">
			<div
				class="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-brand-50 text-brand-700"
			>
				<ShieldCheck class="h-5 w-5" aria-hidden="true" />
			</div>
			<div>
				<h2 class="text-sm font-bold text-slate-900">
					Políticas de Autenticação da Organization ({consoleState.activeOrganization?.desired
						.name ?? '—'})
				</h2>
				<p class="mt-1 text-xs leading-relaxed text-slate-600">
					Esta seção demonstrativa apresenta as configurações futuras de políticas de MFA, tempo de
					expiração de sessão e provedores OIDC federados por <code>Organization</code> no Zitadel.
				</p>
			</div>
		</div>
	</div>
</div>
