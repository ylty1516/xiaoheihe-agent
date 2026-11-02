import { AsyncLocalStorage } from 'node:async_hooks';
import { channel } from 'node:diagnostics_channel';




// Scope Node's HTTP diagnostics to this SDK execution, including its async callbacks.
// No request URL, fingerprint body, headers or response body is retained.
export function observeTokenNetwork(record                                       ,
  timing                    , connectTimeoutMs = 3000, requestTimeoutMs = 5000) {
  const scope = new AsyncLocalStorage         ();
  const created = channel('http.client.request.created');
  const requests = new Set               ();
  const cleanups = new Set            ();
  const observe = (value         ) => {
    const { request } = value                              ;
    if (!scope.getStore() || request.protocol !== 'https:' || request.method !== 'POST'
      || request.getHeader('host') !== 'fp-it.portal101.cn' || request.path !== '/deviceprofile/v4') return;
    requests.add(request);
    let phase                                     = 'dns';
    let started = performance.now();
    const next = (stage                                  , nextPhase                                    ) => {
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
    request.once('socket', (socket           ) => {
      if (request.reusedSocket) { phase = 'response'; clearTimeout(timer); return; }
      socket.once('lookup', () => next('token_dns', 'tcp'));
      socket.once('connect', () => next('token_tcp', 'tls'));
      socket.once('secureConnect', () => { next('token_tls', 'response'); clearTimeout(timer); });
    });
    // This listener is installed before jsdom's error listener invokes the SDK callback.
    request.once('error', (error                       ) => {
      if (phase && phase !== 'response') timing?.(`token_${phase}`, performance.now() - started);
      record({ networkCode: error.code, networkPhase: phase });
    });
    request.once('response', () => clearTimeout(timer));
    request.once('close', cleanup);
  };
  created.subscribe(observe);
  return {
    run   (callback         )    { return scope.run(true, callback); },
    close() {
      created.unsubscribe(observe); scope.disable();
      const pending = [...requests];
      for (const cleanup of cleanups) cleanup();
      for (const request of pending) request.destroy();
    },
  };
}
