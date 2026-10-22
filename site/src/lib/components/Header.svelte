<script lang="ts">
	import { ArrowUpRight, Menu, X } from 'lucide-svelte';
	import { MAIN_NAV } from '$lib/data/platform';

	let isMobileMenuOpen = $state(false);

	function toggleMobileMenu(): void {
		isMobileMenuOpen = !isMobileMenuOpen;
	}

	function closeMobileMenu(): void {
		isMobileMenuOpen = false;
	}
</script>

<header class="sticky top-0 z-50 border-b border-slate-800/80 bg-slate-950/80 backdrop-blur-lg">
	<div class="mx-auto flex h-16 max-w-7xl items-center justify-between px-4 sm:px-6 lg:px-8">
		<!-- Logotipo Oficial da Smarkee IT Solutions -->
		<a
			href="/"
			class="flex items-center gap-2.5 transition hover:opacity-90"
			aria-label="Smarkee IT Solutions Início"
		>
			<img
				src="/brand/smarkee-itsolutions-light.png"
				alt="Smarkee IT Solutions"
				class="h-7 w-auto sm:h-8"
			/>
		</a>

		<!-- Navegação Desktop -->
		<nav class="hidden items-center gap-1 lg:flex" aria-label="Navegação Principal">
			{#each MAIN_NAV as item (item.href)}
				<a
					href={item.href}
					class="rounded-lg px-3 py-1.5 text-xs font-medium text-slate-300 transition hover:bg-slate-900 hover:text-white"
				>
					{item.label}
				</a>
			{/each}
		</nav>

		<!-- CTAs do Cabeçalho -->
		<div class="hidden items-center gap-2.5 sm:flex">
			<a
				href="/contato"
				class="rounded-xl border border-slate-700 bg-slate-900/60 px-3.5 py-1.5 text-xs font-semibold text-slate-200 transition hover:border-slate-600 hover:bg-slate-800"
			>
				Falar com Engenharia
			</a>

			<a
				href="http://localhost:5173"
				target="_blank"
				rel="noreferrer"
				class="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-1.5 text-xs font-semibold text-white shadow-sm shadow-emerald-900/40 transition hover:bg-emerald-500 hover:shadow-emerald-900/60"
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
				class="rounded-lg border border-slate-800 p-2 text-slate-400 hover:bg-slate-900 hover:text-white"
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
		<div class="border-b border-slate-800 bg-slate-950 px-4 py-5 sm:hidden">
			<nav class="flex flex-col gap-2" aria-label="Navegação Mobile">
				{#each MAIN_NAV as item (item.href)}
					<a
						href={item.href}
						onclick={closeMobileMenu}
						class="rounded-lg px-3 py-2 text-sm font-medium text-slate-300 hover:bg-slate-900 hover:text-white"
					>
						{item.label}
					</a>
				{/each}
				<div class="mt-4 flex flex-col gap-2 pt-3 border-t border-slate-900">
					<a
						href="/contato"
						onclick={closeMobileMenu}
						class="rounded-xl border border-slate-700 bg-slate-900 px-3.5 py-2 text-center text-xs font-semibold text-slate-200"
					>
						Falar com Engenharia
					</a>
					<a
						href="http://localhost:5173"
						target="_blank"
						rel="noreferrer"
						onclick={closeMobileMenu}
						class="inline-flex items-center justify-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-2 text-xs font-semibold text-white"
					>
						<span>Console Smarkee</span>
						<ArrowUpRight class="h-3.5 w-3.5" aria-hidden="true" />
					</a>
				</div>
			</nav>
		</div>
	{/if}
</header>
