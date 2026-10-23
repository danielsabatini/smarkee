<script lang="ts">
	import { CheckCircle2, Send } from 'lucide-svelte';

	let name = $state('');
	let email = $state('');
	let company = $state('');
	let message = $state('');
	let submitted = $state(false);

	function handleSubmit(event: SubmitEvent): void {
		event.preventDefault();
		if (!name.trim() || !email.trim()) {
			return;
		}
		submitted = true;
	}
</script>

<svelte:head>
	<title>Fale com a Engenharia — Smarkee IT Solutions</title>
	<meta
		name="description"
		content="Entre em contato com a equipe da Smarkee IT Solutions para agendar uma demonstração técnica, discutir arquitetura ou suporte corporativo."
	/>
</svelte:head>

<div class="mx-auto max-w-7xl px-4 py-16 sm:px-6 lg:px-8">
	<div class="mx-auto max-w-3xl text-center">
		<span class="text-xs font-semibold uppercase tracking-wider text-emerald-700">
			Atendimento Técnico
		</span>
		<h1 class="mt-2 text-3xl font-extrabold tracking-tight text-slate-900 sm:text-5xl">
			Fale com Nossos Especialistas
		</h1>
		<p class="mt-4 text-sm leading-relaxed text-slate-600 sm:text-base">
			Agende uma demonstração ao vivo da plataforma Smarkee, tire dúvidas de integração ou explore
			como implantar o loop declarativo na sua infraestrutura.
		</p>
	</div>

	<div class="mx-auto mt-16 max-w-2xl rounded-2xl border border-slate-200 bg-white shadow-sm p-8">
		{#if submitted}
			<div class="py-12 text-center space-y-4">
				<div
					class="mx-auto flex h-14 w-14 items-center justify-center rounded-full bg-emerald-50 border border-emerald-200 text-emerald-700"
				>
					<CheckCircle2 class="h-8 w-8" aria-hidden="true" />
				</div>
				<h2 class="text-xl font-bold text-slate-900">Mensagem Enviada com Sucesso!</h2>
				<p class="mx-auto max-w-md text-xs text-slate-700">
					Obrigado pelo contato, <strong>{name}</strong>! Nossa equipe de engenharia responderá para
					o endereço <strong>{email}</strong> com os próximos passos.
				</p>
				<button
					type="button"
					onclick={() => {
						submitted = false;
						name = '';
						email = '';
						company = '';
						message = '';
					}}
					class="mt-4 rounded-xl border border-slate-300 bg-white px-4 py-2 text-xs font-semibold text-slate-700 hover:bg-slate-100"
				>
					Enviar outra mensagem
				</button>
			</div>
		{:else}
			<form onsubmit={handleSubmit} class="space-y-5">
				<div>
					<label for="name" class="block text-xs font-semibold text-slate-700">
						Nome Completo *
					</label>
					<input
						type="text"
						id="name"
						bind:value={name}
						required
						placeholder="Seu nome"
						class="mt-1.5 w-full rounded-xl border border-slate-300 bg-slate-50 px-3.5 py-2 text-xs text-slate-900 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-hidden"
					/>
				</div>

				<div>
					<label for="email" class="block text-xs font-semibold text-slate-700">
						E-mail Corporativo *
					</label>
					<input
						type="email"
						id="email"
						bind:value={email}
						required
						placeholder="voce@suaempresa.com"
						class="mt-1.5 w-full rounded-xl border border-slate-300 bg-slate-50 px-3.5 py-2 text-xs text-slate-900 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-hidden"
					/>
				</div>

				<div>
					<label for="company" class="block text-xs font-semibold text-slate-700">
						Empresa / Organização
					</label>
					<input
						type="text"
						id="company"
						bind:value={company}
						placeholder="Nome da sua empresa"
						class="mt-1.5 w-full rounded-xl border border-slate-300 bg-slate-50 px-3.5 py-2 text-xs text-slate-900 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-hidden"
					/>
				</div>

				<div>
					<label for="message" class="block text-xs font-semibold text-slate-700">
						Como podemos ajudar?
					</label>
					<textarea
						id="message"
						rows="4"
						bind:value={message}
						placeholder="Descreva seu projeto, desafio de nuvem ou o que gostaria de ver na demonstração..."
						class="mt-1.5 w-full rounded-xl border border-slate-300 bg-slate-50 px-3.5 py-2 text-xs text-slate-900 placeholder:text-slate-600 focus:border-emerald-500 focus:outline-hidden"
					></textarea>
				</div>

				<div class="pt-2">
					<button
						type="submit"
						class="inline-flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 px-6 py-3 text-xs font-semibold text-slate-900 shadow-lg transition hover:bg-emerald-700"
					>
						<Send class="h-4 w-4" aria-hidden="true" />
						<span>Enviar Solicitação</span>
					</button>
				</div>
			</form>
		{/if}
	</div>
</div>
