<script lang="ts">
	import { Sparkles } from 'lucide-svelte';

	interface Props {
		label?: string;
		title?: string;
	}

	let {
		label = 'Demonstrativo',
		title = 'Módulo ou metadado demonstrativo (Preview) — ainda não conectado ao backend de produção'
	}: Props = $props();
</script>

<span
	class="inline-flex shrink-0 items-center gap-0.5 rounded border border-amber-200 bg-amber-50 px-1 py-0.5 text-[10px] leading-none font-medium text-amber-800"
	{title}
>
	<Sparkles class="h-2.5 w-2.5 shrink-0 text-amber-600" aria-hidden="true" />
	<span>{label}</span>
</span>
