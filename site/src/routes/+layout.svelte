<script lang="ts">
	import '../app.css';
	import Header from '$lib/components/Header.svelte';
	import Footer from '$lib/components/Footer.svelte';

	let { children } = $props();
</script>

<div class="flex min-h-screen flex-col bg-slate-50 text-slate-900">
	<Header />
	<main class="flex-1">
		{@render children()}
	</main>
	<Footer />
</div>
