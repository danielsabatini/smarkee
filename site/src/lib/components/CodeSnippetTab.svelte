<script lang="ts">
	import { Check, Copy } from 'lucide-svelte';

	type SnippetKey = 'cli' | 'rest' | 'manifest';

	let activeTab = $state<SnippetKey>('cli');
	let copied = $state(false);

	const snippets: Record<SnippetKey, { label: string; language: string; code: string }> = {
		cli: {
			label: 'CLI (sk)',
			language: 'bash',
			code: `# Login com fluxo PKCE no navegador
sk login

# Criação declarativa de uma nova organização
sk ipm org create wayne-enterprises --protected

# Habilitando o serviço IPM sob demanda no catálogo
sk sum enable ipm`
		},
		rest: {
			label: 'REST API',
			language: 'bash',
			code: `curl -X POST https://api.smarkee.internal/v1/ipm/organizations \\
  -H "Authorization: Bearer \${SMARKEE_TOKEN}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "wayne-enterprises",
    "deletionProtection": true
  }'

# Retorno imediato (HTTP 202 Accepted):
# {"operationId": "0199c8d0-9900-7a00-8b00", "status": "accepted"}`
		},
		manifest: {
			label: 'Declarative Manifest (JSON/YAML)',
			language: 'json',
			code: `{
  "$schema": "https://smarkee.internal/schemas/ipm/organization/requested-create.v1.schema.json",
  "operationId": "0199c8d0-9900-7a00-8b00",
  "specification": {
    "name": "wayne-enterprises",
    "deletionProtection": true
  }
}`
		}
	};

	async function copyCode(): Promise<void> {
		try {
			if (typeof navigator !== 'undefined' && navigator.clipboard) {
				await navigator.clipboard.writeText(snippets[activeTab].code);
				copied = true;
				setTimeout(() => {
					copied = false;
				}, 2000);
			}
		} catch {
			copied = false;
		}
	}
</script>

<section class="border-t border-slate-900 bg-slate-950 py-20 sm:py-28">
	<div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
		<div class="grid grid-cols-1 items-center gap-10 lg:grid-cols-2">
			<div>
				<span class="text-xs font-semibold uppercase tracking-wider text-emerald-400">
					Developer Experience
				</span>
				<h2 class="mt-2 text-2xl font-bold tracking-tight text-white sm:text-4xl">
					Projetado para Engenheiros que Constróem Plataformas
				</h2>
				<p class="mt-4 text-sm leading-relaxed text-slate-300">
					A Smarkee trata APIs, CLIs e especificações como cidadãos de primeira classe. Todas as
					ações são validadas por contratos rígidos de JSON Schema, emitindo eventos auditáveis no
					NATS JetStream com idempotência comprovada.
				</p>

				<div class="mt-6 space-y-3 text-xs text-slate-400">
					<div class="flex items-start gap-2.5">
						<span
							class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-950 text-emerald-400 font-mono text-[10px] font-bold"
							>1</span
						>
						<span
							><strong>Zero Surpresas:</strong> Schemas validados antes da persistência no banco e do
							despacho do evento.</span
						>
					</div>
					<div class="flex items-start gap-2.5">
						<span
							class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-950 text-emerald-400 font-mono text-[10px] font-bold"
							>2</span
						>
						<span
							><strong>Digest Criptográfico:</strong> Cada payload de solicitação tem sua impressão SHA-256
							registrada no AEM.</span
						>
					</div>
					<div class="flex items-start gap-2.5">
						<span
							class="flex h-5 w-5 shrink-0 items-center justify-center rounded-full bg-emerald-950 text-emerald-400 font-mono text-[10px] font-bold"
							>3</span
						>
						<span
							><strong>Rastreabilidade Unificada:</strong> Mesmos identificadores e IDs compartilhados
							da CLI ao Console.</span
						>
					</div>
				</div>
			</div>

			<!-- Editor / Visualizador de Snippet -->
			<div
				class="rounded-2xl border border-slate-800 bg-slate-900/60 p-4 shadow-xl backdrop-blur-md"
			>
				<div class="flex items-center justify-between border-b border-slate-800 pb-3">
					<!-- Abas -->
					<div class="flex items-center gap-1.5">
						{#each Object.entries(snippets) as [key, value] (key)}
							<button
								type="button"
								onclick={() => (activeTab = key as SnippetKey)}
								class="rounded-lg px-2.5 py-1 text-xs font-medium transition {activeTab === key
									? 'bg-slate-800 text-white font-semibold'
									: 'text-slate-400 hover:text-slate-200'}"
							>
								{value.label}
							</button>
						{/each}
					</div>

					<button
						type="button"
						onclick={copyCode}
						aria-label={copied ? 'Copiado para a área de transferência' : 'Copiar código'}
						class="inline-flex items-center gap-1 rounded-lg border border-slate-700 bg-slate-800 px-2.5 py-1 text-[11px] font-medium text-slate-300 transition hover:bg-slate-700 hover:text-white"
					>
						{#if copied}
							<Check class="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
							<span>Copiado!</span>
						{:else}
							<Copy class="h-3.5 w-3.5" aria-hidden="true" />
							<span>Copiar</span>
						{/if}
					</button>
				</div>

				<!-- Corpo do Código -->
				<div
					class="mt-4 rounded-xl bg-slate-950 p-4 font-mono text-xs text-slate-200 leading-relaxed overflow-x-auto"
				>
					<pre class="whitespace-pre"><code>{snippets[activeTab].code}</code></pre>
				</div>
			</div>
		</div>
	</div>
</section>
