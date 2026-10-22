<script lang="ts">
	import {
		Activity,
		BarChart3,
		Bell,
		Building2,
		ChevronDown,
		ChevronRight,
		FileText,
		Home,
		LayoutGrid,
		ListFilter,
		PanelLeftClose,
		PanelLeftOpen,
		Settings,
		ShieldCheck,
		UserCheck,
		Users,
		X
	} from 'lucide-svelte';
	import { page } from '$app/state';
	import DemoBadge from '$lib/components/ui/DemoBadge.svelte';
	import { NAVIGATION_SECTIONS, type NavItem } from '$lib/config/navigation';
	import { getConsoleState } from '$lib/state/console-context.svelte';

	const consoleState = getConsoleState();

	let collapsedSections = $state<Record<string, boolean>>({});

	function toggleSection(sectionId: string): void {
		collapsedSections[sectionId] = !collapsedSections[sectionId];
	}

	function isActiveRoute(href: string, pathname: string): boolean {
		if (href === '/') {
			return pathname === '/';
		}
		return pathname === href || pathname.startsWith(`${href}/`);
	}

	function closeMobileIfOpen(): void {
		if (consoleState.isMobileDrawerOpen) {
			consoleState.setMobileDrawerOpen(false);
		}
	}

	function handleWindowKeydown(event: KeyboardEvent): void {
		if (event.key === 'Escape' && consoleState.isMobileDrawerOpen) {
			consoleState.setMobileDrawerOpen(false);
		}
	}
</script>

<svelte:window onkeydown={handleWindowKeydown} />

