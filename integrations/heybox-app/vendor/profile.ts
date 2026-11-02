import type { AccountProfile } from './types.js';

export function accountProfile(value: unknown): AccountProfile | undefined {
  if (!value || typeof value !== 'object') return undefined;
  const user = value as Record<string, unknown>;
  const rawName = user.nickname ?? user.username;
  const nickname = typeof rawName === 'string' ? rawName.replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, 80) : '';
  let avatar: string | undefined;
  if (typeof user.avatar === 'string' && user.avatar.length <= 2048) {
    try {
      const url = new URL(user.avatar);
      if (url.protocol === 'https:' && !url.username && !url.password) avatar = url.href;
    } catch { /* An absent or invalid avatar does not invalidate the account. */ }
  }
  return nickname || avatar ? { ...(nickname ? { nickname } : {}), ...(avatar ? { avatar } : {}) } : undefined;
}
