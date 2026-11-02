import { constants, publicEncrypt, randomUUID } from 'node:crypto';
import { HeyboxClient } from './client.js';
import { validateConfig } from './config.js';
import { androidBase64 } from './report.js';
import { snapshot } from './tasks.js';
import { accountProfile } from './profile.js';
import type { Config, Query } from './types.js';

// Public login encryption key returned by the verified APP's NDKTools.getrsakey.
const loginKey = `-----BEGIN PUBLIC KEY-----
MIGfMA0GCSqGSIb3DQEBAQUAA4GNADCBiQKBgQDZgjVwAiKTjZ55nG+mW6r3TSU4
ECvNYqDMIS/bhCj2QaH5GI/KZb2TBp+CBvUj9SLFnmJQ0kzHzHoGZCQ88VevCffF
7JePGF9cmKQqotlfTKbV4oxV5iLz7JSG6b/Vg7AXtrTolNtWsa8HiB0tI0YClYaQ
lOXm4UxLeSxQwSFETwIDAQAB
-----END PUBLIC KEY-----`;

interface LoginResult {
  profile?: { heybox_id?: string | number; nickname?: string; avatar?: string };
  account_detail?: { userid?: string | number };
  pkey?: string;
}
type LoginClient = Pick<HeyboxClient, 'native' | 'tasks'>;
export interface LoginDependencies {
  captcha?: { ticket: string; randstr: string };
  getDeviceToken?: () => Promise<string>;
  clientFactory?: (config: Config) => LoginClient;
}
function captchaQuery(proof: LoginDependencies['captcha']): Query {
  if (!proof) return {};
  if (!proof.ticket.length || proof.ticket.length > 2048 || !proof.randstr.length || proof.randstr.length > 256
      || /[^\x21-\x7e]/.test(proof.ticket + proof.randstr)
      || /^trerror_/i.test(proof.ticket) || /^trerror_/i.test(proof.randstr)) throw new Error('人机验证凭据无效，请重新验证');
  return { captcha_type: 'confirm', ticket: proof.ticket, randstr: proof.randstr };
}

export function normalizePhone(value: string) {
  const phone = value.trim();
  if (/^1[3-9]\d{9}$/.test(phone)) return '+86' + phone;
  if (/^\+[1-9]\d{7,14}$/.test(phone)) return phone;
  throw new Error('手机号格式不正确，海外号码请包含 + 和国家或地区区号');
}

export function encryptPhone(phone: string, key = loginKey) {
  return androidBase64(publicEncrypt({ key, padding: constants.RSA_PKCS1_PADDING }, Buffer.from(phone)));
}

export function createLoginConfig(token: string): Config {
  return {
    session: { heybox_id: '-1', pkey: '', device_id: randomUUID(), x_xhh_tokenid: token },
    device: { model: 'PKJ110', osVersion: '17' },
    app: { version: '1.3.398', build: '1142', shaderVersion: '14' },
  };
}

export async function sendLoginCode(config: Config, phone: string, options: LoginDependencies = {}) {
  const client = (options.clientFactory || (value => new HeyboxClient(value)))(config);
  await client.native('/account/get_login_code/', captchaQuery(options.captcha), new URLSearchParams({ phone_num: encryptPhone(normalizePhone(phone)) }));
}

export async function verifyLoginCode(config: Config, phone: string, code: string, options: LoginDependencies = {}) {
  if (!/^\d{4,8}$/.test(code)) throw new Error('验证码应为 4 至 8 位数字');
  const factory = options.clientFactory || (value => new HeyboxClient(value));
  const result = await factory(config).native<LoginResult>('/account/login_code/', { code, is_new_device: '1', ...captchaQuery(options.captcha) },
    new URLSearchParams({ phone_num: encryptPhone(normalizePhone(phone)) }));
  const account = String(result?.profile?.heybox_id ?? '');
  if (!/^\d+$/.test(account) || account !== String(result?.account_detail?.userid) || !result?.pkey) {
    throw new Error('登录响应中的账号或凭据无效，原配置已保留');
  }
  const authenticated = validateConfig({ ...config, session: { ...config.session, heybox_id: account, pkey: result.pkey } });
  const current = snapshot(await factory(authenticated).tasks(), account);
  authenticated.profile = current.profile || accountProfile(result.profile);
  return authenticated;
}
