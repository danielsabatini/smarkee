/**
 * Testes de contrato (JSON Schema) do Smarkee Console contra os schemas oficiais em ../../schemas/.
 * Garante matematicamente que todos os payloads do MockDataAdapter obedecem aos contratos reais.
 */

import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import Ajv2020 from 'ajv/dist/2020';
import addFormats from 'ajv-formats';
import { describe, expect, it } from 'vitest';
import { MockDataAdapter } from '../../src/lib/services/mock-adapter';

const currentDir = path.dirname(fileURLToPath(import.meta.url));
const schemasRoot = path.resolve(currentDir, '../../../../schemas');

function createValidator(): Ajv2020 {
	const ajv = new Ajv2020({
		strict: false,
		allErrors: true
	});
	addFormats(ajv);

	const schemaFiles = [
		'common/definitions.v1.schema.json',
		'common/condition.v1.schema.json',
		'common/operation.v1.schema.json',
		'common/api-accepted-response.v1.schema.json',
		'core/account/definitions.v1.schema.json',
		'core/account/desired.v1.schema.json',
		'core/account/observed.v1.schema.json',
		'core/account/resource.v1.schema.json',
		'ipm/definitions.v1.schema.json',
		'ipm/organization/definitions.v1.schema.json',
		'ipm/organization/desired.v1.schema.json',
		'ipm/organization/observed.v1.schema.json',
		'ipm/organization/resource.v1.schema.json',
		'ipm/organization/resource-list.v1.schema.json',
		'ipm/user/definitions.v1.schema.json',
		'ipm/user/desired.v1.schema.json',
		'ipm/user/observed.v1.schema.json',
		'ipm/user/resource.v1.schema.json',
		'ipm/user/resource-list.v1.schema.json',
		'sum/service/definitions.v1.schema.json',
		'sum/service/desired.v1.schema.json',
		'sum/service/observed.v1.schema.json',
		'sum/service/resource.v1.schema.json',
		'sum/service/api-list-response.v1.schema.json'
	];

	for (const relPath of schemaFiles) {
		const fullPath = path.join(schemasRoot, relPath);
		const raw = JSON.parse(fs.readFileSync(fullPath, 'utf-8'));
		const schemaUri = `https://smarkee.internal/schemas/${relPath}`;
		ajv.addSchema({ ...raw, $id: schemaUri }, schemaUri);
	}

	return ajv;
}

describe('Contratos JSON Schema (schemas/) vs MockDataAdapter', () => {
	const ajv = createValidator();
	const adapter = new MockDataAdapter({ transitionDelayMs: 50 });

	it('valida AccountResource contra core/account/resource.v1.schema.json', async () => {
		const ctx = await adapter.getUserContext();
		const account = await adapter.getAccount(ctx.accountId);
		const validate = ajv.getSchema(
			'https://smarkee.internal/schemas/core/account/resource.v1.schema.json'
		);
		expect(validate).toBeDefined();
		const valid = validate!(account);
		expect(validate?.errors).toBeNull();
		expect(valid).toBe(true);
	});

	it('valida todas as OrganizationResource contra ipm/organization/resource.v1.schema.json', async () => {
		const organizations = await adapter.listOrganizations();
		expect(organizations.length).toBeGreaterThanOrEqual(3);

		const validateResource = ajv.getSchema(
			'https://smarkee.internal/schemas/ipm/organization/resource.v1.schema.json'
		);
		const validateList = ajv.getSchema(
			'https://smarkee.internal/schemas/ipm/organization/resource-list.v1.schema.json'
		);

		for (const org of organizations) {
			const valid = validateResource!(org);
			expect(validateResource?.errors).toBeNull();
			expect(valid).toBe(true);
		}

		expect(validateList!({ items: organizations })).toBe(true);
	});

	it('valida todos os OrganizationUserResource contra ipm/user/resource.v1.schema.json', async () => {
		const organizations = await adapter.listOrganizations();
		const validateUser = ajv.getSchema(
			'https://smarkee.internal/schemas/ipm/user/resource.v1.schema.json'
		);
		const validateUserList = ajv.getSchema(
			'https://smarkee.internal/schemas/ipm/user/resource-list.v1.schema.json'
		);

		for (const org of organizations) {
			const users = await adapter.listUsers(org.resourceId);
			for (const user of users) {
				const valid = validateUser!(user);
				expect(validateUser?.errors).toBeNull();
				expect(valid).toBe(true);
			}
			expect(validateUserList!({ items: users })).toBe(true);
		}
	});

	it('valida todos os ServiceLinkResource contra sum/service/resource.v1.schema.json', async () => {
		const services = await adapter.listServices();
		expect(services.length).toBeGreaterThanOrEqual(1);

		const validateService = ajv.getSchema(
			'https://smarkee.internal/schemas/sum/service/resource.v1.schema.json'
		);
		const validateList = ajv.getSchema(
			'https://smarkee.internal/schemas/sum/service/api-list-response.v1.schema.json'
		);

		for (const svc of services) {
			const valid = validateService!(svc);
			expect(validateService?.errors).toBeNull();
			expect(valid).toBe(true);
		}
		expect(validateList!({ items: services })).toBe(true);
	});

	it('valida todas as Operation (accepted, in_progress, completed, failed, rejected) contra common/operation.v1.schema.json', async () => {
		const ops = await adapter.listOperations();
		expect(ops.length).toBeGreaterThanOrEqual(4);

		const validateOp = ajv.getSchema(
			'https://smarkee.internal/schemas/common/operation.v1.schema.json'
		);

		for (const item of ops) {
			const valid = validateOp!(item.operation);
			expect(validateOp?.errors).toBeNull();
			expect(valid).toBe(true);
		}
	});

	it('valida respostas 202 Accepted (RequestAccepted) contra common/api-accepted-response.v1.schema.json', async () => {
		const accepted = await adapter.createOrganization({
			name: 'stark-industries',
			deletionProtection: true
		});

		const validateAccepted = ajv.getSchema(
			'https://smarkee.internal/schemas/common/api-accepted-response.v1.schema.json'
		);
		expect(validateAccepted!(accepted)).toBe(true);

		const op = await adapter.getOperation(accepted.operationId);
		const validateOp = ajv.getSchema(
			'https://smarkee.internal/schemas/common/operation.v1.schema.json'
		);
		expect(validateOp!(op)).toBe(true);
	});
});
