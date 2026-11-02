import { webSignature } from './signature.js';
import { nativeSignature } from './native.js';
import { encryptReport } from './report.js';
import type { Config, Query, ShareEvent, SignState, TaskClient, TaskListResult } from './types.js';

interface ClientOptions { fetchImpl?: typeof fetch; signer?: typeof nativeSignature }
interface WebOptions { host?: string; body?: URLSearchParams }
interface ApiResponse<T> { status?: string; msg?: string; result: T }

export class HeyboxRequestError extends Error {
  readonly endpoint: string;
  readonly category: 'network' | 'timeout' | 'http' | 'protocol' | 'auth';
  readonly httpStatus?: number;
  readonly retryAfterMs?: number;
  durationMs?: number;
  constructor(message: string, endpoint: string, category: HeyboxRequestError['category'], httpStatus?: number, retryAfterMs?: number, options?: ErrorOptions) {
    super(message, options); this.endpoint = endpoint; this.category = category;
    this.httpStatus = httpStatus; this.retryAfterMs = retryAfterMs;
  }
}

export function parseRetryAfter(value: string | null, now = Date.now()): number | undefined {
  if (!value?.trim()) return undefined;
  const delay = /^\d+$/.test(value.trim()) ? Number(value) * 1000 : Date.parse(value) - now;
  return Number.isFinite(delay) && delay >= 0 ? Math.min(Math.ceil(delay), 604800000) : undefined;
}

export class HeyboxApiError extends Error {
  readonly endpoint: string;
  readonly status: string;
  readonly upstreamMessage: string;
  readonly retryCode: boolean;
  readonly captchaRequired: boolean;
  readonly captchaAppId?: string;
  readonly rateLimited: boolean;
  retryAfterMs?: number;
  durationMs?: number;
  readonly httpStatus?: number;
  constructor(endpoint: string, status: string | undefined, detail = '', result?: unknown, httpStatus?: number) {
    const expired = /验证码.*(?:过期|失效)/.test(detail);
    const limited = /频繁|次数.*限制/.test(detail);
    const wrongCode = /验证码.*(?:错误|不正确)/.test(detail);
    const safeStatus = /^[a-z_]{1,32}$/.test(status ?? '') ? status : 'unknown';
    const captchaRequired = status === 'show_captcha';
    const reason = captchaRequired ? '小黑盒要求完成人机验证后才能继续登录' : expired ? '验证码已过期，请重新登录获取新的验证码' : limited ? '请求过于频繁，请稍后再试' : wrongCode ? '验证码不正确，请重新输入' : `接口未成功：${endpoint}（${safeStatus}）`;
    super(reason);
    this.endpoint = endpoint;
    this.httpStatus = httpStatus;
    this.status = safeStatus || 'unknown';
    this.upstreamMessage = detail;
    this.captchaRequired = captchaRequired;
    this.rateLimited = limited;
    const appId = result && typeof result === 'object' && 'appid' in result ? String(result.appid) : '';
    if (captchaRequired && /^\d{1,32}$/.test(appId)) this.captchaAppId = appId;
    this.retryCode = endpoint === '/account/login_code/' && status === 'failed' && !expired && !limited;
  }
}

export class HeyboxClient implements TaskClient {
  readonly config: Config;
  readonly fetch: typeof fetch;
  readonly signer: typeof nativeSignature;

  constructor(config: Config, { fetchImpl = fetch, signer = nativeSignature }: ClientOptions = {}) {
    this.config = config;
    this.fetch = fetchImpl;
    this.signer = signer;
  }

