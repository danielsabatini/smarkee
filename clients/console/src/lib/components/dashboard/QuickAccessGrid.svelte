<script lang="ts">
	import { Building2, ChevronRight, FileText, LayoutGrid, ShieldCheck, Users } from 'lucide-svelte';
	import DemoBadge from '$lib/components/ui/DemoBadge.svelte';

	interface QuickAccessItem {
		id: string;
		title: string;
		description: string;
		href: string;
		icon: 'users' | 'building' | 'catalog' | 'enabled' | 'audit';
		isDemo?: boolean;
	}

	const items: QuickAccessItem[] = [
		{
			id: 'users',
			title: 'Usuários',
			description: 'Gerencie usuários e acessos na organização',
			href: '/identity/users',
			icon: 'users'
		},
		{
			id: 'organizations',
			title: 'Organizações',
			description: 'Visualize e gerencie organizações',
			href: '/identity/organizations',
			icon: 'building'
		},
		{
			id: 'catalog',
			title: 'Catálogo de Serviços',
			description: 'Explore os serviços da plataforma',
			href: '/services/catalog',
			icon: 'catalog'
		},
		{
			id: 'enabled',
			title: 'Serviços Habilitados',
			description: 'Gerencie o uso de serviços',
			href: '/services/enabled',
			icon: 'enabled'
		},
		{
			id: 'audit',
			title: 'Eventos de Auditoria',
			description: 'Consulte o histórico de operações',
			href: '/audit/events',
			icon: 'audit',
			isDemo: true
		}
	];
</script>

<section aria-labelledby="quick-access-heading">
	<div class="mb-3">
		<h2 id="quick-access-heading" class="text-base font-bold text-slate-900">Acessos rápidos</h2>
		<p class="text-xs text-slate-600">Acesse os módulos mais utilizados da plataforma.</p>
	</div>

	<div class="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-5">
		{#each items as item (item.id)}
			<a
				href={item.href}
				data-testid="quick-access-{item.id}"
				class="group relative flex items-start gap-2.5 rounded-xl border border-slate-200 bg-white p-3 shadow-2xs transition hover:border-emerald-300 hover:shadow-sm"
			>
				{#if item.isDemo}
					<div class="absolute top-2 right-2.5">
						<DemoBadge label="Preview" />
					</div>
				{/if}

				<div
					class="flex h-8 w-8 shrink-0 items-center justify-center rounded-xl bg-emerald-50 text-emerald-700 transition group-hover:bg-emerald-100"
				>
					{#if item.icon === 'users'}
						<Users class="h-4 w-4" aria-hidden="true" />
					{:else if item.icon === 'building'}
						<Building2 class="h-4 w-4" aria-hidden="true" />
					{:else if item.icon === 'catalog'}
						<LayoutGrid class="h-4 w-4" aria-hidden="true" />
					{:else if item.icon === 'enabled'}
						<ShieldCheck class="h-4 w-4" aria-hidden="true" />
					{:else}
						<FileText class="h-4 w-4" aria-hidden="true" />
					{/if}
				</div>

				<div class="min-w-0 flex-1 {item.isDemo ? 'pt-5' : ''}">
					<div class="flex items-center justify-between gap-0.5">
						<span class="whitespace-nowrap text-[11px] font-bold tracking-tight text-slate-900">
							{item.title}
						</span>
						<ChevronRight
							class="h-3 w-3 shrink-0 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-emerald-700"
							aria-hidden="true"
						/>
					</div>
					<p class="mt-0.5 line-clamp-2 text-[11px] leading-snug text-slate-500">
						{item.description}
					</p>
				</div>
			</a>
		{/each}
	</div>
</section>
