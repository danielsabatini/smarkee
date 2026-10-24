<script lang="ts">
	import { Terminal, Globe, Code2, Database, Check, Copy } from 'lucide-svelte';

	type InterfaceKey = 'console' | 'cli' | 'api' | 'terraform';

	let activeInterface = $state<InterfaceKey>('console');
	let copied = $state(false);

	const interfaces: Record<
		InterfaceKey,
		{
			title: string;
			desc: string;
			// eslint-disable-next-line @typescript-eslint/no-explicit-any
			icon: any;
			color: string;
			label: string;
			language: string;
			code: string;
		}
	> = {
		console: {
			title: 'Web Console',
			desc: 'Interface visual rica e intuitiva para operações do dia a dia e governança.',
			icon: Globe,
			color: 'text-emerald-700 bg-emerald-100',
			label: 'Console Overview',
			language: 'txt',
			code: `Dashboard da Organização
----------------------------------------
[ Serviços Ativos ]    [ Usuários ]
  IPM (Identidade)       12 membros
  ODM (Métricas)         3 admin
  AEM (Auditoria)        -

Últimos Eventos:
• 14:02 - API Key gerada (token_8x...)
• 11:45 - Acesso concedido a alice@...
• 09:30 - Organização criada`
		},
		cli: {
			title: 'CLI (sk)',
			desc: 'Automação via terminal com a nossa ferramenta de linha de comando nativa.',
			icon: Terminal,
			color: 'text-indigo-700 bg-indigo-100',
			label: 'Terminal',
			language: 'bash',
			code: `# Login com fluxo PKCE no navegador
sk login

# Criação declarativa de uma nova organização
sk ipm org create wayne-enterprises --protected

# Habilitando o serviço IPM sob demanda
sk sum enable ipm`
		},
		api: {
			title: 'API REST',
			desc: 'Integração direta com seus sistemas através de endpoints padronizados.',
			icon: Code2,
			color: 'text-rose-700 bg-rose-100',
			label: 'HTTP Request',
			language: 'bash',
			code: `curl -X POST https://api.smarkee.internal/v1/ipm/organizations \\
  -H "Authorization: Bearer \${SMARKEE_TOKEN}" \\
  -H "Content-Type: application/json" \\
  -d '{
    "name": "wayne-enterprises",
    "deletionProtection": true
  }'

# HTTP 202 Accepted
# {"operationId": "0199c8d0-9900-7a00-8b00", "status": "accepted"}`
		},
		terraform: {
			title: 'Terraform',
			desc: 'Gerenciamento de infraestrutura como código (IaC) de forma declarativa.',
			icon: Database,
			color: 'text-purple-700 bg-purple-100',
			label: 'main.tf',
			language: 'hcl',
			code: `terraform {
  required_providers {
    smarkee = {
      source = "smarkee/smarkee"
      version = "~> 1.0"
    }
  }
}

resource "smarkee_organization" "main" {
  name                = "wayne-enterprises"
  deletion_protection = true
}

resource "smarkee_service_entitlement" "ipm" {
  organization_id = smarkee_organization.main.id
  service         = "ipm"
}`
		}
	};

	async function copyCode(): Promise<void> {
		try {
			if (typeof navigator !== 'undefined' && navigator.clipboard) {
				await navigator.clipboard.writeText(interfaces[activeInterface].code);
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

<section class="border-t border-slate-200 bg-white py-20 sm:py-28">
	<div class="mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
		<div class="grid grid-cols-1 items-start gap-12 lg:grid-cols-12">
			<!-- Texto e Navegação Lateral -->
			<div class="lg:col-span-5 flex flex-col justify-center">
				<h2 class="text-3xl font-bold tracking-tight text-slate-900 sm:text-4xl">
					Controle total, na interface da sua escolha
				</h2>
				<p class="mt-4 text-base leading-relaxed text-slate-600 mb-8">
					A Smarkee adota a filosofia API-first. Tudo o que você pode visualizar no Console pode ser
					programado via API, automatizado na CLI ou gerenciado declarativamente com Terraform.
				</p>

				<div
					class="flex flex-col space-y-3"
					role="tablist"
					aria-label="Interfaces de gerenciamento da plataforma"
				>
					{#each Object.entries(interfaces) as [key, value] (key)}
						{@const isSelected = activeInterface === key}
						{@const Icon = value.icon}
						<button
							type="button"
							role="tab"
							id="tab-{key}"
							aria-selected={isSelected}
							aria-controls="panel-interface-code"
							class="group flex items-start gap-4 rounded-xl border p-4 text-left transition-all duration-200 {isSelected
								? 'border-emerald-500 bg-emerald-50/50 shadow-xs'
								: 'border-slate-200 bg-white hover:border-slate-300 hover:bg-slate-50'}"
							onclick={() => (activeInterface = key as InterfaceKey)}
						>
							<div
								class="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg {isSelected
									? value.color
									: 'bg-slate-100 text-slate-500 group-hover:bg-slate-200 group-hover:text-slate-700'} transition-colors"
							>
								<Icon class="h-5 w-5" aria-hidden="true" />
							</div>
							<div>
								<h3
									class="font-bold {isSelected
										? 'text-emerald-900'
										: 'text-slate-900'} transition-colors"
								>
									{value.title}
								</h3>
								<p
									class="mt-1 text-sm {isSelected
										? 'text-emerald-700/80'
										: 'text-slate-500'} transition-colors"
								>
									{value.desc}
								</p>
							</div>
						</button>
					{/each}
				</div>
			</div>

			<!-- Editor / Visualizador -->
			<div
				id="panel-interface-code"
				role="tabpanel"
				aria-labelledby="tab-{activeInterface}"
				class="lg:col-span-7 lg:mt-8"
			>
				<div
					class="rounded-2xl border border-slate-200 bg-slate-900 shadow-2xl overflow-hidden ring-1 ring-white/10"
				>
					<!-- Mac-style header -->
					<div
						class="flex items-center justify-between border-b border-slate-700/50 bg-slate-800/50 px-4 py-3"
					>
						<div class="flex items-center gap-2">
							<div class="h-3 w-3 rounded-full bg-red-500/80"></div>
							<div class="h-3 w-3 rounded-full bg-amber-500/80"></div>
							<div class="h-3 w-3 rounded-full bg-green-500/80"></div>
							<span class="ml-2 font-mono text-xs text-slate-400">
								{interfaces[activeInterface].label}
							</span>
						</div>

						<button
							type="button"
							onclick={copyCode}
							aria-label={copied ? 'Copiado' : 'Copiar'}
							class="inline-flex items-center gap-1.5 rounded border border-slate-600 bg-slate-700/50 px-2 py-1 text-xs font-medium text-slate-300 transition hover:bg-slate-600 hover:text-white"
						>
							{#if copied}
								<Check class="h-3.5 w-3.5 text-emerald-400" aria-hidden="true" />
								<span class="text-emerald-400">Copiado</span>
							{:else}
								<Copy class="h-3.5 w-3.5 text-slate-400" aria-hidden="true" />
								<span>Copiar</span>
							{/if}
						</button>
					</div>

					<!-- Corpo do Código -->
					<div
						class="p-6 font-mono text-sm leading-relaxed overflow-x-auto min-h-[320px] text-slate-300"
					>
						<pre class="whitespace-pre"><code>{interfaces[activeInterface].code}</code></pre>
					</div>
				</div>
			</div>
		</div>
	</div>
</section>
