<script lang="ts">
	import Hero from '$lib/components/Hero.svelte';
	import ModuleCards from '$lib/components/ModuleCards.svelte';
	import ControlLoopInteractive from '$lib/components/ControlLoopInteractive.svelte';
	import CodeSnippetTab from '$lib/components/CodeSnippetTab.svelte';
	import BlogPreview from '$lib/components/BlogPreview.svelte';
	import CtaSection from '$lib/components/CtaSection.svelte';
</script>

<svelte:head>
	<title>Smarkee IT Solutions — Plataforma de Nuvem Declarativa e Engenharia Moderna</title>
	<meta
		name="description"
		content="Smarkee IT Solutions: Plataforma de Nuvem Declarativa com controle de identidade multi-tenant (IPM), habilitação sob demanda (SUM), auditoria imutável (AEM) e observabilidade aberta (ODM)."
	/>
</svelte:head>

<Hero />
<ModuleCards />
<ControlLoopInteractive />
<CodeSnippetTab />
<BlogPreview />
<CtaSection />
