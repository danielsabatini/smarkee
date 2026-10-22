/**
 * Testes unitários do componente CopyableId.
 */

import { render, screen, fireEvent } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import CopyableId from '../../src/lib/components/ui/CopyableId.svelte';

describe('Componente CopyableId', () => {
	it('renderiza o identificador e rótulo corretamente', () => {
		render(CopyableId, {
			id: '0199c8a4-8a01-7b01-9c01-1a2b3c4d5e01',
			label: 'ID:'
		});

		expect(screen.getByText('ID:')).toBeTruthy();
		expect(screen.getByText('0199c8a4-8a01-7b01-9c01-1a2b3c4d5e01')).toBeTruthy();
		expect(
			screen.getByRole('button', {
				name: /Copiar identificador 0199c8a4-8a01-7b01-9c01-1a2b3c4d5e01/i
			})
		).toBeTruthy();
	});

	it('copia o id para a área de transferência ao clicar no botão', async () => {
		const writeTextMock = vi.fn().mockResolvedValue(undefined);
		Object.assign(navigator, {
			clipboard: {
				writeText: writeTextMock
			}
		});

		render(CopyableId, {
			id: 'acme-org-id',
			testId: 'copy-btn'
		});

		const button = screen.getByTestId('copy-btn');
		await fireEvent.click(button);

		expect(writeTextMock).toHaveBeenCalledWith('acme-org-id');
	});
});
