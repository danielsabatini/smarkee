<script lang="ts">
	import { ArrowRight, Clock, Search } from 'lucide-svelte';
	import { BLOG_POSTS } from '$lib/data/blog';

	let searchQuery = $state('');
	let selectedCategory = $state<string>('Todas');

	const categories = [
		'Todas',
		'Engenharia de Plataforma',
		'Segurança e Identidade',
		'Observabilidade',
		'Arquitetura'
	];

	const filteredPosts = $derived.by(() => {
		return BLOG_POSTS.filter((post) => {
			const matchesCategory = selectedCategory === 'Todas' || post.category === selectedCategory;
			const query = searchQuery.toLowerCase().trim();
			const matchesQuery =
				query === '' ||
				post.title.toLowerCase().includes(query) ||
				post.summary.toLowerCase().includes(query) ||
				post.tags.some((t) => t.toLowerCase().includes(query));
			return matchesCategory && matchesQuery;
		});
	});
</script>

<svelte:head>
	<title>Blog de Engenharia — Smarkee IT Solutions</title>
	<meta
		name="description"
		content="Artigos técnicos, decisões arquiteturais e melhores práticas sobre computação em nuvem declarativa, OIDC e observabilidade na Smarkee IT Solutions."
	/>
</svelte:head>

<div class="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
	<!-- Cabeçalho do Blog -->
	<div class="mx-auto max-w-3xl text-center">
		<span class="text-xs font-semibold uppercase tracking-wider text-emerald-700">
			Smarkee Engineering Blog
		</span>
		<h1 class="mt-2 text-3xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
			Artigos Técnicos & Visão de Nuvem
		</h1>
		<p class="mt-4 text-sm leading-relaxed text-slate-600 sm:text-base">
			Explorações profundas sobre engenharia de plataforma, sistemas distribuídos, modelo de
			reconciliação contínua e padrões abertos de telemetria.
		</p>
	</div>

	<!-- Barra de Pesquisa e Filtros -->
	<div
		class="mt-12 flex flex-col items-center justify-between gap-4 border-b border-slate-200 pb-8 sm:flex-row"
	>
		<!-- Filtros de Categoria -->
		<div class="flex flex-wrap items-center gap-1.5">
			{#each categories as category (category)}
				<button
					type="button"
					onclick={() => (selectedCategory = category)}
					class="rounded-xl px-3 py-1.5 text-xs font-semibold transition {selectedCategory ===
					category
						? 'bg-emerald-600 text-white shadow-2xs'
						: 'border border-slate-200 bg-white text-slate-700 hover:bg-slate-50 shadow-2xs'}"
				>
					{category}
				</button>
			{/each}
		</div>

		<!-- Campo de Busca -->
		<div class="relative w-full sm:w-72">
			<Search
				class="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-slate-400"
				aria-hidden="true"
			/>
			<input
				type="search"
				bind:value={searchQuery}
				placeholder="Buscar artigos ou tags..."
				class="w-full rounded-xl border border-slate-300 bg-white py-1.5 pr-3 pl-9 text-xs text-slate-900 placeholder:text-slate-400 focus:border-emerald-500 focus:outline-hidden shadow-2xs"
			/>
		</div>
	</div>

	<!-- Grade de Artigos -->
	{#if filteredPosts.length === 0}
		<div class="mt-16 text-center text-sm text-slate-500">
			Nenhum artigo encontrado para os filtros selecionados.
		</div>
	{:else}
		<div class="mt-12 grid grid-cols-1 gap-8 md:grid-cols-2 lg:grid-cols-3">
			{#each filteredPosts as post (post.slug)}
				<article
					class="flex flex-col justify-between rounded-2xl border border-slate-200 bg-white p-6 shadow-2xs transition hover:border-emerald-300 hover:shadow-md"
				>
					<div>
						<div class="flex items-center justify-between text-[11px] text-slate-500">
							<span
								class="rounded border border-emerald-200 bg-emerald-50 px-2.5 py-0.5 font-semibold text-emerald-800"
							>
								{post.category}
							</span>
							<div class="flex items-center gap-1">
								<Clock class="h-3 w-3 text-slate-400" aria-hidden="true" />
								<span>{post.readTimeMinutes} min</span>
							</div>
						</div>

						<h2 class="mt-4 text-lg font-bold text-slate-900 transition hover:text-emerald-700">
							<a href="/blog/{post.slug}">
								{post.title}
							</a>
						</h2>

						<p class="mt-2 text-xs leading-relaxed text-slate-600 line-clamp-3">
							{post.summary}
						</p>

						<!-- Tags -->
						<div class="mt-4 flex flex-wrap gap-1.5">
							{#each post.tags as tag (tag)}
								<span
									class="rounded border border-slate-200 bg-slate-50 px-2 py-0.5 font-mono text-[10px] text-slate-600"
								>
									#{tag}
								</span>
							{/each}
						</div>
					</div>

					<div
						class="mt-6 flex items-center justify-between border-t border-slate-100 pt-4 text-xs"
					>
						<div class="flex items-center gap-2">
							<img src={post.author.avatar} alt={post.author.name} class="h-6 w-6 rounded-full" />
							<div>
								<p class="text-[11px] font-semibold text-slate-800">{post.author.name}</p>
								<p class="text-[10px] text-slate-500">{post.date}</p>
							</div>
						</div>

						<a
							href="/blog/{post.slug}"
							class="inline-flex items-center gap-1 text-xs font-semibold text-emerald-700 hover:text-emerald-800"
						>
							<span>Ler</span>
							<ArrowRight class="h-3.5 w-3.5" aria-hidden="true" />
						</a>
					</div>
				</article>
			{/each}
		</div>
	{/if}
</div>
