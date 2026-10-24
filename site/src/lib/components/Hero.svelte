<script lang="ts">
	import { ArrowRight } from 'lucide-svelte';
</script>

<div
	class="relative overflow-hidden bg-slate-50 pt-20 pb-24 sm:pt-28 sm:pb-32 border-b border-slate-200"
>
	<!-- Decoration -->
	<div class="absolute inset-x-0 top-0 h-96 bg-linear-to-b from-slate-100 to-transparent"></div>

	<div class="relative mx-auto max-w-7xl px-4 sm:px-6 lg:px-8">
		<div class="mx-auto max-w-4xl text-center">
			<h1 class="text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl lg:text-6xl">
				Acelere o seu negócio com
				<span class="block mt-2 text-emerald-700">nossa plataforma em nuvem.</span>
			</h1>
			<p class="mt-6 text-lg leading-relaxed text-slate-600 sm:text-xl">
				Uma plataforma modular que integra identidade, catálogo de serviços sob demanda, auditoria e
				observabilidade. Governança e autonomia para acelerar o desenvolvimento do seu produto.
			</p>

			<div class="mt-10 flex flex-wrap items-center justify-center gap-4">
				<a
					href="#plataforma"
					class="inline-flex items-center gap-2 rounded-xl bg-emerald-600 px-8 py-3.5 text-sm font-bold text-white shadow-sm shadow-emerald-700/20 transition hover:bg-emerald-700 hover:shadow-md"
				>
					<span>Explorar Plataforma</span>
					<ArrowRight class="h-4 w-4" aria-hidden="true" />
				</a>
				<a
					href="/contato"
					class="inline-flex items-center gap-2 rounded-xl border border-slate-300 bg-white px-8 py-3.5 text-sm font-bold text-slate-700 shadow-sm transition hover:border-slate-400 hover:bg-slate-50"
				>
					<span>Falar com Especialista</span>
				</a>
			</div>
		</div>

		<!-- CLI Preview / Code snippet -->
		<div class="mt-16 sm:mt-24">
			<div class="mx-auto max-w-3xl rounded-2xl bg-slate-900 p-2 shadow-2xl ring-1 ring-slate-800">
				<!-- Mac-style header -->
				<div class="flex items-center gap-2 px-3 py-2 border-b border-slate-800">
					<div class="h-3 w-3 rounded-full bg-red-500"></div>
					<div class="h-3 w-3 rounded-full bg-amber-500"></div>
					<div class="h-3 w-3 rounded-full bg-green-500"></div>
					<span class="ml-2 font-mono text-sm font-medium text-slate-400">sk — smarkee-cli</span>
				</div>
				<!-- CLI Output -->
				<div class="p-6 font-mono text-sm text-slate-300 leading-relaxed overflow-x-auto">
					<p class="text-emerald-400">$ sk login</p>
					<p class="mt-1 text-slate-400">Autenticando via navegador (OIDC PKCE)...</p>
					<p class="mt-1 text-emerald-400">✓ Sessão estabelecida para contato@smarkee.com.br</p>

					<p class="mt-4 text-emerald-400">$ sk org list</p>
					<p class="mt-1 text-slate-200">ID NOME STATUS</p>
					<p class="text-slate-400">
						org_4f89d3a1 Smarkee IT Solutions <span class="text-emerald-400">ACTIVE</span>
					</p>

					<p class="mt-4 text-emerald-400">$ sk sum enable odm</p>
					<p class="mt-1 text-slate-400">Registrando intenção (lifecycle: present)...</p>
					<p class="mt-1 text-emerald-400">
						✓ Observability Data Manager (ODM) provisionado na org_4f89d3a1
					</p>
				</div>
			</div>

			<!-- Faixa tipográfica de capacidades centrais -->
			<div class="mx-auto mt-14 max-w-5xl border-t border-slate-200 pt-10">
				<dl
					class="grid grid-cols-1 gap-8 sm:grid-cols-2 lg:grid-cols-4 lg:divide-x lg:divide-slate-200"
				>
					<div class="flex flex-col items-start lg:pr-6">
						<dt class="font-mono text-xs font-bold tracking-wider uppercase text-emerald-700">
							Identidade (IPM)
						</dt>
						<dd class="mt-1.5 text-base font-bold text-slate-900">Gestão de Acessos</dd>
						<dd class="mt-1 text-sm text-slate-600">Organizações, contas e permissões seguras.</dd>
					</div>

					<div class="flex flex-col items-start lg:px-6">
						<dt class="font-mono text-xs font-bold tracking-wider uppercase text-emerald-700">
							Serviços (SUM)
						</dt>
						<dd class="mt-1.5 text-base font-bold text-slate-900">Recursos sob Demanda</dd>
						<dd class="mt-1 text-sm text-slate-600">Catálogo unificado com ativação imediata.</dd>
					</div>

					<div class="flex flex-col items-start lg:px-6">
						<dt class="font-mono text-xs font-bold tracking-wider uppercase text-emerald-700">
							Auditoria (AEM)
						</dt>
						<dd class="mt-1.5 text-base font-bold text-slate-900">Registro Imutável</dd>
						<dd class="mt-1 text-sm text-slate-600">
							Trilha auditável para segurança e compliance.
						</dd>
					</div>

					<div class="flex flex-col items-start lg:pl-6">
						<dt class="font-mono text-xs font-bold tracking-wider uppercase text-emerald-700">
							Observabilidade (ODM)
						</dt>
						<dd class="mt-1.5 text-base font-bold text-slate-900">Métricas, Logs e Traces</dd>
						<dd class="mt-1 text-sm text-slate-600">Telemetria integrada em padrão aberto.</dd>
					</div>
				</dl>
			</div>
		</div>
	</div>
</div>
