export function formatResourceType(type: string): string {
	switch (type) {
		case 'organization':
		case 'ipm.organization':
			return 'Organização';
		case 'user':
		case 'ipm.user':
			return 'Usuário';
		case 'service':
		case 'sum.service':
			return 'Serviço';
		case 'account':
		case 'core.account':
			return 'Conta';
		default:
			return type;
	}
}

export function formatOperationAction(action: string): string {
	switch (action) {
		case 'create':
			return 'Criação';
		case 'update':
			return 'Atualização';
		case 'delete':
			return 'Exclusão';
		default:
			return action;
	}
}

export function formatOperationTag(resourceType: string, operationType: string): string {
	return `${formatResourceType(resourceType)} • ${formatOperationAction(operationType)}`;
}
