<script lang="ts">
	import { ArrowRight, Building2, Lock, LockOpen, ShieldCheck } from 'lucide-svelte';
	import CopyableId from '$lib/components/ui/CopyableId.svelte';
	import DemoBadge from '$lib/components/ui/DemoBadge.svelte';
	import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';

	const consoleState = getConsoleState();

	let activeOrg = $derived(consoleState.activeOrganization);
	let demoMeta = $derived(consoleState.activeOrganizationDemoMeta);
</script>

{#if consoleState.isBootstrapping || consoleState.isSwitchingOrganization}
	<section
		aria-label="Carregando resumo da organização"
		class="animate-pulse rounded-2xl border border-emerald-200/80 bg-gradient-to-r from-emerald-50/80 via-white to-emerald-50/50 p-6"
	>
		<div class="h-4 w-32 rounded bg-emerald-200/60"></div>
		<div class="mt-2 h-7 w-64 rounded bg-emerald-200/80"></div>
		<div class="mt-4 grid grid-cols-2 gap-4 sm:grid-cols-4">
			<div class="h-10 rounded bg-slate-200/60"></div>
			<div class="h-10 rounded bg-slate-200/60"></div>
			<div class="h-10 rounded bg-slate-200/60"></div>
			<div class="h-10 rounded bg-slate-200/60"></div>
		</div>
	</section>
{:else if activeOrg}
	<section
		aria-label="Resumo da Organização Selecionada"
		data-testid="organization-summary-card"
		class="relative overflow-hidden rounded-2xl border border-emerald-200/90 bg-gradient-to-r from-emerald-50/90 via-white to-emerald-100/60 p-5 shadow-xs sm:p-6"
	>
		<div class="flex flex-col justify-between gap-4 sm:flex-row sm:items-start">
			<div class="flex items-start gap-3.5">
				<div
					class="flex h-12 w-12 shrink-0 items-center justify-center rounded-2xl border border-emerald-200 bg-emerald-100/90 text-emerald-800 shadow-2xs sm:h-14 sm:w-14"
				>
					<Building2 class="h-6 w-6 sm:h-7 sm:w-7" aria-hidden="true" />
				</div>

				<div>
					<span class="text-xs font-medium text-slate-600">Organização atual</span>
					<div class="mt-0.5 flex flex-wrap items-center gap-2">
						<h2
							data-testid="summary-organization-title"
							class="text-xl font-bold tracking-tight text-slate-900 sm:text-2xl"
						>
							{demoMeta?.displayName ?? activeOrg.desired.name}
						</h2>
						<StatusBadge
							phase={activeOrg.phase}
							customLabel={activeOrg.phase === 'Ready' ? 'Ativa' : activeOrg.phase}
						/>
						<span
							class="inline-flex items-center gap-1 rounded-full border border-emerald-200 bg-white/80 px-2 py-0.5 text-[11px] font-medium text-emerald-800"
						>
							<ShieldCheck class="h-3 w-3 text-emerald-600" aria-hidden="true" />
							<span>
								Acesso: {activeOrg.desired.platformAccess === 'granted' ? 'Liberado' : 'Bloqueado'}
							</span>
						</span>
					</div>
					<div class="mt-1.5 flex items-center">
						<CopyableId
							id={activeOrg.resourceId}
							label="ID:"
							idClass="font-mono text-[11px] font-semibold text-slate-700"
							testId="copy-organization-id"
							idTestId="summary-organization-id"
							ariaLabel="Copiar identificador da organização"
						/>
					</div>
				</div>
			</div>

			<a
				href="/identity/organizations"
				class="inline-flex shrink-0 items-center gap-1.5 self-start rounded-xl border border-slate-300 bg-white px-3.5 py-2 text-xs font-semibold text-slate-800 shadow-2xs transition hover:border-emerald-400 hover:text-emerald-800"
			>
				<span>Abrir detalhes</span>
				<ArrowRight class="h-3.5 w-3.5" aria-hidden="true" />
			</a>
		</div>

		<dl
			class="mt-5 grid grid-cols-1 gap-3 border-t border-emerald-200/60 pt-4 sm:grid-cols-2 lg:grid-cols-4"
		>
			<div class="min-w-0">
				<dt class="text-[11px] font-medium text-slate-500">Identificador Único</dt>
				<dd
					class="mt-1 truncate font-mono text-xs font-semibold whitespace-nowrap text-slate-900"
					title={activeOrg.desired.name}
				>
					{activeOrg.desired.name}
				</dd>
			</div>

			<div class="min-w-0 sm:border-l sm:border-emerald-200/60 sm:pl-3">
				<dt class="text-[11px] font-medium text-slate-500">Proteção contra exclusão</dt>
				<dd
					class="mt-1 flex items-center gap-1.5 text-xs font-semibold whitespace-nowrap text-slate-900"
				>
					{#if activeOrg.desired.deletionProtection !== false}
						<Lock class="h-3.5 w-3.5 shrink-0 text-emerald-700" aria-hidden="true" />
						<span>Ativa</span>
					{:else}
						<LockOpen class="h-3.5 w-3.5 shrink-0 text-amber-600" aria-hidden="true" />
						<span>Desativada</span>
					{/if}
				</dd>
			</div>

			<div class="min-w-0 sm:border-l sm:border-emerald-200/60 sm:pl-3">
				<dt class="flex items-center gap-1.5 text-[11px] font-medium text-slate-500">
					<span>Plano / Região</span>
					<DemoBadge label="Demo" />
				</dt>
				<dd class="mt-1 truncate text-xs font-semibold whitespace-nowrap text-slate-900">
					{demoMeta?.planDemo ?? 'Enterprise'} • {demoMeta?.primaryRegionDemo ?? 'us-east-1'}
				</dd>
			</div>

			<div class="min-w-0 sm:border-l sm:border-emerald-200/60 sm:pl-3">
				<dt class="text-[11px] font-medium text-slate-500">Membros</dt>
				<dd
					data-testid="summary-organization-members"
					class="mt-1 truncate text-xs font-semibold whitespace-nowrap text-slate-900"
				>
					{demoMeta?.memberCount ?? consoleState.organizationUsers.length} ({consoleState
						.organizationUsers.length} ativos)
				</dd>
			</div>
		</dl>
	</section>
{/if}
