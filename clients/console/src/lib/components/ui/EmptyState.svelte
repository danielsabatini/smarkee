<script lang="ts">
	import type { Snippet } from 'svelte';
	import { Inbox } from 'lucide-svelte';

	interface Props {
		title: string;
		description: string;
		action?: Snippet;
	}

	let { title, description, action }: Props = $props();
</script>

<div
	class="flex flex-col items-center justify-center rounded-xl border border-dashed border-slate-300 bg-slate-50/70 px-6 py-10 text-center"
>
	<div
		class="mb-3 flex h-11 w-11 items-center justify-center rounded-full bg-brand-50 text-brand-700"
	>
		<Inbox class="h-5 w-5" aria-hidden="true" />
	</div>
	<h3 class="text-sm font-semibold text-slate-900">{title}</h3>
	<p class="mt-1 max-w-md text-xs text-slate-600">{description}</p>
	{#if action}
		<div class="mt-4">
			{@render action()}
		</div>
	{/if}
</div>
