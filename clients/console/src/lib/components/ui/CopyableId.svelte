<script lang="ts">
	import { Check, Copy } from 'lucide-svelte';

	interface Props {
		id: string;
		label?: string;
		class?: string;
		idClass?: string;
		testId?: string;
		idTestId?: string;
		ariaLabel?: string;
	}

	let {
		id,
		label,
		class: className = '',
		idClass = 'font-mono text-[11px] text-slate-600',
		testId,
		idTestId,
		ariaLabel
	}: Props = $props();

	let copied = $state(false);
	let resetTimer: ReturnType<typeof setTimeout> | null = null;

	async function copyId(): Promise<void> {
		if (!id) {
			return;
		}
		try {
			if (typeof navigator !== 'undefined' && navigator.clipboard) {
				await navigator.clipboard.writeText(id);
			}
			copied = true;
			if (resetTimer) {
				clearTimeout(resetTimer);
			}
			resetTimer = setTimeout(() => {
				copied = false;
			}, 1800);
		} catch {
			copied = false;
		}
	}
</script>

<div class="inline-flex items-center gap-1.5 {className}">
	{#if label}
		<span class="text-[11px] font-medium text-slate-500">{label}</span>
	{/if}
	<span data-testid={idTestId} class="{idClass} select-all break-all">
		{id}
	</span>
	<button
		type="button"
		onclick={copyId}
		aria-label={copied ? 'Identificador copiado' : (ariaLabel ?? `Copiar identificador ${id}`)}
		title={copied ? 'Copiado!' : 'Copiar identificador'}
		data-testid={testId}
		class="shrink-0 rounded p-1 text-slate-400 transition hover:bg-emerald-100 hover:text-emerald-800 focus:outline-hidden"
	>
		{#if copied}
			<Check class="h-3 w-3 text-emerald-700" aria-hidden="true" />
		{:else}
			<Copy class="h-3 w-3" aria-hidden="true" />
		{/if}
	</button>
</div>
