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
			<div
				class="inline-flex items-center gap-3 rounded-full border border-slate-200 bg-white px-1 py-1 pr-4 text-sm shadow-sm gap-2 border-emerald-200 bg-emerald-50 px-3.5 text-emerald-800 shadow-2xs"
			>
				<span
					class="flex items-center justify-center rounded-full bg-slate-100 px-3 py-1 font-medium text-slate-900"
					>Smarkee Plataforma</span
				>
				<span class="flex items-center gap-2 font-medium text-emerald-700">
					<span class="flex h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
					Ecossistema Integrado
				</span>
			</div>

			<h1
				class="mt-6 text-4xl font-extrabold tracking-tight text-slate-900 sm:text-5xl lg:text-6xl"
			>
				Acelere o seu negócio com
				<span class="block mt-2 text-emerald-700">nossa plataforma em nuvem.</span>
			</h1>
			<p class="mt-6 text-lg leading-relaxed text-slate-600 sm:text-xl">
				Uma plataforma modular que integra identidade, catálogo de serviços sob demanda, auditoria e
				observabilidade. Governança e autonomia para acelerar o desenvolvimento do seu produto.
			</p>

			<div class="mt-10 flex flex-wrap items-center justify-center gap-4">
				<a
					href="#features"
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

			<div
				class="mt-12 flex flex-wrap items-center justify-center gap-x-8 gap-y-3 text-sm text-slate-600"
			>
				<p class="font-medium text-slate-900">Módulos nativos integrados:</p>
				<div class="grid grid-cols-1 gap-4 md:grid-cols-4">
					<!-- Card 1: IPM -->
					<div class="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs">
						<span class="font-mono text-sm font-bold text-slate-800">Identidade</span>
						<p class="mt-2 text-sm font-semibold text-slate-900">Gestão de Acessos</p>
						<p class="mt-1 text-sm text-slate-500">Organizações e usuários.</p>
					</div>

					<!-- Card 2: SUM -->
					<div class="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs">
						<span class="font-mono text-sm font-bold text-slate-800">Serviços</span>
						<p class="mt-2 text-sm font-semibold text-slate-900">Recursos sob Demanda</p>
						<p class="mt-1 text-sm text-slate-500">Habilitação simplificada.</p>
					</div>

					<!-- Card 3: AEM -->
					<div class="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs">
						<span class="font-mono text-sm font-bold text-slate-800">Auditoria</span>
						<p class="mt-2 text-sm font-semibold text-slate-900">Registro Imutável</p>
						<p class="mt-1 text-sm text-slate-500">Segurança e compliance.</p>
					</div>

					<!-- Card 4: ODM -->
					<div class="rounded-xl border border-slate-200 bg-white p-4 shadow-2xs">
						<span class="font-mono text-sm font-bold text-slate-800">Métricas</span>
						<p class="mt-2 text-sm font-semibold text-slate-900">Observabilidade</p>
						<p class="mt-1 text-sm text-slate-500">Monitoramento integrado.</p>
					</div>
				</div>
			</div>
		</div>
	</div>
</div>
