<script lang="ts">
	import { ArrowLeft, ArrowRight, Calendar, Clock, Share2 } from 'lucide-svelte';
	import type { PageData } from './$types';

	let { data }: { data: PageData } = $props();
	const { post, relatedPosts } = $derived(data);

	let copiedUrl = $state(false);

	async function shareArticle(): Promise<void> {
		if (typeof window !== 'undefined') {
			try {
				await navigator.clipboard.writeText(window.location.href);
				copiedUrl = true;
				setTimeout(() => {
					copiedUrl = false;
				}, 2000);
			} catch {
				copiedUrl = false;
			}
		}
	}
</script>

<svelte:head>
	<title>{post.title} — Blog Smarkee IT Solutions</title>
	<meta name="description" content={post.summary} />
</svelte:head>

<div class="mx-auto max-w-4xl px-4 py-12 sm:px-6 sm:py-16 lg:px-8">
	<!-- Link de Retorno -->
	<div>
		<a
			href="/blog"
			class="inline-flex items-center gap-1.5 text-xs font-semibold text-slate-600 hover:text-emerald-700 transition"
		>
			<ArrowLeft class="h-3.5 w-3.5" aria-hidden="true" />
			<span>Voltar para o blog</span>
		</a>
	</div>

	<!-- Cartão Central do Artigo -->
	<article class="mt-6 rounded-2xl border border-slate-200 bg-white p-6 sm:p-10 shadow-sm">
		<!-- Cabeçalho do Artigo -->
		<header class="border-b border-slate-100 pb-8">
			<div class="flex flex-wrap items-center gap-2">
				<span
					class="rounded-lg bg-emerald-50 border border-emerald-200 px-2.5 py-0.5 font-mono text-xs font-semibold text-emerald-800"
				>
					{post.category}
				</span>
				<span class="text-xs text-slate-400">•</span>
				<span class="inline-flex items-center gap-1 text-xs text-slate-500">
					<Clock class="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
					{post.readTimeMinutes} min de leitura
				</span>
				<span class="text-xs text-slate-400">•</span>
				<span class="inline-flex items-center gap-1 text-xs text-slate-500">
					<Calendar class="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
					{post.date}
				</span>
			</div>

			<h1
				class="mt-4 text-2xl font-extrabold tracking-tight text-slate-900 sm:text-4xl sm:leading-tight"
			>
				{post.title}
			</h1>

			<p class="mt-4 text-base leading-relaxed text-slate-600">
				{post.summary}
			</p>

			<!-- Autor e Compartilhar -->
			<div class="mt-8 flex items-center justify-between border-t border-slate-100 pt-6">
				<div class="flex items-center gap-3">
					<img
						src={post.author.avatar}
						alt={post.author.name}
						class="h-9 w-9 rounded-full bg-slate-100"
					/>
					<div>
						<p class="text-xs font-bold text-slate-900">{post.author.name}</p>
						<p class="text-[11px] text-slate-500">{post.author.role}</p>
					</div>
				</div>

				<button
					type="button"
					onclick={shareArticle}
					class="inline-flex items-center gap-1.5 rounded-xl border border-slate-200 bg-white px-3 py-1.5 text-xs font-semibold text-slate-700 shadow-2xs transition hover:bg-slate-50 hover:text-slate-900"
				>
					<Share2 class="h-3.5 w-3.5" aria-hidden="true" />
					<span>{copiedUrl ? 'Link Copiado!' : 'Compartilhar'}</span>
				</button>
			</div>
		</header>

		<!-- Conteúdo do Artigo -->
		<div class="mt-8 space-y-6 text-sm leading-relaxed text-slate-700">
			{#each post.content.trim().split('\n\n') as paragraph (paragraph)}
				{#if paragraph.startsWith('## ')}
					<h2
						class="mt-8 text-xl font-bold text-slate-900 tracking-tight border-b border-slate-100 pb-2"
					>
						{paragraph.replace('## ', '')}
					</h2>
				{:else if paragraph.startsWith('```')}
					<div
						class="my-4 overflow-x-auto rounded-xl border border-slate-800 bg-slate-900 p-4 font-mono text-xs text-emerald-300 shadow-inner"
					>
						<pre class="whitespace-pre"><code>{paragraph.replace(/```[a-z]*\n?/g, '')}</code></pre>
					</div>
				{:else if paragraph.startsWith('* ')}
					<ul class="my-3 space-y-1.5 pl-4 list-disc marker:text-emerald-600">
						{#each paragraph.split('\n') as bullet (bullet)}
							<li>{bullet.replace('* ', '')}</li>
						{/each}
					</ul>
				{:else if paragraph.startsWith('1. ')}
					<ol class="my-3 space-y-1.5 pl-4 list-decimal marker:text-emerald-600">
						{#each paragraph.split('\n') as item (item)}
							<li>{item.replace(/^[0-9]+\.\s/, '')}</li>
						{/each}
					</ol>
				{:else}
					<p class="text-slate-700 leading-relaxed">
						{paragraph}
					</p>
				{/if}
			{/each}
		</div>

		<!-- Tags do Artigo -->
		<div class="mt-12 flex flex-wrap items-center gap-2 border-t border-slate-100 pt-6">
			<span class="text-xs font-semibold text-slate-500">Tags:</span>
			{#each post.tags as tag (tag)}
				<span
					class="rounded-lg border border-slate-200 bg-slate-50 px-2.5 py-1 font-mono text-xs font-medium text-slate-700"
				>
					#{tag}
				</span>
			{/each}
		</div>
	</article>

	<!-- Artigos Relacionados -->
	{#if relatedPosts.length > 0}
		<div class="mt-12 pt-6">
			<h3 class="text-sm font-bold uppercase tracking-wider text-slate-500">
				Artigos Relacionados
			</h3>

			<div class="mt-6 grid grid-cols-1 gap-6 sm:grid-cols-2">
				{#each relatedPosts as related (related.slug)}
					<a
						href="/blog/{related.slug}"
						class="group flex flex-col justify-between rounded-xl border border-slate-200 bg-white p-5 shadow-2xs transition hover:border-emerald-300 hover:shadow-md"
					>
						<div>
							<span class="text-[10px] font-bold text-emerald-700 uppercase">
								{related.category}
							</span>
							<h4
								class="mt-2 text-sm font-bold text-slate-900 group-hover:text-emerald-700 transition"
							>
								{related.title}
							</h4>
							<p class="mt-1 text-xs text-slate-500 line-clamp-2">
								{related.summary}
							</p>
						</div>

						<div class="mt-4 flex items-center gap-1 text-[11px] font-semibold text-emerald-700">
							<span>Ler artigo</span>
							<ArrowRight class="h-3 w-3 transition group-hover:translate-x-1" aria-hidden="true" />
						</div>
					</a>
				{/each}
			</div>
		</div>
	{/if}
</div>
