<script lang="ts">
	import { ArrowRight } from 'lucide-svelte';
</script>

<div
	class="relative overflow-hidden bg-slate-50 pt-16 pb-24 sm:pt-24 sm:pb-32 border-b border-slate-200"
>
	<!-- Decoration -->
	<div class="absolute inset-x-0 top-0 h-96 bg-linear-to-b from-slate-100 to-transparent"></div>

	<div class="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
		<div class="mx-auto max-w-4xl text-center">
			<h1 class="text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl lg:text-6xl">
				Acelere o seu negócio com
				<span class="block mt-2 text-emerald-700">nossa plataforma em nuvem.</span>
			</h1>
			<p class="mx-auto mt-6 max-w-2xl text-lg leading-relaxed text-slate-600 sm:text-xl">
				Uma plataforma modular que integra identidade, catálogo de serviços sob demanda, auditoria e
				observabilidade. Governança e autonomia para acelerar o desenvolvimento do seu produto.
			</p>

			<div class="mt-10 flex items-center justify-center">
				<a
					href="#plataforma"
					class="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-8 py-3.5 text-sm font-bold text-white shadow-sm shadow-emerald-700/20 transition hover:bg-emerald-700 hover:shadow-md"
				>
					<span>Explorar Plataforma</span>
					<ArrowRight class="h-4 w-4" aria-hidden="true" />
				</a>
			</div>
		</div>

		<!-- Preview Visual da Plataforma (Console Smarkee) -->
		<div class="mt-14 sm:mt-20">
			<div
				class="mx-auto max-w-6xl overflow-hidden rounded-2xl border border-slate-200/90 bg-white shadow-xl shadow-slate-900/5"
			>
				<!-- Moldura sutil do navegador -->
				<div
					class="flex items-center justify-between border-b border-slate-200 bg-slate-50/90 px-4 py-2.5"
				>
					<div class="flex items-center gap-2" aria-hidden="true">
						<div class="h-2.5 w-2.5 rounded-full bg-slate-300"></div>
						<div class="h-2.5 w-2.5 rounded-full bg-slate-300"></div>
						<div class="h-2.5 w-2.5 rounded-full bg-slate-300"></div>
					</div>
					<div
						class="flex items-center gap-2 rounded-md border border-slate-200/80 bg-white px-3 py-1 font-mono text-xs text-slate-500"
					>
						<span class="h-1.5 w-1.5 rounded-full bg-emerald-500" aria-hidden="true"></span>
						<span>console.smarkee.com.br</span>
					</div>
					<div class="w-12" aria-hidden="true"></div>
				</div>

				<!-- Imagem real do Smarkee Console -->
				<img
					src="/brand/console-main-layout.png"
					alt="Painel principal do Smarkee Console exibindo a visão unificada da organização, catálogo de serviços sob demanda, gestão de identidade, auditoria e observabilidade."
					class="block w-full h-auto"
					loading="eager"
				/>
			</div>
		</div>
	</div>
</div>
