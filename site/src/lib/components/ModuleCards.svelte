<script lang="ts">
	import { ArrowRight, CheckCircle2 } from 'lucide-svelte';
	import { PLATFORM_MODULES } from '$lib/data/platform';
</script>

<section id="plataforma" class="relative border-t border-slate-200 bg-white py-20 sm:py-28">
	<div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
		<div class="mx-auto max-w-3xl text-center">
			<span class="text-sm font-semibold uppercase tracking-wider text-emerald-700">
				Suíte de Produtos Smarkee
			</span>
			<h2 class="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-4xl">
				Tudo o que você precisa, sem a complexidade
			</h2>
			<p class="mt-4 text-sm leading-relaxed text-slate-600 sm:text-base">
				Nossos módulos foram desenhados para resolver problemas reais de hospedagem e gestão,
				entregando máxima segurança sem exigir que você seja um especialista em DevOps.
			</p>
		</div>

		<div class="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
			{#each PLATFORM_MODULES as mod (mod.code)}
				<div
					class="group relative flex flex-col justify-between rounded-2xl border border-slate-200 bg-slate-50/60 p-6 shadow-2xs transition hover:border-emerald-400 hover:bg-white hover:shadow-md"
				>
					<div>
						<div class="flex items-center justify-between">
							<span class="font-mono text-sm font-bold text-emerald-700">{mod.code}</span>
							<span
								class="rounded-full px-2 py-0.5 font-mono text-sm font-semibold {mod.status === 'GA'
									? 'bg-emerald-50 text-emerald-800 border border-emerald-200'
									: 'bg-blue-50 text-blue-800 border border-blue-200'}"
							>
								{mod.status}
							</span>
						</div>

						<h3
							class="mt-3 text-base font-bold text-slate-900 group-hover:text-emerald-700 transition"
						>
							{mod.name}
						</h3>
						<p class="mt-1 text-sm text-slate-500">
							{mod.tagline}
						</p>

						<p class="mt-4 text-sm leading-relaxed text-slate-600">
							{mod.description}
						</p>

						<ul class="mt-5 space-y-2 border-t border-slate-200/80 pt-4">
							{#each mod.highlights as highlight (highlight)}
								<li class="flex items-start gap-2 text-sm text-slate-700">
									<CheckCircle2
										class="h-3.5 w-3.5 shrink-0 text-emerald-600 mt-0.5"
										aria-hidden="true"
									/>
									<span>{highlight}</span>
								</li>
							{/each}
						</ul>
					</div>

					<div class="mt-6 pt-4 border-t border-slate-200/80">
						<a
							href={mod.href}
							class="inline-flex items-center gap-1.5 text-sm font-semibold text-emerald-700 hover:text-emerald-800 transition"
						>
							<span>Conhecer módulo</span>
							<ArrowRight
								class="h-3.5 w-3.5 transition group-hover:translate-x-1"
								aria-hidden="true"
							/>
						</a>
					</div>
				</div>
			{/each}
		</div>
	</div>
</section>