{#snippet navIcon(iconName: NavItem['iconName'], isCurrent: boolean)}
	{@const iconClass = `h-4 w-4 shrink-0 ${isCurrent ? 'text-emerald-700' : 'text-slate-500'}`}
	{#if iconName === 'home'}
		<Home class={iconClass} aria-hidden="true" />
	{:else if iconName === 'user-check'}
		<UserCheck class={iconClass} aria-hidden="true" />
	{:else if iconName === 'building-2'}
		<Building2 class={iconClass} aria-hidden="true" />
	{:else if iconName === 'users'}
		<Users class={iconClass} aria-hidden="true" />
	{:else if iconName === 'settings'}
		<Settings class={iconClass} aria-hidden="true" />
	{:else if iconName === 'layout-grid'}
		<LayoutGrid class={iconClass} aria-hidden="true" />
	{:else if iconName === 'shield-check'}
		<ShieldCheck class={iconClass} aria-hidden="true" />
	{:else if iconName === 'file-text'}
		<FileText class={iconClass} aria-hidden="true" />
	{:else if iconName === 'bar-chart-3'}
		<BarChart3 class={iconClass} aria-hidden="true" />
	{:else if iconName === 'list-filter'}
		<ListFilter class={iconClass} aria-hidden="true" />
	{:else if iconName === 'activity'}
		<Activity class={iconClass} aria-hidden="true" />
	{:else if iconName === 'bell'}
		<Bell class={iconClass} aria-hidden="true" />
	{:else}
		<LayoutGrid class={iconClass} aria-hidden="true" />
	{/if}
{/snippet}

{#snippet navigationContent(compact: boolean)}
	<div class="flex h-full flex-col justify-between">
		<div class="space-y-4 overflow-y-auto px-2.5 py-3">
			{#each NAVIGATION_SECTIONS as section (section.id)}
				{@const isCollapsed = Boolean(collapsedSections[section.id])}
				<div>
					{#if section.id !== 'home'}
						{#if !compact}
							<div class="mb-1 flex items-center justify-between px-2">
								{#if section.collapsible}
									<button
										type="button"
										onclick={() => toggleSection(section.id)}
										aria-expanded={!isCollapsed}
										title={section.title}
										data-testid="sidebar-section-toggle-{section.id}"
										class="flex w-full items-center justify-between py-1 text-left text-[11px] font-semibold tracking-normal text-slate-500 hover:text-slate-800"
									>
										<span class="flex items-center gap-1.5 truncate">
											<span>{section.shortTitle ?? section.title}</span>
											{#if section.isDemo}
												<DemoBadge label="Preview" />
											{/if}
										</span>
										{#if isCollapsed}
											<ChevronRight class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
										{:else}
											<ChevronDown class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
										{/if}
									</button>
								{:else}
									<span
										title={section.title}
										class="text-[11px] font-semibold tracking-normal text-slate-500"
									>
										{section.shortTitle ?? section.title}
									</span>
								{/if}
							</div>
						{:else}
							<div class="my-2 border-t border-slate-200/80" aria-hidden="true"></div>
						{/if}
					{/if}

					{#if !isCollapsed || compact}
						<ul class="space-y-0.5">
							{#each section.items as item (item.id)}
								{@const isCurrent = isActiveRoute(item.href, page.url.pathname)}
								<li>
									<a
										href={item.href}
										onclick={closeMobileIfOpen}
										aria-current={isCurrent ? 'page' : undefined}
										title={compact ? `${item.label}${item.isDemo ? ' (Preview)' : ''}` : item.label}
										data-testid="nav-link-{item.id}"
										class="group flex items-center justify-between gap-1.5 rounded-lg px-2 py-2 text-xs font-medium transition {isCurrent
											? 'bg-emerald-50 font-semibold text-emerald-900 ring-1 ring-emerald-200/80'
											: 'text-slate-700 hover:bg-slate-100 hover:text-slate-900'} {compact
											? 'justify-center px-2'
											: ''}"
									>
										<span class="flex min-w-0 items-center gap-2">
											{@render navIcon(item.iconName, isCurrent)}
											{#if !compact}
												<span class="truncate">{item.label}</span>
											{/if}
										</span>

										{#if !compact}
											<span class="flex shrink-0 items-center gap-1">
												{#if item.isDemo && !section.isDemo}
													<span
														class="rounded bg-amber-50 px-1 py-0.5 text-[9px] font-medium text-amber-800 ring-1 ring-amber-200"
													>
														Preview
													</span>
												{/if}
												{#if item.href !== '/'}
													<ChevronRight
														class="h-3 w-3 text-slate-400 transition group-hover:translate-x-0.5 group-hover:text-slate-600"
														aria-hidden="true"
													/>
												{/if}
											</span>
										{/if}
									</a>
								</li>
							{/each}
						</ul>
					{/if}
				</div>
			{/each}
		</div>

		<!-- Rodapé do menu lateral com controle de modo compacto -->
		<div class="border-t border-slate-200 bg-slate-50/60 p-2.5">
			<button
				type="button"
				onclick={() => consoleState.toggleSidebarCompact()}
				aria-label={compact
					? 'Expandir menu de navegação lateral'
					: 'Recolher menu para modo compacto com ícones'}
				data-testid="sidebar-compact-toggle"
				class="hidden w-full items-center justify-center gap-2 rounded-lg border border-slate-200 bg-white px-2.5 py-1.5 text-xs font-medium text-slate-700 transition hover:border-emerald-300 hover:text-emerald-800 lg:flex"
			>
				{#if compact}
					<PanelLeftOpen class="h-4 w-4 shrink-0 text-emerald-700" aria-hidden="true" />
				{:else}
					<PanelLeftClose class="h-4 w-4 shrink-0 text-slate-500" aria-hidden="true" />
					<span>Modo compacto</span>
				{/if}
			</button>
		</div>
	</div>
{/snippet}

<!-- Navegação Desktop -->
<aside
	aria-label="Menu principal de módulos da plataforma"
	data-testid="desktop-sidebar"
	data-compact={consoleState.isSidebarCompact ? 'true' : 'false'}
	class="hidden shrink-0 border-r border-slate-200 bg-white transition-all duration-200 lg:block {consoleState.isSidebarCompact
		? 'w-16'
		: 'w-60'}"
>
	{@render navigationContent(consoleState.isSidebarCompact)}
</aside>

<!-- Drawer Mobile -->
{#if consoleState.isMobileDrawerOpen}
	<div
		class="fixed inset-0 z-50 flex lg:hidden"
		role="dialog"
		aria-modal="true"
		aria-label="Menu de navegação móvel"
		data-testid="mobile-sidebar-drawer"
	>
		<div
			class="fixed inset-0 bg-slate-900/40 backdrop-blur-[1px]"
			aria-hidden="true"
			onclick={() => consoleState.setMobileDrawerOpen(false)}
		></div>

		<div class="relative z-10 flex w-72 max-w-[85vw] flex-col bg-white shadow-2xl">
			<div class="flex h-14 items-center justify-between border-b border-slate-200 px-4">
				<div class="flex items-center gap-2">
					<img src="/brand/s-small.png" alt="Smarkee" class="h-6 w-6" width="24" height="24" />
					<span class="text-sm font-bold text-slate-900">Smarkee Console</span>
				</div>
				<button
					type="button"
					onclick={() => consoleState.setMobileDrawerOpen(false)}
					aria-label="Fechar menu de navegação"
					data-testid="mobile-drawer-close"
					class="rounded-lg p-1.5 text-slate-500 hover:bg-slate-100 hover:text-slate-900"
				>
					<X class="h-4 w-4" aria-hidden="true" />
				</button>
			</div>

			<div class="flex-1 overflow-y-auto">
				{@render navigationContent(false)}
			</div>
		</div>
	</div>
{/if}
