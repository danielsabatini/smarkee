import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { svelteTesting } from '@testing-library/svelte/vite';
import { defineConfig } from 'vitest/config';

export default defineConfig({
	plugins: [tailwindcss(), sveltekit(), svelteTesting()],
	test: {
		include: ['tests/unit/**/*.test.ts'],
		environment: 'jsdom',
		globals: true,
		coverage: {
			provider: 'v8',
			reporter: ['text', 'lcov', 'json-summary'],
			include: [
				'src/lib/services/**/*.ts',
				'src/lib/config/**/*.ts',
				'src/lib/state/**/*.svelte.ts'
			],
			thresholds: {
				lines: 80,
				functions: 80,
				statements: 80
			}
		}
	}
});
