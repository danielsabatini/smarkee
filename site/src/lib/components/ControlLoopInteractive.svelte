<script lang="ts">
	import { Check, Loader2, Play, ShieldCheck } from 'lucide-svelte';

	type LoopStep = 'idle' | 'submitting' | 'accepted' | 'reconciling' | 'ready';

	let currentStep = $state<LoopStep>('ready');
	let orgName = $state('acme-fintech');
	let operationId = $state('0199c8d0-9900-7a00-8b00-112233445566');
	let generation = $state(1);

	async function runSimulation(): Promise<void> {
		currentStep = 'submitting';
		generation += 1;
		operationId = `0199c8d0-9900-${Math.floor(1000 + Math.random() * 9000)}-${Math.floor(1000 + Math.random() * 9000)}`;

		await new Promise((r) => setTimeout(r, 600));
		currentStep = 'accepted';

		await new Promise((r) => setTimeout(r, 800));
		currentStep = 'reconciling';

		await new Promise((r) => setTimeout(r, 1200));
		currentStep = 'ready';
	}
</script>

<section
	id="loop-de-controle"
	class="relative border-t border-slate-200 bg-slate-50 py-20 sm:py-28"
>
	<div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
		<div class="mx-auto max-w-3xl text-center">
			<span class="text-xs font-semibold uppercase tracking-wider text-emerald-700">
				Arquitetura Fundamental
			</span>
			<h2 class="mt-2 text-2xl font-bold tracking-tight text-slate-900 sm:text-4xl">
				O Loop de Controle Declarativo da Smarkee
			</h2>
			<p class="mt-4 text-sm leading-relaxed text-slate-600 sm:text-base">
				Diferente de APIs bloqueantes que falham silenciosamente na metade do caminho, a Smarkee
				opera com o modelo inspirado no Kubernetes: <strong>Intenção Declarada</strong>,
				<strong>Confirmação Assíncrona (202 Accepted)</strong>
				e <strong>Reconciliação Contínua</strong> orientada a eventos duráveis no NATS JetStream.
			</p>
		</div>

		<!-- Simulador Interativo do Loop -->
		<div class="mt-12 rounded-2xl border border-slate-200 bg-white p-6 shadow-sm">
			<div
				class="flex flex-col items-start justify-between gap-4 border-b border-slate-100 pb-5 sm:flex-row sm:items-center"
			>
				<div>
					<h3 class="text-sm font-bold text-slate-900">Simulador de Reconciliação em Tempo Real</h3>
					<p class="text-xs text-slate-500">
						Dispare uma nova intenção declarativa e acompanhe a convergência automática entre
						Desired e Observed.
					</p>
				</div>

				<div class="flex items-center gap-2">
					<input
						type="text"
						bind:value={orgName}
						placeholder="nome-da-organizacao"
						class="rounded-xl border border-slate-300 bg-white px-3 py-1.5 font-mono text-xs text-slate-900 placeholder:text-slate-400 focus:border-emerald-500 focus:outline-hidden"
					/>
					<button
						type="button"
						onclick={runSimulation}
						disabled={currentStep === 'submitting' || currentStep === 'reconciling'}
						class="inline-flex items-center gap-1.5 rounded-xl bg-emerald-600 px-4 py-1.5 text-xs font-semibold text-white transition hover:bg-emerald-700 disabled:opacity-50"
					>
						{#if currentStep === 'submitting' || currentStep === 'reconciling'}
							<Loader2 class="h-3.5 w-3.5 animate-spin" aria-hidden="true" />
							<span>Reconciliando...</span>
						{:else}
							<Play class="h-3.5 w-3.5" aria-hidden="true" />
							<span>Enviar Intenção</span>
						{/if}
					</button>
				</div>
			</div>

			<!-- Visualizador dos 3 Estados -->
			<div class="mt-8 grid grid-cols-1 gap-6 md:grid-cols-3">
				<!-- Fase 1: Estado Desejado (Desired) -->
				<div class="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
					<div class="flex items-center justify-between">
						<span class="text-xs font-bold text-slate-800">1. Estado Desejado (Desired)</span>
						<span
							class="rounded bg-white border border-slate-200 px-2 py-0.5 font-mono text-xs text-slate-700"
						>
							Gen {generation}
						</span>
					</div>
					<p class="mt-1 text-xs text-slate-500">Intenção declarada pelo cliente via API/CLI.</p>

					<div
						class="mt-3 rounded-lg bg-slate-900 p-3 font-mono text-xs text-emerald-300 shadow-inner"
					>
						<pre class="overflow-x-auto whitespace-pre"><code
								>{`{
  "name": "${orgName}",
  "lifecycle": "present",
  "deletionProtection": true,
  "desiredGeneration": ${generation}
}`}</code
							></pre>
					</div>
				</div>

				<!-- Fase 2: Confirmação Assíncrona & Mensageria -->
				<div class="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
					<div class="flex items-center justify-between">
						<span class="text-xs font-bold text-slate-800">2. HTTP 202 & NATS JetStream</span>
						{#if currentStep === 'submitting' || currentStep === 'accepted' || currentStep === 'reconciling'}
							<span
								class="flex items-center gap-1 rounded bg-amber-50 border border-amber-200 px-2 py-0.5 font-mono text-xs text-amber-800"
							>
								<Loader2 class="h-2.5 w-2.5 animate-spin" aria-hidden="true" />
								<span>Processando</span>
							</span>
						{:else}
							<span
								class="rounded bg-emerald-50 border border-emerald-200 px-2 py-0.5 font-mono text-xs text-emerald-800"
							>
								Accepted
							</span>
						{/if}
					</div>
					<p class="mt-1 text-xs text-slate-500">Resposta imediata sem bloqueio de thread.</p>

					<div
						class="mt-3 rounded-lg bg-slate-900 p-3 font-mono text-xs text-blue-300 shadow-inner"
					>
						<pre class="overflow-x-auto whitespace-pre"><code
								>{`{
  "status": "202 Accepted",
  "operationId": "${operationId}",
  "stream": "IPM_EVENTS",
  "phase": "${currentStep === 'ready' ? 'Ready' : 'Reconciling'}"
}`}</code
							></pre>
					</div>
				</div>

				<!-- Fase 3: Estado Observado (Observed) -->
				<div class="rounded-xl border border-slate-200 bg-slate-50/70 p-4">
					<div class="flex items-center justify-between">
						<span class="text-xs font-bold text-slate-800">3. Estado Observado (Observed)</span>
						{#if currentStep === 'ready'}
							<span
								class="flex items-center gap-1 rounded bg-emerald-50 border border-emerald-200 px-2 py-0.5 font-mono text-xs text-emerald-800"
							>
								<Check class="h-2.5 w-2.5" aria-hidden="true" />
								<span>Ready: True</span>
							</span>
						{:else}
							<span
								class="rounded bg-blue-50 border border-blue-200 px-2 py-0.5 font-mono text-xs text-blue-800"
							>
								Convergindo
							</span>
						{/if}
					</div>
					<p class="mt-1 text-xs text-slate-500">
						Realidade verificada pelo controlador de recurso.
					</p>

					<div
						class="mt-3 rounded-lg bg-slate-900 p-3 font-mono text-xs text-amber-200 shadow-inner"
					>
						<pre class="overflow-x-auto whitespace-pre"><code
								>{`{
  "observedGeneration": ${currentStep === 'ready' ? generation : generation - 1},
  "conditions": [
    {
      "type": "Ready",
      "status": "${currentStep === 'ready' ? 'True' : 'False'}",
      "reason": "${currentStep === 'ready' ? 'Reconciled' : 'Reconciling'}"
    }
  ]
}`}</code
							></pre>
					</div>
				</div>
			</div>

			<!-- Indicador de Invariante -->
			<div
				class="mt-6 flex flex-col items-center justify-between gap-3 rounded-xl border border-emerald-200 bg-emerald-50 px-4 py-3 sm:flex-row"
			>
				<div class="flex items-center gap-2 text-xs text-emerald-900">
					<ShieldCheck class="h-4 w-4 text-emerald-700" aria-hidden="true" />
					<span
						><strong>Invariante da Plataforma:</strong> Recursos só respondem como
						<code>Ready</code>
						quando <code>observedGeneration === desiredGeneration</code>.</span
					>
				</div>
				<span class="font-mono text-xs font-semibold text-emerald-800"
					>Zero Inconsistência de Estado</span
				>
			</div>
		</div>
	</div>
</section>
