<script lang="ts">
	import { page } from '$app/state';
	import { ArrowUpRight, Menu, X } from 'lucide-svelte';
	import { CONSOLE_URL, MAIN_NAV } from '$lib/data/platform';

	let isMobileMenuOpen = $state(false);

	function isNavActive(href: string, pathname: string): boolean {
		if (href.startsWith('/#')) {
			return false;
		}
		return pathname === href || pathname.startsWith(`${href}/`);
	}

	function toggleMobileMenu(): void {
		isMobileMenuOpen = !isMobileMenuOpen;
	}

	function closeMobileMenu(): void {
		isMobileMenuOpen = false;
	}
</script>

<header class="sticky top-0 z-50 border-b border-slate-200 bg-white/95 backdrop-blur-md">
	<div class="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
		<!-- Logotipo Oficial da Smarkee IT Solutions (Versão para fundo claro) -->
		<a
			href="/"
			class="flex items-center gap-2.5 transition hover:opacity-90"
			aria-label="Smarkee IT Solutions Início"
		>
			<img
				src="/brand/smarkee-itsolutions.png"
				alt="Smarkee IT Solutions"
				class="h-7 w-auto sm:h-8"
			/>
		</a>

		<!-- Navegação Desktop -->
		<nav class="hidden items-center gap-1 lg:flex" aria-label="Navegação Principal">
			{#each MAIN_NAV as item (item.href)}
				{@const active = isNavActive(item.href, page.url.pathname)}
				<a
					href={item.href}
					aria-current={active ? 'page' : undefined}
					class="rounded-lg px-3 py-1.5 text-sm font-semibold transition {active
						? 'bg-emerald-50 text-emerald-800'
						: 'text-slate-600 hover:bg-slate-100 hover:text-slate-900'}"
				>
					{item.label}
				</a>
			{/each}
		</nav>

		<!-- CTAs do Cabeçalho -->
		<div class="hidden items-center gap-2.5 sm:flex">
			<a
				href="/contato"
				class="rounded-xl border border-slate-200 bg-white px-3.5 py-1.5 text-sm font-semibold text-slate-700 shadow-2xs transition hover:border-slate-300 hover:bg-slate-50"
			>
				Falar com Especialistas
			</a>

			<a
				href={CONSOLE_URL}
				target="_blank"
				rel="noreferrer"
				class="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-1.5 text-sm font-semibold text-white shadow-2xs transition hover:bg-emerald-700"
			>
				<span>Console Smarkee</span>
				<ArrowUpRight class="h-3.5 w-3.5" aria-hidden="true" />
			</a>
		</div>

		<!-- Botão Hamburger Mobile -->
		<div class="flex items-center sm:hidden">
			<button
				type="button"
				onclick={toggleMobileMenu}
				aria-label={isMobileMenuOpen ? 'Fechar menu de navegação' : 'Abrir menu de navegação'}
				class="rounded-lg border border-slate-200 p-2 text-slate-600 hover:bg-slate-100 hover:text-slate-900"
			>
				{#if isMobileMenuOpen}
					<X class="h-5 w-5" aria-hidden="true" />
				{:else}
					<Menu class="h-5 w-5" aria-hidden="true" />
				{/if}
			</button>
		</div>
	</div>

	<!-- Menu Mobile Desdobrável -->
	{#if isMobileMenuOpen}
		<div class="border-b border-slate-200 bg-white px-4 py-5 sm:hidden shadow-lg">
			<nav class="flex flex-col gap-2" aria-label="Navegação Mobile">
				{#each MAIN_NAV as item (item.href)}
					{@const active = isNavActive(item.href, page.url.pathname)}
					<a
						href={item.href}
						aria-current={active ? 'page' : undefined}
						onclick={closeMobileMenu}
						class="rounded-lg px-3 py-2 text-sm font-medium {active
							? 'bg-emerald-50 text-emerald-800'
							: 'text-slate-700 hover:bg-slate-100 hover:text-slate-900'}"
					>
						{item.label}
					</a>
				{/each}
				<div class="mt-4 flex flex-col gap-2 pt-3 border-t border-slate-100">
					<a
						href="/contato"
						onclick={closeMobileMenu}
						class="rounded-xl border border-slate-200 bg-slate-50 px-3.5 py-2 text-center text-sm font-semibold text-slate-700"
					>
						Falar com Especialistas
					</a>
					<a
						href={CONSOLE_URL}
						target="_blank"
						rel="noreferrer"
						onclick={closeMobileMenu}
						class="inline-flex items-center justify-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-sm font-semibold text-white"
					>
						<span>Console Smarkee</span>
						<ArrowUpRight class="h-3.5 w-3.5" aria-hidden="true" />
					</a>
				</div>
			</nav>
		</div>
	{/if}
</header>
