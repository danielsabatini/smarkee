<script lang="ts">
	import { ArrowUpRight, MessageSquare, ShieldCheck } from 'lucide-svelte';
</script>

<section
	class="relative overflow-hidden border-t border-slate-900 bg-gradient-to-b from-slate-950 to-slate-900 py-20 sm:py-28"
>
	<div class="pointer-events-none absolute inset-0 -z-10 glow-emerald-subtle opacity-50"></div>

	<div class="mx-auto max-w-5xl px-4 text-center sm:px-6 lg:px-8">
		<div
			class="inline-flex items-center gap-1.5 rounded-full border border-emerald-500/30 bg-emerald-950/60 px-3.5 py-1 text-xs text-emerald-300"
		>
			<ShieldCheck class="h-3.5 w-3.5" aria-hidden="true" />
			<span>Engenharia Confiável • Sem Lock-in</span>
		</div>

		<h2 class="mt-4 text-3xl font-extrabold tracking-tight text-white sm:text-5xl">
			Pronto para Modernizar Sua Nuvem com Controle Declarativo?
		</h2>

		<p class="mx-auto mt-4 max-w-2xl text-sm leading-relaxed text-slate-300 sm:text-base">
			Elimine estados inconsistentes, padronize identidades com menor privilégio e proporcione uma
			Internal Developer Platform (IDP) de classe mundial para suas equipes de engenharia.
		</p>

		<div class="mt-8 flex flex-wrap items-center justify-center gap-3">
			<a
				href="http://localhost:5173"
				target="_blank"
				rel="noreferrer"
				class="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-6 py-3 text-sm font-semibold text-white shadow-xl shadow-emerald-950/60 transition hover:bg-emerald-500 hover:shadow-emerald-900/80"
			>
				<span>Acessar o Smarkee Console</span>
				<ArrowUpRight class="h-4 w-4" aria-hidden="true" />
			</a>

			<a
				href="/contato"
				class="inline-flex items-center gap-2 rounded-xl border border-slate-700 bg-slate-900 px-6 py-3 text-sm font-semibold text-slate-200 transition hover:border-slate-600 hover:bg-slate-800"
			>
				<MessageSquare class="h-4 w-4 text-emerald-400" aria-hidden="true" />
				<span>Agendar Demonstração</span>
			</a>
		</div>
	</div>
</section>
