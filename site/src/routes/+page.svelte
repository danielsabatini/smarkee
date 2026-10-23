<script lang="ts">
	import Hero from '$lib/components/Hero.svelte';
	import ModuleCards from '$lib/components/ModuleCards.svelte';
	import CodeSnippetTab from '$lib/components/CodeSnippetTab.svelte';
	import BlogPreview from '$lib/components/BlogPreview.svelte';
	import CtaSection from '$lib/components/CtaSection.svelte';
</script>

<svelte:head>
	<title>Smarkee IT Solutions — Plataforma de Hospedagem e Gestão</title>
	<meta
		name="description"
		content="Smarkee IT Solutions: Hospedagem, gestão de acessos, infraestrutura e observabilidade integrados para alavancar seu produto."
	/>
</svelte:head>

<Hero />
<ModuleCards />
<CodeSnippetTab />
<BlogPreview />
<CtaSection />
