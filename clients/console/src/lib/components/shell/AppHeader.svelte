<script lang="ts">
	import {
		Activity,
		Bell,
		ChevronDown,
		CircleHelp,
		Menu,
		ShieldCheck,
		Sparkles,
		SquareTerminal,
		User
	} from 'lucide-svelte';
	import GlobalSearch from '$lib/components/shell/GlobalSearch.svelte';
	import OrganizationSelector from '$lib/components/shell/OrganizationSelector.svelte';
	import { getConsoleState } from '$lib/state/console-context.svelte';

	const consoleState = getConsoleState();

	let isProfileMenuOpen = $state(false);
	let isHelpModalOpen = $state(false);

	function handleMenuButtonClick(): void {
		if (typeof window !== 'undefined' && window.innerWidth < 1024) {
			consoleState.setMobileDrawerOpen(!consoleState.isMobileDrawerOpen);
		} else {
			consoleState.toggleSidebarCompact();
		}
	}

	function toggleProfileMenu(): void {
		isProfileMenuOpen = !isProfileMenuOpen;
	}

	function closeProfileMenu(): void {
		isProfileMenuOpen = false;
	}

	function handleKeydown(event: KeyboardEvent): void {
		if (event.key === 'Escape') {
			isProfileMenuOpen = false;
			isHelpModalOpen = false;
		}
	}
</script>

<svelte:window onkeydown={handleKeydown} />

<header
	class="sticky top-0 z-30 flex h-14 shrink-0 items-center justify-between gap-2 border-b border-slate-200 bg-white px-2.5 sm:gap-3 sm:px-4"
