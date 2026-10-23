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
		<span class="text-xs font-semibold uppercase tracking-wider text-emerald-700">
			Nossa Missão
		</span>
		<h1 class="mt-2 text-3xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
			Engenharia de Nuvem Sem Fórmulas Mágicas
		</h1>
		<p class="mt-4 text-sm leading-relaxed text-slate-600 sm:text-base">
			Acreditamos que plataformas confiáveis nascem da simplicidade, da resiliência perante falhas e
			do respeito aos padrões abertos consagrados pela indústria.
		</p>
	</div>

	<!-- Conteúdo Institucional -->
	<div class="mt-16 grid grid-cols-1 gap-12 lg:grid-cols-2">
		<div class="space-y-6 text-sm text-slate-700 leading-relaxed">
			<h2 class="text-xl font-bold text-slate-900">Por Que Criamos a Smarkee?</h2>
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

		<div class="rounded-2xl border border-slate-200 bg-white shadow-sm p-8">
			<h3 class="text-lg font-bold text-slate-900">Nossos Pilares Fundamentais</h3>
			<p class="mt-1 text-xs text-slate-600">
				Diretrizes inegociáveis presentes em cada linha de código da plataforma:
			</p>

			<div class="mt-6 space-y-4">
				{#each PILLARS as pillar, idx (pillar.title)}
					<div class="flex items-start gap-3">
						<div
							class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700 font-mono text-xs font-bold"
						>
							{idx + 1}
						</div>
						<div>
							<h4 class="text-xs font-bold text-slate-900">{pillar.title}</h4>
							<p class="mt-0.5 text-xs text-slate-600">{pillar.description}</p>
						</div>
					</div>
				{/each}
			</div>
		</div>
	</div>

	<!-- Chamada de Tecnologia Aberta -->
	<div class="mt-16 rounded-2xl border border-emerald-200 bg-slate-50 p-8 text-center sm:p-12">
		<h3 class="text-xl font-bold text-slate-900 sm:text-2xl">
			Tecnologia Aberta, Moderna e Confiável
		</h3>
		<p class="mx-auto mt-3 max-w-2xl text-xs text-slate-600 sm:text-sm">
			Utilizamos NATS JetStream para mensageria assíncrona, PostgreSQL com JSONB para Single Source
			of Truth, OpenTelemetry para telemetria sem lock-in e Svelte 5 para interfaces de usuário
			ágeis e acessíveis.
		</p>
	</div>
</div>
