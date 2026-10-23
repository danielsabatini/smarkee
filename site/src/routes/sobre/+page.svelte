<script lang="ts">
	import { PILLARS } from '$lib/data/platform';
</script>

<svelte:head>
	<title>Sobre a Smarkee IT Solutions — Produtos Focados no seu Negócio</title>
	<meta
		name="description"
		content="Conheça a visão da Smarkee IT Solutions: foco na entrega de valor através de módulos de produtos integrados, seguros e fáceis de usar."
	/>
</svelte:head>

<div class="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
	<!-- Hero da Seção Sobre -->
	<div class="mx-auto max-w-3xl text-center">
		<span class="text-xs font-semibold uppercase tracking-wider text-emerald-700">
			Nossa Missão
		</span>
		<h1 class="mt-2 text-3xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
			Plataforma Focada na Operação
		</h1>
		<p class="mt-4 text-sm leading-relaxed text-slate-600 sm:text-base">
			Acreditamos que plataformas confiáveis nascem da simplicidade de uso. Nossos produtos garantem
			que a sua equipe invista tempo construindo soluções, e não gerenciando complexidade.
		</p>
	</div>

	<!-- Conteúdo Institucional -->
	<div class="mt-16 grid grid-cols-1 gap-12 lg:grid-cols-2">
		<div class="space-y-6 text-sm text-slate-700 leading-relaxed">
			<h2 class="text-xl font-bold text-slate-900">Por Que Criamos a Smarkee?</h2>
			<p>
				Ao longo dos anos, a gestão de acesso e serviços tornou-se excessivamente complexa. Pequenas
				alterações exigem dezenas de passos manuais e ferramentas proprietárias prendem empresas a
				ecossistemas fechados.
			</p>
			<p>
				A <strong>Smarkee IT Solutions</strong> foi concebida com um princípio simples:
				<strong
					>entregar produtos prontos para produção que resolvem dores reais de segurança e operação</strong
				>. Queremos que cada módulo sirva como uma fundação sólida para o crescimento do seu
				negócio, de maneira integrada e intuitiva.
			</p>
		</div>

		<div class="rounded-2xl border border-slate-200 bg-white shadow-sm p-8">
			<h3 class="text-lg font-bold text-slate-900">Nossos Pilares Fundamentais</h3>
			<p class="mt-1 text-xs text-slate-600">
				Diretrizes inegociáveis presentes em cada produto da plataforma:
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
		<h3 class="text-xl font-bold text-slate-900 sm:text-2xl">Um Ecossistema Integrado</h3>
		<p class="mx-auto mt-3 max-w-2xl text-xs text-slate-600 sm:text-sm">
			Com os módulos IPM, SUM, AEM e ODM, você tem uma suíte completa para identidade, gestão de
			serviços, auditoria e observabilidade — tudo operando de forma conjunta para impulsionar seus
			resultados.
		</p>
	</div>
</div>
