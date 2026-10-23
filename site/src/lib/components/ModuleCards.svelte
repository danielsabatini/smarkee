<script lang="ts">
	import { ArrowRight, CheckCircle2, Terminal } from 'lucide-svelte';
	import { PLATFORM_MODULES } from '$lib/data/platform';
</script>

<section id="plataforma" class="relative border-t border-slate-200 bg-white py-20 sm:py-28">
	<div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
		<div class="mx-auto max-w-3xl text-center">
			<span class="text-xs font-semibold uppercase tracking-wider text-emerald-700">
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
								class="rounded-full px-2 py-0.5 font-mono text-xs font-semibold {mod.status === 'GA'
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
						<p class="mt-1 text-xs text-slate-500">
							{mod.tagline}
						</p>

						<p class="mt-4 text-xs leading-relaxed text-slate-600">
							{mod.description}
						</p>

						<ul class="mt-5 space-y-2 border-t border-slate-200/80 pt-4">
							{#each mod.highlights as highlight (highlight)}
								<li class="flex items-start gap-2 text-xs text-slate-700">
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
							class="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-700 hover:text-emerald-800 transition"
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

		<!-- Destaque Especial: Developer Tooling & CLI sk -->
		<div class="mt-12 rounded-2xl border border-emerald-200 bg-emerald-50/40 p-6 sm:p-8">
			<div class="grid grid-cols-1 items-center gap-6 lg:grid-cols-3">
				<div class="lg:col-span-2">
					<div
						class="inline-flex items-center gap-2 rounded-full border border-emerald-300 bg-emerald-100/60 px-3 py-1 text-xs font-medium text-emerald-900"
					>
						<Terminal class="h-3.5 w-3.5" aria-hidden="true" />
						<span>Developer-First Experience</span>
					</div>
					<h3 class="mt-3 text-xl font-bold text-slate-900 sm:text-2xl">
						CLI Smarkee (<code class="font-mono text-emerald-700">sk</code>)
					</h3>
					<p class="mt-2 text-xs leading-relaxed text-slate-600 sm:text-sm">
						Controle total da plataforma a partir do seu terminal. Com autenticação segura baseada
						em navegador, contextos locais por projeto, saída em JSON/YAML e modo não-interativo
						para pipelines de CI/CD.
					</p>
					<div class="mt-4 flex flex-wrap gap-2 text-xs">
						<span
							class="rounded-md border border-slate-200 bg-white px-2.5 py-1 font-mono text-slate-800 shadow-2xs"
							>sk login</span
						>
						<span
							class="rounded-md border border-slate-200 bg-white px-2.5 py-1 font-mono text-slate-800 shadow-2xs"
							>sk ipm org create &lt;name&gt;</span
						>
						<span
							class="rounded-md border border-slate-200 bg-white px-2.5 py-1 font-mono text-slate-800 shadow-2xs"
							>sk sum enable ipm</span
						>
					</div>
				</div>

				<div class="flex justify-start lg:justify-end">
					<a
						href="/produtos#cli"
						class="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-5 py-2.5 text-xs font-semibold text-white shadow-xs transition hover:bg-emerald-700"
					>
						<span>Documentação da CLI</span>
						<ArrowRight class="h-4 w-4" aria-hidden="true" />
					</a>
				</div>
			</div>
		</div>
	</div>
</section>
