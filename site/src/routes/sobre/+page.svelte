<script lang="ts">
	import { PILLARS } from '$lib/data/platform';
</script>

<svelte:head>
	<title>Sobre a Smarkee IT Solutions — Engenharia de Nuvem Moderna</title>
	<meta
		name="description"
		content="Conheça a visão, arquitetura e princípios de engenharia da Smarkee IT Solutions: segurança em primeiro lugar, simplicidade radical, robustez e resiliência."
	/>
</svelte:head>

<div class="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
	<!-- Hero da Seção Sobre -->
	<div class="mx-auto max-w-3xl text-center">
		<span class="text-xs font-semibold uppercase tracking-wider text-emerald-400">
			Nossa Missão
		</span>
		<h1 class="mt-2 text-3xl font-extrabold tracking-tight text-white sm:text-5xl">
			Engenharia de Nuvem Sem Fórmulas Mágicas
		</h1>
		<p class="mt-4 text-sm leading-relaxed text-slate-400 sm:text-base">
			Acreditamos que plataformas confiáveis nascem da simplicidade, da resiliência perante falhas e
			do respeito aos padrões abertos consagrados pela indústria.
		</p>
	</div>

	<!-- Conteúdo Institucional -->
	<div class="mt-16 grid grid-cols-1 gap-12 lg:grid-cols-2">
		<div class="space-y-6 text-sm text-slate-300 leading-relaxed">
			<h2 class="text-xl font-bold text-white">Por Que Criamos a Smarkee?</h2>
			<p>
				Ao longo dos anos, a computação em nuvem tornou-se excessivamente complexa. Pequenas
				alterações exigem dezenas de passos manuais, chamadas síncronas frágeis deixam recursos em
				estados órfãos, e ferramentas proprietárias prendem empresas a ecossistemas fechados.
			</p>
			<p>
				A **Smarkee IT Solutions** foi concebida com um princípio simples: **o que é declarado como
				intenção deve ser continuamente reconciliado com a realidade**. Sem caixas pretas, sem
				atalhos que comprometem a segurança e com total transparência de estado.
			</p>
		</div>

		<div class="rounded-2xl border border-slate-800 bg-slate-900/40 p-8 backdrop-blur-md">
			<h3 class="text-lg font-bold text-white">Nossos Pilares Fundamentais</h3>
			<p class="mt-1 text-xs text-slate-400">
				Diretrizes inegociáveis presentes em cada linha de código da plataforma:
			</p>

			<div class="mt-6 space-y-4">
				{#each PILLARS as pillar, idx (pillar.title)}
					<div class="flex items-start gap-3">
						<div
							class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-950 border border-emerald-800 text-emerald-400 font-mono text-xs font-bold"
						>
							{idx + 1}
						</div>
						<div>
							<h4 class="text-xs font-bold text-white">{pillar.title}</h4>
							<p class="mt-0.5 text-xs text-slate-400">{pillar.description}</p>
						</div>
					</div>
				{/each}
			</div>
		</div>
	</div>

	<!-- Chamada de Tecnologia Aberta -->
	<div
		class="mt-16 rounded-2xl border border-emerald-900/40 bg-slate-900/30 p-8 text-center sm:p-12"
	>
		<h3 class="text-xl font-bold text-white sm:text-2xl">Tecnologia Aberta, Moderna e Confiável</h3>
		<p class="mx-auto mt-3 max-w-2xl text-xs text-slate-400 sm:text-sm">
			Utilizamos NATS JetStream para mensageria assíncrona, PostgreSQL com JSONB para Single Source
			of Truth, OpenTelemetry para telemetria sem lock-in e Svelte 5 para interfaces de usuário
			ágeis e acessíveis.
		</p>
	</div>
</div>
