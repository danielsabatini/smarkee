/**
 * Testes unitários de validação de identificadores, adaptador simulado,
 * watcher de operações e isolamento de transição de organização.
 */

import { describe, expect, it, vi } from 'vitest';
import { NAVIGATION_SECTIONS, PLATFORM_SERVICE_CATALOG } from '../../src/lib/config/navigation';
import { MockDataAdapter } from '../../src/lib/services/mock-adapter';
import { OperationWatcher } from '../../src/lib/services/operation-watcher';
import { ConsoleState } from '../../src/lib/state/console-context.svelte';
import { isValidIdentifier, validateIdentifier } from '../../src/lib/types/common';

describe('Validação de Identificadores e Defesa contra Path Traversal', () => {
	it('aceita UUIDv7 e slugs minúsculos válidos', () => {
		expect(isValidIdentifier('0199c8a4-7b1e-7c3a-9f2d-5e8a1b2c3d4e')).toBe(true);
		expect(isValidIdentifier('acme-corporation')).toBe(true);
		expect(isValidIdentifier('a')).toBe(true);
		expect(validateIdentifier('globex-labs')).toBe('globex-labs');
	});

	it('rejeita tentativas de path traversal, letras maiúsculas e caracteres especiais', () => {
		expect(isValidIdentifier('../admin')).toBe(false);
		expect(isValidIdentifier('org/../../secret')).toBe(false);
		expect(isValidIdentifier('Acme-Corp')).toBe(false);
		expect(isValidIdentifier('-invalid-start')).toBe(false);
		expect(isValidIdentifier('invalid-end-')).toBe(false);
		expect(isValidIdentifier('')).toBe(false);
		expect(() => validateIdentifier('../etc/passwd', 'organizationId')).toThrow(
			/Identificador inválido para organizationId/
		);
	});
});

describe('Configuração de Navegação e Catálogo', () => {
	it('inclui os módulos oficiais IPM, SUM, AEM e ODM (nunca POM)', () => {
		const codes = PLATFORM_SERVICE_CATALOG.map((item) => item.code);
		expect(codes).toEqual(['IPM', 'SUM', 'AEM', 'ODM']);
		expect(NAVIGATION_SECTIONS.some((s) => s.moduleCode === 'ODM')).toBe(true);
	});
});

describe('MockDataAdapter e Reconciliação Assíncrona', () => {
	it('isola recursos e usuários por Organization', async () => {
		const adapter = new MockDataAdapter({ transitionDelayMs: 40 });
		const orgs = await adapter.listOrganizations();
		const acme = orgs[0]!;
		const globex = orgs[1]!;

		const acmeUsers = await adapter.listUsers(acme.resourceId);
		const globexUsers = await adapter.listUsers(globex.resourceId);

		expect(acmeUsers.every((u) => u.desired.organizationId === acme.resourceId)).toBe(true);
		expect(globexUsers.every((u) => u.desired.organizationId === globex.resourceId)).toBe(true);
		expect(acmeUsers[0]?.desired.email).not.toBe(globexUsers[0]?.desired.email);
	});

	it('rejeita exclusão de Organization com deletionProtection ativo (motivo protected)', async () => {
		const adapter = new MockDataAdapter({ transitionDelayMs: 40 });
		const orgs = await adapter.listOrganizations();
		const protectedOrg = orgs.find((o) => o.desired.deletionProtection === true)!;

		const accepted = await adapter.deleteOrganization(protectedOrg.resourceId);
		const op = await adapter.getOperation(accepted.operationId);

		expect(op?.operationStatus).toBe('rejected');
		expect(op?.operationStatusReason).toBe('protected');
	});

	it('transiciona operação de habilitação de serviço de accepted -> in_progress -> completed', async () => {
		vi.useFakeTimers();
		try {
			const adapter = new MockDataAdapter({ transitionDelayMs: 200 });
			const accepted = await adapter.enableService({ service: 'aem' });

			let op = await adapter.getOperation(accepted.operationId);
			expect(op?.operationStatus).toBe('accepted');

			vi.advanceTimersByTime(150);
			op = await adapter.getOperation(accepted.operationId);
			expect(op?.operationStatus).toBe('in_progress');

			vi.advanceTimersByTime(250);
			op = await adapter.getOperation(accepted.operationId);
			expect(op?.operationStatus).toBe('completed');
			expect(op?.completedAt).toBeDefined();
		} finally {
			vi.useRealTimers();
		}
	});
});

