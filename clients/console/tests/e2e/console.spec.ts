import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';

test.describe('Smarkee Console — E2E & WCAG AA', () => {
	test('renderiza o Dashboard principal com os módulos IPM, SUM, AEM e ODM e passa na auditoria WCAG AA', async ({
		page
	}) => {
		await page.goto('/');

		await expect(page.getByRole('heading', { name: 'Bem-vindo à Smarkee' })).toBeVisible();
		await expect(page.getByTestId('organization-summary-card')).toBeVisible();
		await expect(page.getByTestId('summary-organization-title')).toContainText('Acme Corp');

		// Confere os 4 cards dos módulos da plataforma (IPM, SUM, AEM, ODM — nunca POM)
		await expect(page.getByTestId('service-card-IPM')).toBeVisible();
		await expect(page.getByTestId('service-card-SUM')).toBeVisible();
		await expect(page.getByTestId('service-card-AEM')).toBeVisible();
		await expect(page.getByTestId('service-card-ODM')).toBeVisible();

		// Auditoria de acessibilidade automatizada WCAG 2.0/2.1 AA
		const accessibilityScanResults = await new AxeBuilder({ page })
			.withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
			.analyze();

		expect(accessibilityScanResults.violations).toEqual([]);
	});

	test('alterna de Organization no seletor do cabeçalho e atualiza o contexto sem vazar dados anteriores', async ({
		page
	}) => {
		await page.goto('/');

		await expect(page.getByTestId('summary-organization-title')).toContainText('Acme Corp');
		await expect(
			page.getByTestId('recent-resource-row-0199c8a4-8a01-7b01-9c01-1a2b3c4d5e01')
		).toBeVisible();

		// Abre o seletor de Organization e seleciona Globex Labs
		await page.getByTestId('organization-selector-trigger').click();
		await expect(page.getByTestId('organization-selector-popover')).toBeVisible();
		await page.getByTestId('org-option-globex-labs').click();

		// Verifica se o resumo e a tabela de recursos recentes refletem Globex Labs
		await expect(page.getByTestId('summary-organization-title')).toContainText('Globex Labs');
		await expect(
			page.getByTestId('recent-resource-row-0199c8a4-8a02-7b02-9c02-1a2b3c4d5e02')
		).toBeVisible();
		await expect(
			page.getByTestId('recent-resource-row-0199c8a4-8a01-7b01-9c01-1a2b3c4d5e01')
		).toHaveCount(0);
	});

	test('alterna o menu lateral entre modo expandido e compacto no desktop e abre a busca global (⌘K)', async ({
		page
	}) => {
		await page.setViewportSize({ width: 1440, height: 900 });
		await page.goto('/');

		const sidebar = page.getByTestId('desktop-sidebar');
		await expect(sidebar).toHaveAttribute('data-compact', 'false');

		await page.getByTestId('sidebar-compact-toggle').click();
		await expect(sidebar).toHaveAttribute('data-compact', 'true');

		await page.getByTestId('sidebar-compact-toggle').click();
		await expect(sidebar).toHaveAttribute('data-compact', 'false');

		// Abre a busca global e filtra por ODM
		await page.getByTestId('global-search-trigger').click();
		const searchDialog = page.getByTestId('global-search-dialog');
		await expect(searchDialog).toBeVisible();
		await page.getByTestId('global-search-input').fill('ODM');
		await expect(searchDialog.getByText('Observability Data Manager (ODM)')).toBeVisible();
		await page.keyboard.press('Escape');
		await expect(searchDialog).toHaveCount(0);
	});

	test('em viewport mobile recolhe a sidebar em drawer acessível e fecha com Escape', async ({
		page
	}) => {
		await page.setViewportSize({ width: 390, height: 844 });
		await page.goto('/');
		await page.waitForLoadState('networkidle');

		await expect(page.getByTestId('mobile-sidebar-drawer')).toHaveCount(0);
		await page.getByTestId('sidebar-toggle-button').click();
		await expect(page.getByTestId('mobile-sidebar-drawer')).toBeVisible();

		await page.keyboard.press('Escape');
		await expect(page.getByTestId('mobile-sidebar-drawer')).toHaveCount(0);
	});

	test('executa fluxo 202 Accepted de criação de Organization e acompanha reconciliação até completed / Ready', async ({
		page
	}) => {
		await page.goto('/identity/organizations');
		await page.waitForLoadState('networkidle');
		await expect(page.getByRole('heading', { name: 'Nova Organização' })).toBeVisible();

		await page.getByTestId('create-org-name-input').fill('wayne-enterprises');
		await expect(page.getByTestId('create-org-slug-input')).toHaveValue('wayne-enterprises');
		await page.getByTestId('create-org-submit-button').click();

		// Painel de operações exibe a operação assíncrona e converge para Ready
		await expect(page.getByTestId('operations-panel')).toBeVisible();
		const newRow = page.getByTestId('organization-table-row-wayne-enterprises');
		await expect(newRow).toBeVisible();
		await expect(newRow).toContainText('Ready', { timeout: 6000 });

		// Auditoria WCAG AA na página de Organizações
		const accessibilityScanResults = await new AxeBuilder({ page })
			.withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa'])
			.analyze();
		expect(accessibilityScanResults.violations).toEqual([]);
	});

	test('gerencia notificações na aba Central de Notificações do painel direito', async ({
		page
	}) => {
		await page.goto('/');
		await page.waitForLoadState('networkidle');
		await expect(page.getByRole('heading', { name: 'Bem-vindo à Smarkee' })).toBeVisible();

		await page.getByTestId('header-notifications-button').click();
		await expect(page.getByTestId('tab-notifications')).toHaveAttribute('aria-selected', 'true');
		await expect(page.getByTestId('mark-all-notifications-read')).toBeVisible();

		await page.getByTestId('mark-all-notifications-read').click();
		await expect(page.getByTestId('unread-notifications-badge')).toHaveCount(0);
	});
});
