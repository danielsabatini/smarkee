<script lang="ts">
	import { CheckCircle2, ShieldCheck, Terminal } from 'lucide-svelte';
</script>

<footer class="border-t border-slate-200 bg-white text-sm text-slate-600">
	<div class="mx-auto max-w-7xl px-4 py-12 sm:px-6 lg:px-8">
		<div class="grid grid-cols-2 gap-8 md:grid-cols-5">
			<!-- Coluna 1: Marca e Missão -->
			<div class="col-span-2 space-y-4">
				<a href="/" class="inline-block" aria-label="Smarkee IT Solutions">
					<img src="/brand/smarkee-itsolutions.png" alt="Smarkee IT Solutions" class="h-7 w-auto" />
				</a>
				<p class="max-w-sm text-sm leading-relaxed text-slate-600">
					Plataforma de hospedagem e gestão para sua empresa. Foque no seu negócio, sem perder tempo
					com complexidade de infraestrutura e operações de DevOps.
				</p>
				<div class="flex items-center gap-2 text-sm font-medium text-emerald-800">
					<CheckCircle2 class="h-3.5 w-3.5 text-emerald-600" aria-hidden="true" />
					<span>Todos os sistemas operando normalmente</span>
				</div>
			</div>

			<!-- Coluna 2: Módulos & Plataforma -->
			<div class="space-y-3">
				<p class="text-sm font-bold uppercase tracking-wider text-slate-900">Plataforma</p>
				<ul class="space-y-2">
					<li>
						<a href="/produtos#ipm" class="transition hover:text-emerald-700"
							>IPM — Identidade & Acesso</a
						>
					</li>
					<li>
						<a href="/produtos#sum" class="transition hover:text-emerald-700"
							>SUM — Catálogo & Uso</a
						>
					</li>
					<li>
						<a href="/produtos#aem" class="transition hover:text-emerald-700"
							>AEM — Auditoria Imutável</a
						>
					</li>
					<li>
						<a href="/produtos#odm" class="transition hover:text-emerald-700"
							>ODM — Observabilidade</a
						>
					</li>
				</ul>
			</div>

			<!-- Coluna 3: Soluções & DX -->
			<div class="space-y-3">
				<p class="text-sm font-bold uppercase tracking-wider text-slate-900">Soluções & DX</p>
				<ul class="space-y-2">
					<li>
						<a href="/solucoes#multi-tenant" class="transition hover:text-emerald-700"
							>Multi-tenant Cloud</a
						>
					</li>
					<li>
						<a href="/solucoes#idp" class="transition hover:text-emerald-700"
							>Internal Developer Platform</a
						>
					</li>
					<li>
						<a href="/solucoes#governanca" class="transition hover:text-emerald-700"
							>Governança & Compliance</a
						>
					</li>
					<li>
						<a
							href="/produtos#cli"
							class="inline-flex items-center gap-1 transition hover:text-emerald-700"
						>
							<Terminal class="h-3 w-3 text-emerald-600" aria-hidden="true" />
							<span>CLI sk (Developer-first)</span>
						</a>
					</li>
				</ul>
			</div>

			<!-- Coluna 4: Recursos & Empresa -->
			<div class="space-y-3">
				<p class="text-sm font-bold uppercase tracking-wider text-slate-900">Recursos</p>
				<ul class="space-y-2">
					<li>
						<a href="/blog" class="transition hover:text-emerald-700">Blog de Engenharia</a>
					</li>
					<li>
						<a href="/sobre" class="transition hover:text-emerald-700">Sobre a Smarkee</a>
					</li>
					<li>
						<a href="/contato" class="transition hover:text-emerald-700">Contato & Suporte</a>
					</li>
					<li>
						<a
							href="http://localhost:5173"
							target="_blank"
							rel="noreferrer"
							class="transition hover:text-emerald-700"
						>
							Acessar Console Web
						</a>
					</li>
				</ul>
			</div>
		</div>

		<!-- Linha Inferior de Copyright e Conformidade -->
		<div
			class="mt-12 flex flex-col items-center justify-between gap-4 border-t border-slate-100 pt-8 sm:flex-row"
		>
			<p class="text-sm text-slate-500">
				&copy; {new Date().getFullYear()} Smarkee IT Solutions. Todos os direitos reservados.
			</p>
			<div class="flex items-center gap-4 text-sm text-slate-500">
				<span class="inline-flex items-center gap-1">
					<ShieldCheck class="h-3.5 w-3.5 text-emerald-600" aria-hidden="true" />
					Zero Vendor Lock-in & Padrões Abertos
				</span>
				<span>•</span>
				<span>JSON Schema V1</span>
				<span>•</span>
				<span>OpenTelemetry</span>
			</div>
		</div>
	</div>
</footer>
