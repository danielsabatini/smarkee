<script lang="ts">
	import { Building2, Check, Lock, LockOpen, Plus, ShieldCheck, Trash2 } from 'lucide-svelte';
	import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';

	const consoleState = getConsoleState();

	let newOrgDisplayName = $state('');
	let newOrgSlug = $state('');
	let isSlugManuallyEdited = $state(false);
	let deletionProtection = $state(true);
	let formError = $state<string | null>(null);
	let isSubmitting = $state(false);

	function slugify(text: string): string {
		return text
			.normalize('NFD')
			.replace(/[\u0300-\u036f]/g, '') // remove acentos
			.toLowerCase()
			.trim()
			.replace(/[^a-z0-9]+/g, '-') // substitui caracteres inválidos por hífen
			.replace(/^-+|-+$/g, '') // remove hífens das extremidades
			.slice(0, 63);
	}

	function handleDisplayNameInput(value: string): void {
		newOrgDisplayName = value;
		if (!isSlugManuallyEdited) {
			newOrgSlug = slugify(value);
		}
	}

	function handleSlugInput(value: string): void {
		newOrgSlug = value;
		isSlugManuallyEdited = true;
	}

	function handleResetSlug(): void {
		isSlugManuallyEdited = false;
		newOrgSlug = slugify(newOrgDisplayName);
	}

	async function handleCreateOrganization(event: SubmitEvent): Promise<void> {
		event.preventDefault();
		formError = null;
		isSubmitting = true;

		const targetSlug = newOrgSlug.trim() || slugify(newOrgDisplayName);
		if (!targetSlug) {
			formError = 'Por favor, informe um identificador único para a organização.';
			isSubmitting = false;
			return;
		}

		try {
			await consoleState.createOrganization({
				name: targetSlug,
				displayName: newOrgDisplayName.trim() || targetSlug,
				deletionProtection
			});
			newOrgDisplayName = '';
			newOrgSlug = '';
			isSlugManuallyEdited = false;
		} catch (err) {
			formError = err instanceof Error ? err.message : 'Erro ao solicitar criação de Organization.';
		} finally {
			isSubmitting = false;
		}
	}

	async function handleDeleteOrganization(resourceId: string): Promise<void> {
		await consoleState.deleteOrganization(resourceId);
	}
</script>

<svelte:head>
	<title>Smarkee Console — Organizações</title>
</svelte:head>