>
	<!-- Esquerda: Botão menu + Logo Oficial + Seletor de Organização -->
	<div class="flex min-w-0 items-center gap-1.5 sm:gap-3">
		<button
			type="button"
			onclick={handleMenuButtonClick}
			aria-label="Alternar menu de navegação lateral"
			data-testid="sidebar-toggle-button"
			class="shrink-0 rounded-lg p-1.5 text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 sm:p-2"
		>
			<Menu class="h-5 w-5" aria-hidden="true" />
		</button>

		<a
			href="/"
			aria-label="Smarkee Console — Página inicial"
			class="flex shrink-0 items-center gap-2 rounded-lg px-0.5 py-1 focus-visible:outline-emerald-600 sm:px-1"
		>
			<img
				src="/brand/s-small.png"
				alt="Smarkee"
				class="h-6 w-6 object-contain sm:h-7 sm:w-7"
				width="28"
				height="28"
			/>
			<span class="hidden text-base font-bold tracking-tight text-slate-900 sm:inline">
				Smarkee
			</span>
		</a>

		<div class="hidden h-5 w-px bg-slate-200 sm:block" aria-hidden="true"></div>

		<OrganizationSelector />
	</div>

	<!-- Centro: Busca Global -->
	<div class="hidden flex-1 justify-center px-2 md:flex">
		<GlobalSearch />
	</div>

	<!-- Direita: Ações Globais (Assistente/Busca mobile, CLI info, Notificações/Operações, Ajuda, Perfil) -->
	<div class="flex items-center gap-1 sm:gap-2">
		<button
			type="button"
			onclick={() => (consoleState.isGlobalSearchOpen = true)}
			aria-label="Abrir busca rápida e assistente de navegação"
			title="Busca rápida (⌘K)"
			class="hidden rounded-lg p-2 text-emerald-600 transition hover:bg-emerald-50 sm:inline-flex"
		>
			<Sparkles class="h-4 w-4" aria-hidden="true" />
		</button>

		<button
			type="button"
			onclick={() => consoleState.toggleOperationsPanel('operations')}
			aria-label={consoleState.activeOperationsCount > 0
				? `${consoleState.activeOperationsCount} operações em andamento — Abrir painel de operações assíncronas`
				: 'Abrir painel de operações assíncronas'}
			data-testid="header-operations-button"
			title="Operações do Control Loop"
			class="relative rounded-lg p-2 text-slate-600 transition hover:bg-slate-100 hover:text-slate-900"
		>
			<SquareTerminal class="h-4 w-4" aria-hidden="true" />
			{#if consoleState.activeOperationsCount > 0}
				<span
					aria-hidden="true"
					data-testid="active-operations-badge"
					class="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-emerald-600 px-1 text-[10px] font-bold text-white"
				>
					{consoleState.activeOperationsCount}
				</span>
			{/if}
		</button>

		<button
			type="button"
			onclick={() => consoleState.toggleOperationsPanel('notifications')}
			aria-label={consoleState.unreadNotificationsCount > 0
				? `${consoleState.unreadNotificationsCount} notificações não lidas — Abrir painel de notificações`
				: 'Abrir painel de notificações'}
			data-testid="header-notifications-button"
			title="Notificações"
			class="relative rounded-lg p-2 text-slate-600 transition hover:bg-slate-100 hover:text-slate-900"
		>
			<Bell class="h-4 w-4" aria-hidden="true" />
			{#if consoleState.unreadNotificationsCount > 0}
				<span
					aria-hidden="true"
					data-testid="unread-notifications-badge"
					class="absolute -top-0.5 -right-0.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-emerald-600 px-1 text-[10px] font-bold text-white"
				>
					{consoleState.unreadNotificationsCount}
				</span>
			{/if}
		</button>

		<button
			type="button"
			onclick={() => (isHelpModalOpen = !isHelpModalOpen)}
			aria-label="Abrir documentação e ajuda da plataforma"
			title="Ajuda e Contratos"
			class="hidden rounded-lg p-2 text-slate-600 transition hover:bg-slate-100 hover:text-slate-900 sm:inline-flex"
		>
			<CircleHelp class="h-4 w-4" aria-hidden="true" />
		</button>

		<div class="relative ml-1">
			<button
				type="button"
				onclick={toggleProfileMenu}
				aria-expanded={isProfileMenuOpen}
				aria-haspopup="menu"
				aria-label="Menu de perfil da conta autenticada ({consoleState.userContext?.displayName?.charAt(
					0
				) ?? 'S'})"
				data-testid="profile-menu-trigger"
				class="flex items-center gap-1.5 rounded-full border border-slate-200 bg-slate-50 py-1 pr-2 pl-1 text-xs font-medium text-slate-800 transition hover:border-emerald-300 hover:bg-white"
			>
				<span
					aria-hidden="true"
					class="flex h-6 w-6 items-center justify-center rounded-full bg-emerald-700 text-[11px] font-bold text-white"
				>
					{consoleState.userContext?.displayName?.charAt(0) ?? 'S'}
				</span>
				<ChevronDown class="h-3.5 w-3.5 text-slate-500" aria-hidden="true" />
			</button>

			{#if isProfileMenuOpen}
				<div class="fixed inset-0 z-40" aria-hidden="true" onclick={closeProfileMenu}></div>
				<div
					role="menu"
					aria-label="Detalhes da conta autenticada"
					class="absolute right-0 z-50 mt-2 w-72 rounded-xl border border-slate-200 bg-white p-3.5 shadow-xl"
				>
					<div class="flex items-center gap-2.5 border-b border-slate-100 pb-3">
						<div
							class="flex h-9 w-9 items-center justify-center rounded-full bg-emerald-100 text-emerald-800"
						>
							<User class="h-4 w-4" aria-hidden="true" />
						</div>
						<div class="min-w-0">
							<p class="truncate text-xs font-semibold text-slate-900">
								{consoleState.userContext?.displayName ?? 'Conta Smarkee'}
							</p>
							<p class="truncate font-mono text-[11px] text-slate-500">
								{consoleState.userContext?.emailMasked ?? '—'}
							</p>
						</div>
					</div>

					<div class="mt-2.5 space-y-1.5 text-[11px] text-slate-600">
						<div class="flex items-center justify-between">
							<span class="text-slate-500">Recurso:</span>
							<span class="font-mono font-medium text-slate-800">core.account</span>
						</div>
						<div class="flex items-center justify-between">
							<span class="text-slate-500">Provedor OIDC:</span>
							<span class="inline-flex items-center gap-1 font-medium text-emerald-700">
								<ShieldCheck class="h-3 w-3" aria-hidden="true" />
								PKCE Público
							</span>
						</div>
						<div class="flex items-center justify-between">
							<span class="text-slate-500">Roles ativas no token:</span>
							<span class="font-semibold text-slate-800">
								{consoleState.userContext?.roles.length ?? 0}
							</span>
						</div>
					</div>

					<div class="mt-3 flex flex-col gap-1 border-t border-slate-100 pt-2.5 text-xs">
						<a
							href="/identity/accounts"
							onclick={closeProfileMenu}
							class="rounded-lg px-2.5 py-1.5 font-medium text-slate-700 hover:bg-slate-100"
						>
							Ver detalhes da Account
						</a>
						<a
							href="/settings"
							onclick={closeProfileMenu}
							class="rounded-lg px-2.5 py-1.5 font-medium text-slate-700 hover:bg-slate-100"
						>
							Configurações de sessão OIDC
						</a>
					</div>
				</div>
			{/if}
		</div>
	</div>
</header>

{#if isHelpModalOpen}
	<div
		class="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/40 p-4"
		role="dialog"
		aria-modal="true"
		aria-label="Ajuda e Arquitetura do Smarkee Console"
	>
		<div class="w-full max-w-lg rounded-2xl border border-slate-200 bg-white p-5 shadow-2xl">
			<div class="flex items-center justify-between border-b border-slate-100 pb-3">
				<div class="flex items-center gap-2">
					<Activity class="h-4 w-4 text-emerald-600" aria-hidden="true" />
					<h2 class="text-sm font-bold text-slate-900">Sobre o Smarkee Console</h2>
				</div>
				<button
					type="button"
					onclick={() => (isHelpModalOpen = false)}
					aria-label="Fechar janela de ajuda"
					class="rounded-lg px-2 py-1 text-xs font-medium text-slate-500 hover:bg-slate-100"
				>
					Fechar
				</button>
			</div>
			<div class="mt-3 space-y-2.5 text-xs leading-relaxed text-slate-600">
				<p>
					O <strong>Smarkee Console</strong> opera sobre o loop de controle assíncrono da plataforma
					(<code>desired</code> vs. <code>observed</code>). Toda escrita retorna
					<code>202 Accepted</code> com <code>operationId</code> e <code>resourceId</code>.
				</p>
				<p>
					A autorização é sempre validada nos <strong>Receivers</strong> do backend via token JWT
					OIDC (aplicação <code>console</code> no projeto <code>clients</code> do Zitadel).
				</p>
				<p>
					Módulos sinalizados com <strong>Preview / Demonstrativo</strong> (como <code>AEM</code> e
					<code>ODM</code>) apresentam a visão planejada sem simular falsa persistência no backend.
				</p>
			</div>
		</div>
	</div>
{/if}
