<script lang="ts">
	import { ArrowRight, CheckCircle2, Terminal } from 'lucide-svelte';
	import { PLATFORM_MODULES } from '$lib/data/platform';
</script>

<section id="plataforma" class="relative border-t border-slate-900 bg-slate-950 py-20 sm:py-28">
	<div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
		<div class="mx-auto max-w-3xl text-center">
			<span class="text-xs font-semibold uppercase tracking-wider text-emerald-400">
				Suíte de Produtos Smarkee
			</span>
			<h2 class="mt-2 text-2xl font-bold tracking-tight text-white sm:text-4xl">
				Módulos Especializados em Uma Plataforma Unificada
			</h2>
			<p class="mt-4 text-sm leading-relaxed text-slate-400 sm:text-base">
				Cada capacidade de nuvem foi projetada com responsabilidade única, contratos JSON Schema
				versionados e observabilidade de ponta a ponta.
			</p>
		</div>

		<div class="mt-14 grid grid-cols-1 gap-6 md:grid-cols-2 lg:grid-cols-4">
			{#each PLATFORM_MODULES as mod (mod.code)}
				<div
					class="group relative flex flex-col justify-between rounded-2xl border border-slate-800 bg-slate-900/50 p-6 transition hover:border-emerald-500/50 hover:bg-slate-900/80 hover:shadow-xl hover:shadow-emerald-950/20"
				>
					<div>
						<div class="flex items-center justify-between">
							<span class="font-mono text-sm font-bold text-emerald-400">{mod.code}</span>
							<span
								class="rounded-full px-2 py-0.5 font-mono text-[10px] font-semibold {mod.status ===
								'GA'
									? 'bg-emerald-950 text-emerald-300 border border-emerald-800'
									: 'bg-blue-950 text-blue-300 border border-blue-800'}"
							>
								{mod.status}
							</span>
						</div>

						<h3 class="mt-3 text-base font-bold text-white group-hover:text-emerald-300 transition">
							{mod.name}
						</h3>
						<p class="mt-1 text-xs text-slate-400">
							{mod.tagline}
						</p>

						<p class="mt-4 text-xs leading-relaxed text-slate-300">
							{mod.description}
						</p>

						<ul class="mt-5 space-y-2 border-t border-slate-800/80 pt-4">
							{#each mod.highlights as highlight (highlight)}
								<li class="flex items-start gap-2 text-[11px] text-slate-400">
									<CheckCircle2
										class="h-3.5 w-3.5 shrink-0 text-emerald-500 mt-0.5"
										aria-hidden="true"
									/>
									<span>{highlight}</span>
								</li>
							{/each}
						</ul>
					</div>

					<div class="mt-6 pt-4 border-t border-slate-800/80">
						<a
							href={mod.href}
							class="inline-flex items-center gap-1.5 text-xs font-semibold text-emerald-400 hover:text-emerald-300 transition"
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
		<div
			class="mt-12 rounded-2xl border border-emerald-900/40 bg-gradient-to-r from-emerald-950/30 via-slate-900/60 to-slate-950 p-6 sm:p-8"
		>
			<div class="grid grid-cols-1 items-center gap-6 lg:grid-cols-3">
				<div class="lg:col-span-2">
					<div
						class="inline-flex items-center gap-2 rounded-full border border-emerald-500/30 bg-emerald-950/50 px-3 py-1 text-xs text-emerald-300"
					>
						<Terminal class="h-3.5 w-3.5" aria-hidden="true" />
						<span>Developer-First Experience</span>
					</div>
					<h3 class="mt-3 text-xl font-bold text-white sm:text-2xl">
						CLI Smarkee (<code class="font-mono text-emerald-400">sk</code>)
					</h3>
					<p class="mt-2 text-xs leading-relaxed text-slate-300 sm:text-sm">
						Controle total da plataforma a partir do seu terminal. Com autenticação segura baseada
						em navegador, contextos locais por projeto, saída em JSON/YAML e modo não-interativo
						para pipelines de CI/CD.
					</p>
					<div class="mt-4 flex flex-wrap gap-2 text-xs">
						<span
							class="rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1 font-mono text-slate-300"
							>sk login</span
						>
						<span
							class="rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1 font-mono text-slate-300"
							>sk ipm org create &lt;name&gt;</span
						>
						<span
							class="rounded-md border border-slate-700 bg-slate-900 px-2.5 py-1 font-mono text-slate-300"
							>sk sum enable ipm</span
						>
					</div>
				</div>

				<div class="flex justify-start lg:justify-end">
					<a
						href="/produtos#cli"
						class="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-5 py-2.5 text-xs font-semibold text-white shadow-md transition hover:bg-emerald-500"
					>
						<span>Documentação da CLI</span>
						<ArrowRight class="h-4 w-4" aria-hidden="true" />
					</a>
				</div>
			</div>
		</div>
	</div>
</section>