<div class="mx-auto max-w-6xl space-y-6">
	<div class="flex flex-col justify-between gap-3 sm:flex-row sm:items-center">
		<div>
			<span class="text-xs font-semibold uppercase text-emerald-700"> Identidade (IPM) </span>
			<h1 class="mt-0.5 text-2xl font-bold text-slate-900">Organizações</h1>
			<p class="mt-1 text-xs text-slate-600">
				Gerencie as organizações da sua conta na plataforma.
			</p>
		</div>
	</div>

	<!-- Formulário de criação assíncrona -->
	<form
		onsubmit={handleCreateOrganization}
		class="rounded-2xl border border-slate-200 bg-white p-5 shadow-2xs"
	>
		<div>
			<h2 class="text-sm font-bold text-slate-900">Nova Organização</h2>
			<p class="mt-0.5 text-xs text-slate-500">
				Cadastre uma nova organização para gerenciar acessos, membros e serviços.
			</p>
		</div>

		{#if formError}
			<div
				role="alert"
				class="mt-3 rounded-lg border border-red-200 bg-red-50 px-3 py-2 text-xs text-red-800"
			>
				{formError}
			</div>
		{/if}

		<div class="mt-4 grid grid-cols-1 gap-4 md:grid-cols-2">
			<!-- Nome Completo (Display Name) -->
			<div>
				<label for="org-display-name-input" class="block text-xs font-semibold text-slate-700">
					Nome da Organização
				</label>
				<input
					id="org-display-name-input"
					type="text"
					required
					bind:value={newOrgDisplayName}
					oninput={(e) => handleDisplayNameInput(e.currentTarget.value)}
					placeholder="ex: Smarkee IT Solutions"
					data-testid="create-org-name-input"
					class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 text-xs text-slate-900 placeholder:text-slate-400 focus:border-emerald-600 focus:outline-none"
				/>
				<p class="mt-1 text-[11px] text-slate-500">
					Nome legível exibido no console, cabeçalhos e relatórios.
				</p>
			</div>

			<!-- Identificador Único (Slug DNS) -->
			<div>
				<div class="flex items-center justify-between">
					<label for="org-slug-input" class="block text-xs font-semibold text-slate-700">
						Identificador Único (Slug DNS)
					</label>
					{#if isSlugManuallyEdited}
						<button
							type="button"
							onclick={handleResetSlug}
							class="text-[10px] font-medium text-emerald-700 hover:underline"
						>
							Gerar automaticamente
						</button>
					{/if}
				</div>
				<input
					id="org-slug-input"
					type="text"
					required
					bind:value={newOrgSlug}
					oninput={(e) => handleSlugInput(e.currentTarget.value)}
					placeholder="ex: smarkee-it-solutions"
					data-testid="create-org-slug-input"
					class="mt-1 w-full rounded-lg border border-slate-300 px-3 py-2 font-mono text-xs text-slate-900 placeholder:text-slate-400 focus:border-emerald-600 focus:outline-none"
				/>
				<p class="mt-1 text-[11px] text-slate-500">
					Identificador único em URLs e comandos CLI (apenas letras minúsculas e hífens).
				</p>
			</div>
		</div>

		<div
			class="mt-4 flex flex-col gap-3 border-t border-slate-100 pt-3 sm:flex-row sm:items-center sm:justify-between"
		>
			<label class="flex items-center gap-2 text-xs font-medium text-slate-700">
				<input
					type="checkbox"
					bind:checked={deletionProtection}
					class="h-4 w-4 rounded border-slate-300 text-emerald-600"
				/>
				<span>Proteção contra exclusão</span>
			</label>

			<button
				type="submit"
				disabled={isSubmitting || (!newOrgDisplayName.trim() && !newOrgSlug.trim())}
				data-testid="create-org-submit-button"
				class="inline-flex items-center justify-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50"
			>
				<Plus class="h-4 w-4" aria-hidden="true" />
				<span>Criar Organização</span>
			</button>
		</div>
	</form>

	<!-- Lista de Organizações -->
	<div class="overflow-hidden rounded-2xl border border-slate-200 bg-white shadow-2xs">
		<div class="overflow-x-auto">
			<table class="w-full text-left text-xs">
				<thead>
					<tr
						class="border-b border-slate-200 bg-slate-50 text-[11px] font-semibold text-slate-500"
					>
						<th class="px-4 py-3">Organização</th>
						<th class="px-4 py-3">ID</th>
						<th class="px-4 py-3">Status</th>
						<th class="px-4 py-3">Acesso e Proteção</th>
						<th class="px-4 py-3 text-right">Ações</th>
					</tr>
				</thead>
				<tbody class="divide-y divide-slate-100">
					{#each consoleState.organizations as org (org.resourceId)}
						{@const isActive = org.resourceId === consoleState.activeOrganizationId}
						{@const demoMeta = consoleState.adapter.getOrganizationMetadataDemo(org.resourceId)}
						<tr
							data-testid="organization-table-row-{org.desired.name}"
							class="transition hover:bg-slate-50/80 {isActive ? 'bg-emerald-50/30' : ''}"
						>
							<td class="px-4 py-3">
								<div class="flex items-center gap-2.5">
									<Building2 class="h-4 w-4 shrink-0 text-emerald-700" aria-hidden="true" />
									<div>
										<span class="font-bold text-slate-900">{demoMeta.displayName}</span>
										<span class="ml-1 font-mono text-[11px] text-slate-500">
											({org.desired.name})
										</span>
									</div>
								</div>
							</td>
							<td class="px-4 py-3 font-mono text-[11px] text-slate-600">{org.resourceId}</td>
							<td class="px-4 py-3">
								<StatusBadge phase={org.phase} size="sm" />
							</td>
							<td class="px-4 py-3">
								<div class="flex items-center gap-3 text-[11px]">
									<span class="inline-flex items-center gap-1 font-medium text-emerald-700">
										<ShieldCheck class="h-3.5 w-3.5" aria-hidden="true" />
										{org.desired.platformAccess === 'granted' ? 'Liberado' : 'Bloqueado'}
									</span>
									{#if org.desired.deletionProtection !== false}
										<span class="inline-flex items-center gap-1 text-slate-600">
											<Lock class="h-3.5 w-3.5 text-emerald-700" aria-hidden="true" />
											Protegida
										</span>
									{:else}
										<span class="inline-flex items-center gap-1 text-amber-700">
											<LockOpen class="h-3.5 w-3.5" aria-hidden="true" />
											Desprotegida
										</span>
									{/if}
								</div>
							</td>
							<td class="px-4 py-3 text-right">
								<div class="inline-flex items-center gap-2">
									{#if isActive}
										<span
											class="inline-flex items-center gap-1 rounded-lg bg-emerald-100 px-2.5 py-1 text-[11px] font-semibold text-emerald-900"
										>
											<Check class="h-3 w-3" aria-hidden="true" />
											Contexto ativo
										</span>
									{:else}
										<button
											type="button"
											onclick={() => consoleState.selectOrganization(org.resourceId)}
											class="rounded-lg border border-slate-200 bg-white px-2.5 py-1 text-[11px] font-semibold text-slate-700 hover:border-emerald-300 hover:text-emerald-800"
										>
											Selecionar
										</button>
									{/if}

									<button
										type="button"
										onclick={() => handleDeleteOrganization(org.resourceId)}
										aria-label="Solicitar exclusão da organização {org.desired.name}"
										data-testid="delete-org-{org.desired.name}"
										class="rounded-lg border border-red-200 bg-red-50 p-1.5 text-red-700 hover:bg-red-100"
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
	</div>
</div>