  async request<T>(host: string, endpoint: string, query: Query, headers: Record<string, string>, body?: URLSearchParams): Promise<T> {
    const started = performance.now();
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(new DOMException('The operation was aborted due to timeout', 'TimeoutError')), 20_000);
    try {
      let response: Response;
      try {
        response = await this.fetch(`https://${host}${endpoint}?${new URLSearchParams(query)}`, {
          method: body ? 'POST' : 'GET', headers, body,
          redirect: 'error', signal: controller.signal,
        });
      } catch (error) {
        throw new HeyboxRequestError(`请求失败或超时：${endpoint}`, endpoint,
          error instanceof Error && /TimeoutError|AbortError/.test(error.name) ? 'timeout' : 'network', undefined, undefined, { cause: error });
      }
      if (!response.ok) {
        await response.body?.cancel().catch(() => {});
        throw new HeyboxRequestError(`HTTP ${response.status}：${endpoint}`, endpoint, 'http', response.status, parseRetryAfter(response.headers.get('retry-after')));
      }
      let data: ApiResponse<T>;
      try { data = await response.json() as ApiResponse<T>; }
      catch { throw new HeyboxRequestError(`接口返回了非 JSON 内容：${endpoint}`, endpoint, controller.signal.aborted ? 'timeout' : 'protocol', response.status); }
      if (!data || typeof data !== 'object' || Array.isArray(data)) throw new HeyboxRequestError('Invalid upstream response', endpoint, 'protocol', response.status);
      if (data.status === 'relogin') throw new HeyboxRequestError('APP 登录已过期，请重新运行登录命令', endpoint, 'auth', response.status);
      if (data.status === 'lack_token') throw new HeyboxRequestError('设备令牌无效，请重新运行登录命令', endpoint, 'auth', response.status);
      // Only known error categories are displayed; raw replies may contain account data.
      if (data.status !== 'ok') {
        const error = new HeyboxApiError(endpoint, typeof data.status === 'string' ? data.status : undefined, typeof data.msg === 'string' ? data.msg : '', data.result, response.status);
        error.retryAfterMs = parseRetryAfter(response.headers.get('retry-after'));
        throw error;
      }
      return data.result;
    } catch (error) {
      if (error instanceof HeyboxRequestError || error instanceof HeyboxApiError) error.durationMs = Math.round(performance.now() - started);
      throw error;
    } finally { clearTimeout(timer); }
  }

  web<T = unknown>(endpoint: string, extra: Query = {}, { host = 'api.xiaoheihe.cn', body }: WebOptions = {}): Promise<T> {
    const { session, device, app } = this.config;
    const query = {
      app: 'heybox', os_type: 'web', x_app: 'heybox', x_client_type: 'web', x_os_type: 'Android',
      x_client_version: app.version, version: '999.0.4', heybox_id: session.heybox_id,
      ...extra, ...webSignature(endpoint),
    };
    const headers: Record<string, string> = {
      'User-Agent': `Mozilla/5.0 (Linux; Android ${device.osVersion}; ${device.model}; wv) AppleWebKit/537.36 (KHTML, like Gecko) Version/4.0 Chrome/143.0.7499.192 Mobile Safari/537.36`,
      Accept: 'application/json, text/plain, */*', Origin: 'https://web.xiaoheihe.cn',
      Referer: 'https://web.xiaoheihe.cn/', 'X-Requested-With': 'com.max.xiaoheihe',
      Cookie: `pkey=${session.pkey};x_xhh_tokenid=${session.x_xhh_tokenid};x_pkey=${session.pkey};x_heybox_id=${session.heybox_id}`,
    };
    if (body) headers['Content-Type'] = 'application/x-www-form-urlencoded;charset=UTF-8';
    return this.request<T>(host, endpoint, query, headers, body);
  }

  native<T>(endpoint: string, extra: Query = {}, body?: URLSearchParams): Promise<T> {
    const { session, device, app } = this.config;
    const headers: Record<string, string> = {
      'User-Agent': 'Mozilla/5.0 AppleWebKit/537.36 (KHTML, like Gecko) Chrome/41.0.2272.118 Safari/537.36 ApiMaxJia/1.0',
      Accept: 'application/json', Referer: 'http://api.maxjia.com/',
      Cookie: `pkey=${session.pkey}; x_xhh_tokenid=${session.x_xhh_tokenid}`,
    };
    if (body) headers['Content-Type'] = 'application/x-www-form-urlencoded';
    return this.request<T>('api.xiaoheihe.cn', endpoint, {
      heybox_id: session.heybox_id, imei: session.device_id, device_info: device.model,
      os_type: 'Android', x_os_type: 'Android', x_client_type: 'mobile', os_version: device.osVersion,
      version: app.version, build: app.build, dw: '360', channel: 'heybox', x_app: 'heybox', time_zone: 'Asia/Shanghai',
      ...extra, ...this.signer(endpoint, this.config),
    }, headers, body);
  }

  tasks() { return this.web<TaskListResult>('/task/list_v2/'); }
  signState() { return this.native<SignState>('/task/sign_v4/get_sign_state'); }
  sign() { return this.native<SignState>('/task/sign_v3/sign'); }
  report(event: ShareEvent, sessionId: string) {
    const { data, key, sid, time } = encryptReport([event]);
    return this.web('/account/data_report/', { type: '104', time_: time, session_id: sessionId }, {
      host: 'data.xiaoheihe.cn', body: new URLSearchParams({ data, key, sid }),
    });
  }
}
