<script lang="ts">
	import OrganizationSummary from '$lib/components/dashboard/OrganizationSummary.svelte';
	import RecentResources from '$lib/components/dashboard/RecentResources.svelte';
	import ServiceCards from '$lib/components/dashboard/ServiceCards.svelte';
	import ServiceStatusTable from '$lib/components/dashboard/ServiceStatusTable.svelte';
</script>

<svelte:head>
	<title>Smarkee Console — Dashboard</title>
</svelte:head>

<div class="mx-auto max-w-7xl space-y-6">
	<!-- Cabeçalho de boas-vindas -->
	<div>
		<h1 class="text-2xl font-bold tracking-tight text-slate-900 sm:text-3xl">
			Bem-vindo à Smarkee
		</h1>
		<p class="mt-1 text-sm text-slate-600">
			Gerencie suas organizações, serviços e recursos da plataforma.
		</p>
	</div>

	<!-- Card de Resumo da Organization Ativa -->
	<OrganizationSummary />

	<!-- Cards dos Serviços da Plataforma (IPM, SUM, AEM, ODM) -->
	<ServiceCards />

	<!-- Tabelas Inferiores: Recursos Recentes e Estado dos Serviços -->
	<div class="grid grid-cols-1 gap-5 xl:grid-cols-2">
		<RecentResources />
		<ServiceStatusTable />
	</div>
</div>
