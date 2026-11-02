import { AsyncLocalStorage } from 'node:async_hooks';
import { channel } from 'node:diagnostics_channel';
import type { ClientRequest } from 'node:http';
import type { TLSSocket } from 'node:tls';
import type { DeviceTokenDetails, DeviceTokenTiming } from './device-token.js';

// Scope Node's HTTP diagnostics to this SDK execution, including its async callbacks.
// No request URL, fingerprint body, headers or response body is retained.
export function observeTokenNetwork(record: (details: DeviceTokenDetails) => void,
  timing?: DeviceTokenTiming, connectTimeoutMs = 3000, requestTimeoutMs = 5000) {
  const scope = new AsyncLocalStorage<boolean>();
  const created = channel('http.client.request.created');
  const requests = new Set<ClientRequest>();
  const cleanups = new Set<() => void>();
  const observe = (value: unknown) => {
    const { request } = value as { request: ClientRequest };
    if (!scope.getStore() || request.protocol !== 'https:' || request.method !== 'POST'
      || request.getHeader('host') !== 'fp-it.portal101.cn' || request.path !== '/deviceprofile/v4') return;
    requests.add(request);
    let phase: DeviceTokenDetails['networkPhase'] = 'dns';
    let started = performance.now();
    const next = (stage: Parameters<DeviceTokenTiming>[0], nextPhase: DeviceTokenDetails['networkPhase']) => {
      const now = performance.now(); timing?.(stage, now - started); started = now; phase = nextPhase;
    };
    const timeout = () => {
      const error = Object.assign(new Error('设备令牌请求超时'), { code: 'ETIMEDOUT' });
      request.destroy(error);
    };
    const timer = setTimeout(timeout, connectTimeoutMs);
    const responseTimer = setTimeout(timeout, requestTimeoutMs);
    const cleanup = () => { clearTimeout(timer); clearTimeout(responseTimer); cleanups.delete(cleanup); requests.delete(request); };
    cleanups.add(cleanup);
    request.once('socket', (socket: TLSSocket) => {
      if (request.reusedSocket) { phase = 'response'; clearTimeout(timer); return; }
      socket.once('lookup', () => next('token_dns', 'tcp'));
      socket.once('connect', () => next('token_tcp', 'tls'));
      socket.once('secureConnect', () => { next('token_tls', 'response'); clearTimeout(timer); });
    });
    // This listener is installed before jsdom's error listener invokes the SDK callback.
    request.once('error', (error: NodeJS.ErrnoException) => {
      if (phase && phase !== 'response') timing?.(`token_${phase}`, performance.now() - started);
      record({ networkCode: error.code, networkPhase: phase });
    });
    request.once('response', () => clearTimeout(timer));
    request.once('close', cleanup);
  };
  created.subscribe(observe);
  return {
    run<T>(callback: () => T): T { return scope.run(true, callback); },
    close() {
      created.unsubscribe(observe); scope.disable();
      const pending = [...requests];
      for (const cleanup of cleanups) cleanup();
      for (const request of pending) request.destroy();
    },
  };
}
