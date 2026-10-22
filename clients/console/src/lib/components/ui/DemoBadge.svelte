<script lang="ts">
	import { Sparkles } from 'lucide-svelte';

	interface Props {
		label?: string;
		title?: string;
		variant?: 'default' | 'icon';
	}

	let {
		label = 'Demonstrativo',
		title = 'Módulo ou metadado demonstrativo (Preview) — ainda não conectado ao backend de produção',
		variant = 'default'
	}: Props = $props();
</script>

{#if variant === 'icon'}
	<span
		class="group flex shrink-0 items-center justify-center overflow-hidden rounded-full border border-transparent text-amber-400 transition-all duration-300 hover:border-amber-200 hover:bg-amber-50 hover:px-1.5 hover:py-0.5 hover:text-amber-700"
		{title}
	>
		<Sparkles class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
		<span
			class="max-w-0 overflow-hidden whitespace-nowrap text-[10px] font-medium leading-none transition-all duration-300 group-hover:ml-1 group-hover:max-w-[80px]"
		>
			{label}
		</span>
	</span>
{:else}
	<span
		class="inline-flex shrink-0 items-center gap-0.5 rounded border border-amber-200 bg-amber-50 px-1 py-0.5 text-[10px] font-medium leading-none text-amber-800"
		{title}
	>
		<Sparkles class="h-2.5 w-2.5 shrink-0 text-amber-600" aria-hidden="true" />
		<span>{label}</span>
	</span>
{/if}
