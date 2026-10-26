/**
 * Adaptador de acompanhamento de operações assíncronas (OperationWatcher).
 * Conforme docs/console/CONSOLE.md §8:
 * - Desacoplado da tecnologia de transporte.
 * - Deduplica eventos por operationId e updatedAt/operationStatus.
 * - Suporta polling com backoff sobre ConsoleDataAdapter.
 */

import { validateIdentifier, type Operation } from '../types/common';
import type { ConsoleDataAdapter } from './adapter';

export type OperationUpdateListener = (operation: Operation) => void;

export interface OperationWatcherOptions {
	initialIntervalMs?: number;
	maxIntervalMs?: number;
}

export class OperationWatcher {
	private readonly adapter: ConsoleDataAdapter;
	private readonly initialIntervalMs: number;
	private readonly maxIntervalMs: number;
	private readonly listeners = new Set<OperationUpdateListener>();
	private readonly activeTimers = new Map<string, ReturnType<typeof setTimeout>>();
	private readonly seenFingerprints = new Map<string, string>();

	constructor(adapter: ConsoleDataAdapter, options: OperationWatcherOptions = {}) {
		this.adapter = adapter;
		this.initialIntervalMs = options.initialIntervalMs ?? 600;
		this.maxIntervalMs = options.maxIntervalMs ?? 4000;
	}

	/**
	 * Registra um ouvinte para atualizações deduplicadas de Operation.
	 */
	subscribe(listener: OperationUpdateListener): () => void {
		this.listeners.add(listener);
		return () => {
			this.listeners.delete(listener);
		};
	}

	/**
	 * Inicia o acompanhamento de uma operação pelo operationId até atingir estado terminal.
	 */
	watch(operationId: string): void {
		const validId = validateIdentifier(operationId, 'operationId');
		if (this.activeTimers.has(validId)) {
			return;
		}
		this.schedulePoll(validId, this.initialIntervalMs);
	}

	/**
	 * Cancela o acompanhamento de uma operação específica.
	 */
	unwatch(operationId: string): void {
		const timer = this.activeTimers.get(operationId);
		if (timer) {
			clearTimeout(timer);
			this.activeTimers.delete(operationId);
		}
	}

	/**
	 * Encerra todos os acompanhamentos ativos.
	 */
	dispose(): void {
		for (const timer of this.activeTimers.values()) {
			clearTimeout(timer);
		}
		this.activeTimers.clear();
		this.listeners.clear();
	}

	private schedulePoll(operationId: string, delayMs: number): void {
		const timer = setTimeout(async () => {
			try {
				const operation = await this.adapter.getOperation(operationId);
				if (!operation) {
					this.activeTimers.delete(operationId);
					return;
				}

				const fingerprint = `${operation.operationStatus}:${operation.updatedAt}:${operation.completedAt ?? ''}`;
				if (this.seenFingerprints.get(operationId) !== fingerprint) {
					this.seenFingerprints.set(operationId, fingerprint);
					for (const listener of this.listeners) {
						listener(operation);
					}
				}

				const isTerminal =
					operation.operationStatus === 'completed' ||
					operation.operationStatus === 'failed' ||
					operation.operationStatus === 'rejected' ||
					operation.operationStatus === 'superseded';

				if (isTerminal) {
					this.activeTimers.delete(operationId);
				} else {
					const nextDelay = Math.min(Math.round(delayMs * 1.35), this.maxIntervalMs);
					this.schedulePoll(operationId, nextDelay);
				}
			} catch {
				this.activeTimers.delete(operationId);
			}
		}, delayMs);

		this.activeTimers.set(operationId, timer);
	}
}
