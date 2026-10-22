<script lang="ts">
	import { ArrowRight, Clock } from 'lucide-svelte';
	import { BLOG_POSTS } from '$lib/data/blog';
</script>

<section id="blog-preview" class="border-t border-slate-900 bg-slate-950 py-20 sm:py-28">
	<div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
		<div class="flex flex-col items-start justify-between gap-4 sm:flex-row sm:items-end">
			<div>
				<span class="text-xs font-semibold uppercase tracking-wider text-emerald-400">
					Conhecimento Técnico & Engenharia
				</span>
				<h2 class="mt-2 text-2xl font-bold tracking-tight text-white sm:text-4xl">
					Blog da Smarkee IT Solutions
				</h2>
				<p class="mt-2 max-w-2xl text-xs text-slate-400 sm:text-sm">
					Artigos aprofundados sobre arquitetura distribuída, reconciliação declarativa, segurança
					multi-tenant e engenharia de plataforma.
				</p>
			</div>

			<a
				href="/blog"
				class="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-400 hover:text-emerald-300 transition"
			>
				<span>Ver todos os artigos</span>
				<ArrowRight class="h-4 w-4" aria-hidden="true" />
			</a>
		</div>

		<div class="mt-12 grid grid-cols-1 gap-6 md:grid-cols-3">
			{#each BLOG_POSTS as post (post.slug)}
				<article
					class="group flex flex-col justify-between rounded-2xl border border-slate-800 bg-slate-900/40 p-6 transition hover:border-emerald-500/40 hover:bg-slate-900/80"
				>
					<div>
						<div class="flex items-center justify-between text-[11px] text-slate-400">
							<span class="rounded bg-slate-800 px-2 py-0.5 font-medium text-emerald-300">
								{post.category}
							</span>
							<div class="flex items-center gap-1 text-slate-500">
								<Clock class="h-3 w-3" aria-hidden="true" />
								<span>{post.readTimeMinutes} min de leitura</span>
							</div>
						</div>

						<h3 class="mt-4 text-base font-bold text-white group-hover:text-emerald-300 transition">
							<a href="/blog/{post.slug}" class="focus:outline-hidden">
								{post.title}
							</a>
						</h3>

						<p class="mt-2 text-xs leading-relaxed text-slate-400 line-clamp-3">
							{post.summary}
						</p>
					</div>

					<div
						class="mt-6 flex items-center justify-between border-t border-slate-800/80 pt-4 text-xs"
					>
						<div class="flex items-center gap-2">
							<img src={post.author.avatar} alt={post.author.name} class="h-5 w-5 rounded-full" />
							<span class="text-[11px] text-slate-300">{post.author.name}</span>
						</div>

						<a
							href="/blog/{post.slug}"
							class="inline-flex items-center gap-1 text-[11px] font-semibold text-emerald-400 hover:text-emerald-300"
						>
							<span>Ler artigo</span>
							<ArrowRight
								class="h-3 w-3 transition group-hover:translate-x-0.5"
								aria-hidden="true"
							/>
						</a>
					</div>
				</article>
			{/each}
		</div>
	</div>
</section>
