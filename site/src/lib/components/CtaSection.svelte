<script lang="ts">
	import { ArrowUpRight } from 'lucide-svelte';
	import { CONSOLE_URL } from '$lib/data/platform';
</script>

<section class="relative overflow-hidden border-t border-slate-200 bg-white py-20 sm:py-28">
	<div class="mx-auto max-w-5xl px-4 text-center sm:px-6 lg:px-8">
		<h2 class="text-3xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
			Pronto para uma plataforma que joga a favor do seu negócio?
		</h2>

		<p class="mx-auto mt-4 max-w-2xl text-sm leading-relaxed text-slate-600 sm:text-base">
			Reduza seus custos e traga previsibilidade para a sua operação. Controle acessos, habilite
			serviços em segundos e tenha suporte integrado sem dores de cabeça.
		</p>

		<div class="mt-8 flex flex-wrap items-center justify-center gap-3">
			<a
				href={CONSOLE_URL}
				target="_blank"
				rel="noreferrer"
				class="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-6 py-3 text-sm font-semibold text-white shadow-sm shadow-emerald-700/20 transition hover:bg-emerald-700 hover:shadow-md"
			>
				<span>Acessar o Smarkee Console</span>
				<ArrowUpRight class="h-4 w-4" aria-hidden="true" />
			</a>
		</div>
	</div>
</section>
