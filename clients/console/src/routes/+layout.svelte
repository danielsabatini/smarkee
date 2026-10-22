<script lang="ts">
	import type { Snippet } from 'svelte';
	import { onDestroy, onMount } from 'svelte';
	import '../app.css';
	import AppHeader from '$lib/components/shell/AppHeader.svelte';
	import OperationsPanel from '$lib/components/shell/OperationsPanel.svelte';
	import Sidebar from '$lib/components/shell/Sidebar.svelte';
	import { MockDataAdapter } from '$lib/services/mock-adapter';
	import { ConsoleState, setConsoleState } from '$lib/state/console-context.svelte';

	interface Props {
		children: Snippet;
	}

	let { children }: Props = $props();

	const adapter = new MockDataAdapter({ transitionDelayMs: 900 });
	const consoleState = setConsoleState(new ConsoleState(adapter));

	onMount(() => {
		if (typeof window !== 'undefined' && window.innerWidth < 1024) {
			consoleState.closeOperationsPanel();
		}
		void consoleState.initialize();
	});

	onDestroy(() => {
		consoleState.dispose();
	});
</script>

<div class="flex min-h-screen flex-col bg-slate-50 text-slate-900">
	<AppHeader />

	<div class="flex flex-1 overflow-hidden">
		<Sidebar />

		<main
			id="main-content"
			data-testid="main-content"
			class="min-w-0 flex-1 overflow-y-auto px-4 py-5 sm:px-5 lg:px-6"
		>
			{#if consoleState.errorMessage}
				<div
					role="alert"
					class="mb-4 flex items-center justify-between rounded-xl border border-red-200 bg-red-50 px-4 py-3 text-xs text-red-900"
				>
					<span>{consoleState.errorMessage}</span>
					<button
						type="button"
						onclick={() => consoleState.initialize()}
						class="rounded-lg bg-red-700 px-3 py-1 font-semibold text-white hover:bg-red-800"
					>
						Tentar novamente
					</button>
				</div>
			{/if}

			{#key consoleState.activeOrganizationId}
				{@render children()}
			{/key}
		</main>

		<OperationsPanel />
	</div>
</div>