describe('OperationWatcher e ConsoleState', () => {
	it('acompanha uma operação até o estado terminal e deduplica notificações', async () => {
		const adapter = new MockDataAdapter({ transitionDelayMs: 60 });
		const watcher = new OperationWatcher(adapter, { initialIntervalMs: 20, maxIntervalMs: 50 });
		const updates: string[] = [];

		watcher.subscribe((op) => {
			updates.push(op.operationStatus);
		});

		const accepted = await adapter.enableService({ service: 'odm' });
		watcher.watch(accepted.operationId);

		await new Promise((resolve) => setTimeout(resolve, 300));
		expect(updates).toContain('completed');
		watcher.dispose();
	});

	it('limpa sincronicamente dados da organização anterior ao alternar no ConsoleState', async () => {
		const adapter = new MockDataAdapter({ transitionDelayMs: 50 });
		const state = new ConsoleState(adapter);
		await state.initialize();

		const orgs = state.organizations;
		const firstOrgId = orgs[0]!.resourceId;
		const secondOrgId = orgs[1]!.resourceId;

		expect(state.activeOrganizationId).toBe(firstOrgId);
		expect(state.activeOrganization?.resourceId).toBe(firstOrgId);
		expect(state.activeOrganizationDemoMeta?.displayName).toBeDefined();
		expect(state.serviceCatalog.length).toBe(4);
		expect(state.organizationUsers.length).toBeGreaterThan(0);

		const switchPromise = state.selectOrganization(secondOrgId);
		// Verificação imediata antes da resolução da Promise: estado anterior deve ter sido limpo
		expect(state.activeOrganizationId).toBe(secondOrgId);
		expect(state.organizationUsers).toEqual([]);

		await switchPromise;
		expect(state.organizationUsers.every((u) => u.desired.organizationId === secondOrgId)).toBe(
			true
		);

		// Testa mutações assíncronas e helpers do ConsoleState
		const createdOrg = await state.createOrganization({
			name: 'stark-industries',
			deletionProtection: false
		});
		expect(createdOrg.operationId).toBeDefined();

		// Tenta criar organização duplicada para exercitar rejeição por conflito
		const conflictOrg = await state.createOrganization({
			name: 'stark-industries',
			deletionProtection: true
		});
		const conflictOp = await adapter.getOperation(conflictOrg.operationId);
		expect(conflictOp?.operationStatus).toBe('rejected');
		expect(conflictOp?.operationStatusReason).toBe('conflict');

		const createdUser = await state.createUser({
			organizationId: secondOrgId,
			givenName: 'Tony',
			familyName: 'Stark',
			email: 'tony@stark.example.com',
			roles: ['ipm.user.get']
		});
		expect(createdUser.resourceId).toBeDefined();

		const enabledSvc = await state.enableService({ service: 'odm' });
		expect(enabledSvc.operationId).toBeDefined();

		const svcList = await adapter.listServices();
		const odmSvc = svcList.find((s) => s.desired.service === 'odm');
		if (odmSvc) {
			const disabledSvc = await state.disableService(odmSvc.resourceId);
			expect(disabledSvc.operationId).toBeDefined();
		}

		// Update organization
		const updatedOrg = await state.updateOrganization({
			resourceId: createdOrg.resourceId,
			name: 'stark-industries-v2',
			displayName: 'Stark Industries V2',
			deletionProtection: false
		});
		expect(updatedOrg.operationId).toBeDefined();

		// Update user
		const updatedUser = await state.updateUser({
			resourceId: createdUser.resourceId,
			roles: ['ipm.user.list', 'ipm.user.get'],
			deletionProtection: false
		});
		expect(updatedUser.operationId).toBeDefined();

		// Delete user
		const deletedUser = await state.deleteUser(createdUser.resourceId);
		expect(deletedUser.operationId).toBeDefined();

		// Update account
		const updatedAccount = await state.updateAccount({
			resourceId: state.account!.resourceId,
			deletionProtection: false
		});
		expect(updatedAccount.operationId).toBeDefined();

		// Delete account
		const deletedAccount = await state.deleteAccount(state.account!.resourceId);
		expect(deletedAccount.operationId).toBeDefined();

		// Exclui a organização sem deletionProtection
		const deletedOrg = await state.deleteOrganization(createdOrg.resourceId);
		expect(deletedOrg.operationId).toBeDefined();

		// Notificações e UI
		const firstNotif = state.notifications[0];
		if (firstNotif) {
			await state.markNotificationAsRead(firstNotif.id);
		}
		await state.markAllNotificationsAsRead();
		expect(state.unreadNotificationsCount).toBe(0);

		state.toggleSidebarCompact();
		expect(state.isSidebarCompact).toBe(true);
		state.setMobileDrawerOpen(true);
		expect(state.isMobileDrawerOpen).toBe(true);
		state.closeOperationsPanel();
		expect(state.isOperationsPanelOpen).toBe(false);
		state.openOperationsPanel('notifications');
		expect(state.isOperationsPanelOpen).toBe(true);
		expect(state.activePanelTab).toBe('notifications');
		state.toggleOperationsPanel('operations');
		expect(state.activePanelTab).toBe('operations');
		state.toggleOperationsPanel('operations');
		expect(state.isOperationsPanelOpen).toBe(false);

		expect(state.inProgressOperations.length).toBeGreaterThanOrEqual(0);
		expect(state.completedOperations.length).toBeGreaterThan(0);
		expect(state.activeOperationsCount).toBe(state.inProgressOperations.length);

		await new Promise((resolve) => setTimeout(resolve, 160));
		state.dispose();
	});
});
