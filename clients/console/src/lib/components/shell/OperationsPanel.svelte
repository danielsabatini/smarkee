<script lang="ts">
	import {
		AlertTriangle,
		ArrowRight,
		Bell,
		CheckCheck,
		CheckCircle2,
		Loader2,
		ShieldAlert,
		X,
		XCircle
	} from 'lucide-svelte';
	import CopyableId from '$lib/components/ui/CopyableId.svelte';
	import EmptyState from '$lib/components/ui/EmptyState.svelte';
	import StatusBadge from '$lib/components/ui/StatusBadge.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';
	import {
		formatResourceType,
		formatOperationAction,
		formatOperationTag
	} from '$lib/utils/formatters';
	import type { OperationTitleInfo } from '$lib/types/console';

	const consoleState = getConsoleState();

	function formatReasonLabel(reason?: string): string {
		switch (reason) {
			case 'protected':
				return 'Protegido contra exclusão';
			case 'conflict':
				return 'Conflito de unicidade ou versão';
			case 'validation':
				return 'Falha na validação das informações';
			case 'not_found':
				return 'Recurso não encontrado';
			default:
				return reason ?? 'Não especificado';
		}
	}

	function formatRelativeTimestamp(iso: string): string {
		if (!iso.includes('T')) {
			return iso;
		}
		const time = iso.slice(11, 19);
		return `${time} UTC`;
	}

	function openOperationModal(entry: OperationTitleInfo): void {
		consoleState.selectedOperationForModal = entry;
	}

	function closeOperationModal(): void {
		consoleState.selectedOperationForModal = null;
	}

	function handleKeydown(event: KeyboardEvent): void {
		if (event.key === 'Escape') {
			if (consoleState.selectedOperationForModal) {
				closeOperationModal();
			}
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

{#if consoleState.isOperationsPanelOpen}
	<!-- Overlay em viewports menores que 2xl -->
	<div
		class="fixed inset-0 top-14 z-30 bg-slate-900/30 backdrop-blur-[1px] 2xl:hidden"
		onclick={() => consoleState.closeOperationsPanel()}
		aria-hidden="true"
	></div>
	<aside
		aria-label="Painel de Notificações e Operações"
		data-testid="operations-panel"
		class="fixed top-14 right-0 bottom-0 z-40 flex w-full max-w-sm shrink-0 flex-col border-l border-slate-200 bg-white shadow-xl 2xl:static 2xl:z-auto 2xl:w-80 2xl:max-w-none 2xl:shadow-none"
	>
		<!-- Cabeçalho com abas -->
		<div class="flex h-12 items-center justify-between border-b border-slate-200 px-3">
			<div
				class="flex h-full items-center gap-4"
				role="tablist"
				aria-label="Abas do painel lateral"
			>
				<button
					type="button"
					role="tab"
					aria-selected={consoleState.activePanelTab === 'notifications'}
					onclick={() => (consoleState.activePanelTab = 'notifications')}
					data-testid="tab-notifications"
					class="relative flex h-full items-center gap-1.5 px-1 text-xs font-semibold transition {consoleState.activePanelTab ===
					'notifications'
						? 'text-emerald-700'
						: 'text-slate-600 hover:text-slate-900'}"
				>
					<span>Notificações</span>
					{#if consoleState.unreadNotificationsCount > 0}
						<span
							class="rounded-full bg-emerald-100 px-1.5 py-0.5 text-[10px] font-bold text-emerald-800"
						>
							{consoleState.unreadNotificationsCount}
						</span>
					{/if}
					{#if consoleState.activePanelTab === 'notifications'}
						<span
							class="absolute right-0 bottom-0 left-0 h-0.5 rounded-full bg-emerald-600"
							aria-hidden="true"
						></span>
					{/if}
				</button>

				<button
					type="button"
					role="tab"
					aria-selected={consoleState.activePanelTab === 'operations'}
					onclick={() => (consoleState.activePanelTab = 'operations')}
					data-testid="tab-operations"
					class="relative flex h-full items-center gap-1.5 px-1 text-xs font-semibold transition {consoleState.activePanelTab ===
					'operations'
						? 'text-emerald-700'
						: 'text-slate-600 hover:text-slate-900'}"
				>
					<span>Operações ({consoleState.operations.length})</span>
					{#if consoleState.activePanelTab === 'operations'}
						<span
							class="absolute right-0 bottom-0 left-0 h-0.5 rounded-full bg-emerald-600"
							aria-hidden="true"
						></span>
					{/if}
				</button>
			</div>

			<button
				type="button"
				onclick={() => consoleState.closeOperationsPanel()}
				aria-label="Fechar painel lateral de operações e notificações"
				data-testid="close-operations-panel"
				class="rounded-lg p-1.5 text-slate-400 transition hover:bg-slate-100 hover:text-slate-700"
			>
				<X class="h-4 w-4" aria-hidden="true" />
			</button>
		</div>

		<!-- Conteúdo da Aba Selecionada -->
		<div class="flex-1 overflow-y-auto p-3.5">
			{#if consoleState.activePanelTab === 'operations'}
				<div class="space-y-5" role="tabpanel" aria-label="Lista de operações assíncronas">
					<!-- Seção: Operações em andamento -->
					<div>
						<div class="mb-2">
							<h2 class="text-xs font-bold text-slate-900">Operações em andamento</h2>
							<p class="text-[11px] text-slate-500">
								Acompanhe os estados e eventos da organização.
							</p>
						</div>

						{#if consoleState.inProgressOperations.length === 0}
							<div
								class="rounded-xl border border-slate-200/80 bg-slate-50/70 p-3 text-center text-xs text-slate-500"
							>
								Nenhuma operação pendente ou em andamento neste momento.
							</div>
						{:else}
							<div class="space-y-2.5">
								{#each consoleState.inProgressOperations as entry (entry.operation.operationId)}
									<div
										data-testid="operation-card-{entry.operation.operationId}"
										class="rounded-xl border border-slate-200 bg-white p-3 shadow-xs transition hover:border-emerald-200"
									>
										<div class="flex items-start gap-2.5">
											<div
												class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-50 text-emerald-600"
											>
												<Loader2 class="h-4 w-4 animate-spin" aria-hidden="true" />
											</div>

											<div class="min-w-0 flex-1">
												<div class="flex items-center justify-between gap-1">
													<p class="truncate text-xs font-bold text-slate-900">{entry.title}</p>
													<StatusBadge
														operationStatus={entry.operation.operationStatus}
														size="sm"
													/>
												</div>
												<p class="mt-0.5 text-[11px] text-slate-600">{entry.subtitle}</p>

												<!-- Barra indeterminada honesta (sem percentuais fictícios, docs/console/CONSOLE.md §5.5) -->
												<div
													class="mt-2.5 h-1.5 w-full overflow-hidden rounded-full bg-slate-100"
													role="progressbar"
													aria-label="Operação em andamento (progresso indeterminado)"
												>
													<div class="h-full w-2/3 animate-pulse rounded-full bg-emerald-600"></div>
												</div>

												<div
													class="mt-2 flex flex-wrap items-center justify-between gap-1 text-[11px] text-slate-500"
												>
													<span class="font-medium text-slate-600">
														{formatOperationTag(
															entry.operation.resourceType,
															entry.operation.operationType
														)}
													</span>
													<button
														type="button"
														onclick={() => openOperationModal(entry)}
														class="font-medium text-emerald-700 hover:underline"
													>
														Inspecionar
													</button>
												</div>
											</div>
										</div>
									</div>
								{/each}
							</div>
						{/if}
					</div>

					<!-- Seção: Concluídas recentemente -->
					<div>
						<div class="mb-2">
							<h2 class="text-xs font-bold text-slate-900">Concluídas recentemente</h2>
							<p class="text-[11px] text-slate-500">
								Operações finalizadas com sucesso, falha ou rejeição.
							</p>
						</div>

						{#if consoleState.completedOperations.length === 0}
							<EmptyState
								title="Sem histórico recente"
								description="As operações concluídas aparecerão nesta seção."
							/>
						{:else}
							<div class="space-y-2.5">
								{#each consoleState.completedOperations as entry (entry.operation.operationId)}
									{@const status = entry.operation.operationStatus}
									<div
										data-testid="operation-card-{entry.operation.operationId}"
										class="rounded-xl border border-slate-200 bg-white p-3 shadow-xs"
									>
										<div class="flex items-start gap-2.5">
											{#if status === 'completed'}
												<div
													class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-emerald-100 text-emerald-700"
												>
													<CheckCircle2 class="h-4 w-4" aria-hidden="true" />
												</div>
											{:else if status === 'rejected'}
												<div
													class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-amber-100 text-amber-700"
												>
													<ShieldAlert class="h-4 w-4" aria-hidden="true" />
												</div>
											{:else}
												<div
													class="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-red-100 text-red-700"
												>
													<XCircle class="h-4 w-4" aria-hidden="true" />
												</div>
											{/if}

											<div class="min-w-0 flex-1">
												<div class="flex items-center justify-between gap-1">
													<p class="truncate text-xs font-bold text-slate-900">{entry.title}</p>
													<StatusBadge operationStatus={status} size="sm" />
												</div>
												<p class="mt-0.5 text-[11px] text-slate-600">{entry.subtitle}</p>

												{#if status === 'rejected' && entry.operation.operationStatusReason}
													<div
														class="mt-1.5 rounded-lg border border-amber-200 bg-amber-50/80 px-2 py-1 text-[11px] text-amber-900"
													>
														<span class="font-semibold">Motivo:</span>
														<span class="font-mono">{entry.operation.operationStatusReason}</span>
													</div>
												{/if}

												<div class="mt-2.5 flex items-center justify-between gap-2">
													<span class="text-[11px] text-slate-500">
														{formatRelativeTimestamp(entry.operation.updatedAt)}
													</span>

													<button
														type="button"
														onclick={() => openOperationModal(entry)}
														class="rounded-lg border px-2.5 py-1 text-[11px] font-semibold transition {status ===
															'failed' || status === 'rejected'
															? 'border-red-200 bg-red-50 text-red-700 hover:bg-red-100'
															: 'border-slate-200 bg-slate-50 text-slate-700 hover:bg-slate-100'}"
													>
														{status === 'failed' || status === 'rejected'
															? 'Ver erro'
															: 'Ver detalhes'}
													</button>
												</div>
											</div>
										</div>
									</div>
								{/each}
							</div>
						{/if}
					</div>
				</div>
			{:else}
				<!-- Aba Notificações -->
				<div class="space-y-3" role="tabpanel" aria-label="Lista de notificações">
					<div class="flex items-center justify-between">
						<div>
							<h2 class="text-xs font-bold text-slate-900">Central de Notificações</h2>
							<p class="text-[11px] text-slate-500">Alertas de estado e eventos da organização.</p>
						</div>

						{#if consoleState.unreadNotificationsCount > 0}
							<button
								type="button"
								onclick={() => consoleState.markAllNotificationsAsRead()}
								data-testid="mark-all-notifications-read"
								class="inline-flex items-center gap-1 rounded-lg px-2 py-1 text-[11px] font-semibold text-emerald-700 hover:bg-emerald-50"
							>
								<CheckCheck class="h-3.5 w-3.5" aria-hidden="true" />
								<span>Marcar lidas</span>
							</button>
						{/if}
					</div>

					{#if consoleState.notifications.length === 0}
						<EmptyState
							title="Nenhuma notificação"
							description="Você está em dia com os eventos da organização selecionada."
						/>
					{:else}
						<div class="space-y-2">
							{#each consoleState.notifications as notif (notif.id)}
								<div
									data-testid="notification-item-{notif.id}"
									class="rounded-xl border p-3 transition {notif.read
										? 'border-slate-200 bg-white'
										: 'border-emerald-200 bg-emerald-50/40'}"
								>
									<div class="flex items-start justify-between gap-2">
										<div class="flex items-center gap-1.5">
											{#if notif.severity === 'warning' || notif.severity === 'error'}
												<AlertTriangle
													class="h-3.5 w-3.5 shrink-0 text-amber-600"
													aria-hidden="true"
												/>
											{:else}
												<Bell class="h-3.5 w-3.5 shrink-0 text-emerald-600" aria-hidden="true" />
											{/if}
											<h3 class="text-xs font-semibold text-slate-900">{notif.title}</h3>
										</div>
										{#if !notif.read}
											<span class="h-2 w-2 shrink-0 rounded-full bg-emerald-600" title="Não lida"
											></span>
										{/if}
									</div>
									<p class="mt-1 text-[11px] leading-relaxed text-slate-600">
										{notif.description}
									</p>
									<div class="mt-2 flex items-center justify-between text-[11px] text-slate-500">
										<span>{notif.createdAt}</span>
										{#if !notif.read}
											<button
												type="button"
												onclick={() => consoleState.markNotificationAsRead(notif.id)}
												class="font-medium text-emerald-700 hover:underline"
											>
												Marcar como lida
											</button>
										{/if}
									</div>
								</div>
							{/each}
						</div>
					{/if}
				</div>
			{/if}
		</div>

		<!-- Rodapé do painel -->
		<div class="border-t border-slate-200 bg-slate-50/70 p-3">
			<a
				href="/audit/events"
				class="flex w-full items-center justify-center gap-1.5 rounded-lg border border-slate-200 bg-white py-2 text-xs font-semibold text-emerald-700 shadow-2xs transition hover:border-emerald-300 hover:bg-emerald-50/50"
			>
				<span>Ver todas as operações</span>
				<ArrowRight class="h-3.5 w-3.5" aria-hidden="true" />
			</a>
		</div>
	</aside>
{/if}

<!-- Modal de Diagnóstico de Operation -->
{#if consoleState.selectedOperationForModal}
	{@const selected = consoleState.selectedOperationForModal}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4 backdrop-blur-[1px]"
		role="dialog"
		aria-modal="true"
		aria-label="Detalhes do contrato Operation"
		data-testid="operation-details-modal"
	>
		<div class="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl">
			<div class="flex items-start justify-between gap-3 border-b border-slate-100 pb-3">
				<div>
					<span class="text-[11px] font-semibold text-emerald-700 uppercase">
						Detalhes da Operação
					</span>
					<h2 class="mt-0.5 text-sm font-bold text-slate-900">{selected.title}</h2>
				</div>
				<button
					type="button"
					onclick={closeOperationModal}
					aria-label="Fechar detalhes da operação"
					class="rounded-lg p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"
				>
					<X class="h-4 w-4" aria-hidden="true" />
				</button>
			</div>

			<dl class="mt-4 grid grid-cols-1 gap-2.5 text-xs sm:grid-cols-2">
				<div class="rounded-lg bg-slate-50 p-2.5 sm:col-span-2">
					<dt class="text-[11px] text-slate-500">ID da Operação</dt>
					<dd class="mt-0.5">
						<CopyableId
							id={selected.operation.operationId}
							idClass="font-mono text-xs font-medium text-slate-900"
						/>
					</dd>
				</div>
				<div class="rounded-lg bg-slate-50 p-2.5 sm:col-span-2">
					<dt class="text-[11px] text-slate-500">ID do Recurso</dt>
					<dd class="mt-0.5">
						<CopyableId
							id={selected.operation.resourceId}
							idClass="font-mono text-xs font-medium text-slate-900"
						/>
					</dd>
				</div>
				<div class="rounded-lg bg-slate-50 p-2.5">
					<dt class="text-[11px] text-slate-500">Recurso</dt>
					<dd class="mt-0.5 font-medium text-slate-900">
						{formatResourceType(selected.operation.resourceType)}
					</dd>
				</div>
				<div class="rounded-lg bg-slate-50 p-2.5">
					<dt class="text-[11px] text-slate-500">Ação</dt>
					<dd class="mt-0.5 font-medium text-slate-900">
						{formatOperationAction(selected.operation.operationType)}
					</dd>
				</div>
				<div class="rounded-lg bg-slate-50 p-2.5">
					<dt class="text-[11px] text-slate-500">Status</dt>
					<dd class="mt-1">
						<StatusBadge operationStatus={selected.operation.operationStatus} size="sm" />
					</dd>
				</div>
				<div class="rounded-lg bg-slate-50 p-2.5">
					<dt class="text-[11px] text-slate-500">Atualizado em</dt>
					<dd class="mt-0.5 font-mono text-slate-800">{selected.operation.updatedAt}</dd>
				</div>
			</dl>

			{#if selected.operation.operationStatusReason}
				<div class="mt-3 rounded-xl border border-amber-200 bg-amber-50 p-3 text-xs text-amber-900">
					<p class="font-semibold">Motivo da Rejeição:</p>
					<p class="mt-0.5 text-[11px]">
						{formatReasonLabel(selected.operation.operationStatusReason)}
					</p>
				</div>
			{/if}

			<p class="mt-3 text-xs text-slate-600">{selected.subtitle}</p>

			<div class="mt-4 flex justify-end border-t border-slate-100 pt-3">
				<button
					type="button"
					onclick={closeOperationModal}
					class="rounded-lg bg-slate-900 px-3.5 py-1.5 text-xs font-semibold text-white hover:bg-slate-800"
				>
					Fechar
				</button>
			</div>
		</div>
	</div>
{/if}
