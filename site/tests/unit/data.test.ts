import { describe, expect, it } from 'vitest';
import { BLOG_POSTS } from '../../src/lib/data/blog';
import { MAIN_NAV, PILLARS, PLATFORM_MODULES } from '../../src/lib/data/platform';

describe('Smarkee IT Solutions — Contratos e Dados Institucionais', () => {
	it('valida os módulos centrais da plataforma (IPM, SUM, AEM, ODM)', () => {
		const moduleCodes = PLATFORM_MODULES.map((m) => m.code);
		expect(moduleCodes).toContain('IPM');
		expect(moduleCodes).toContain('SUM');
		expect(moduleCodes).toContain('AEM');
		expect(moduleCodes).toContain('ODM');
		expect(PLATFORM_MODULES.length).toBe(4);

		for (const mod of PLATFORM_MODULES) {
			expect(mod.name.length).toBeGreaterThan(0);
			expect(mod.tagline.length).toBeGreaterThan(0);
			expect(mod.description.length).toBeGreaterThan(0);
			expect(mod.highlights.length).toBeGreaterThanOrEqual(3);
		}
	});

	it('valida integridade de todos os posts de blog', () => {
		expect(BLOG_POSTS.length).toBeGreaterThanOrEqual(3);

		const slugs = new Set<string>();
		for (const post of BLOG_POSTS) {
			expect(slugs.has(post.slug)).toBe(false);
			slugs.add(post.slug);

			expect(post.title.length).toBeGreaterThan(5);
			expect(post.summary.length).toBeGreaterThan(10);
			expect(post.readTimeMinutes).toBeGreaterThan(0);
			expect(post.author.name.length).toBeGreaterThan(0);
			expect(post.content.length).toBeGreaterThan(50);
			expect(post.tags.length).toBeGreaterThan(0);
		}
	});

	it('valida a navegação principal e os pilares fundamentais', () => {
		expect(MAIN_NAV.length).toBeGreaterThanOrEqual(5);
		expect(PILLARS.length).toBe(4);

		for (const pillar of PILLARS) {
			expect(pillar.title.length).toBeGreaterThan(0);
			expect(pillar.description.length).toBeGreaterThan(0);
		}
	});
});
