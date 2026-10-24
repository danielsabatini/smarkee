<script lang="ts">
	import { AlertTriangle, CheckCircle2, Clock, Loader2, ShieldAlert, XCircle } from 'lucide-svelte';
	import type { OperationStatus, ResourcePhase } from '$lib/types/common';

	interface Props {
		phase?: ResourcePhase;
		operationStatus?: OperationStatus;
		customLabel?: string;
		variant?: 'ready' | 'progress' | 'warning' | 'failed' | 'neutral';
		size?: 'sm' | 'md';
	}

	let { phase, operationStatus, customLabel, variant, size = 'md' }: Props = $props();

	let resolvedInfo = $derived.by(() => {
		if (phase) {
			switch (phase) {
				case 'Ready':
					return { label: customLabel ?? 'Ready', tone: 'ready' as const };
				case 'Pending':
					return { label: customLabel ?? 'Pendente', tone: 'progress' as const };
				case 'Reconciling':
					return { label: customLabel ?? 'Reconciling', tone: 'progress' as const };
				case 'Deleting':
					return { label: customLabel ?? 'Excluindo', tone: 'progress' as const };
				case 'Degraded':
					return { label: customLabel ?? 'Degraded', tone: 'warning' as const };
				case 'Failed':
					return { label: customLabel ?? 'Failed', tone: 'failed' as const };
			}
		}

		if (operationStatus) {
			switch (operationStatus) {
				case 'completed':
					return { label: customLabel ?? 'Concluído', tone: 'ready' as const };
				case 'accepted':
					return { label: customLabel ?? 'Aceito', tone: 'progress' as const };
				case 'in_progress':
					return { label: customLabel ?? 'Em andamento', tone: 'progress' as const };
				case 'failed':
					return { label: customLabel ?? 'Falhou', tone: 'failed' as const };
				case 'rejected':
					return { label: customLabel ?? 'Rejeitado', tone: 'warning' as const };
			}
		}

		return {
			label: customLabel ?? 'Indefinido',
			tone: variant ?? ('neutral' as const)
		};
	});

	let badgeClasses = $derived.by(() => {
		const sizeClass = size === 'sm' ? 'px-2 py-0.5 text-xs' : 'px-2.5 py-1 text-xs';
		switch (resolvedInfo.tone) {
			case 'ready':
				return `${sizeClass} bg-status-ready-bg text-status-ready-text border-status-ready-text/20`;
			case 'progress':
				return `${sizeClass} bg-status-progress-bg text-status-progress-text border-status-progress-text/20`;
			case 'warning':
				return `${sizeClass} bg-status-warning-bg text-status-warning-text border-status-warning-text/20`;
			case 'failed':
				return `${sizeClass} bg-status-failed-bg text-status-failed-text border-status-failed-text/20`;
			default:
				return `${sizeClass} bg-slate-100 text-slate-700 border-slate-200`;
		}
	});
</script>

<span
	class="inline-flex items-center gap-1.5 rounded-full border font-medium whitespace-nowrap {badgeClasses}"
>
	{#if resolvedInfo.tone === 'ready'}
		<CheckCircle2 class="h-3.5 w-3.5 shrink-0 text-status-ready-text" aria-hidden="true" />
	{:else if resolvedInfo.tone === 'progress'}
		<Loader2
			class="h-3.5 w-3.5 shrink-0 animate-spin text-status-progress-text"
			aria-hidden="true"
		/>
	{:else if resolvedInfo.tone === 'warning'}
		{#if operationStatus === 'rejected'}
			<ShieldAlert class="h-3.5 w-3.5 shrink-0 text-status-warning-text" aria-hidden="true" />
		{:else}
			<AlertTriangle class="h-3.5 w-3.5 shrink-0 text-status-warning-text" aria-hidden="true" />
		{/if}
	{:else if resolvedInfo.tone === 'failed'}
		<XCircle class="h-3.5 w-3.5 shrink-0 text-status-failed-text" aria-hidden="true" />
	{:else}
		<Clock class="h-3.5 w-3.5 shrink-0 text-slate-500" aria-hidden="true" />
	{/if}
	<span>{resolvedInfo.label}</span>
</span>
