import { randomUUID } from 'node:crypto';
import { setTimeout } from 'node:timers/promises';
import { shareEvent } from './report.js';
import { accountProfile } from './profile.js';
import { readSignHistory, signBalance, signFailure, signResponse, type SignDiagnostic } from './sign-diagnostics.js';
import type { FeedResult, Inspection, ReviewShareResult, ShareContent, ShareId, SignState, TaskClient, TaskExecution, TaskListResult, TaskSnapshot } from './types.js';

const shareIds: ShareId[] = ['1', '19', '31'];
const names = { '1': '分享帖子', '19': '分享游戏', '31': '分享游戏评价' };
const delays = [2000, 3000, 5000, 10000];

export function snapshot(result: TaskListResult | undefined, account: string): TaskSnapshot {
  if (String(result?.user?.userid) !== account) throw new Error('任务列表账号不匹配或登录已过期');
  const daily = result!.task_list?.find(group => group.title === '每日任务')?.tasks;
  if (!Array.isArray(daily) || !daily.length) throw new Error('每日任务列表为空');
  const tasks = daily.map(task => ({ id: String(task.report_extra?.task_id ?? 'sign'), title: task.title, state: task.state }));
  for (const id of shareIds) {
    const task = tasks.find(task => task.id === id);
    if (!task || !['waiting', 'finish'].includes(task.state ?? '')) throw new Error(`APP 任务 ${id} 缺失或状态变化，请检查接口版本`);
  }
  const level = result!.user!.level_info;
  if (!Number.isFinite(Number(level?.exp)) || !Number.isFinite(Number(level?.coin))) throw new Error('任务列表缺少经验或 H 币数据');
  return { tasks, exp: Number(level!.exp), coin: Number(level!.coin), battery: nonnegativeInteger(result!.user!.battery), profile: accountProfile(result!.user),
    level: nonnegativeInteger(level?.level), maxExp: nonnegativeInteger(level?.max_exp, 1) };
}

function nonnegativeInteger(value: unknown, minimum = 0): number | undefined {
  if (typeof value !== 'number' && (typeof value !== 'string' || !value.trim())) return undefined;
  const number = Number(value);
  return Number.isSafeInteger(number) && number >= minimum ? number : undefined;
}

export function experienceDelta(before: TaskSnapshot, after: TaskSnapshot): number | undefined {
  if (before.level === undefined || after.level === undefined) return undefined;
  let delta = after.exp - before.exp;
  if (after.level === before.level + 1 && before.maxExp !== undefined && before.exp <= before.maxExp) delta += before.maxExp;
  else if (after.level !== before.level) return undefined;
  // Missing intermediate levels or a balance decrease cannot establish an earned amount.
  return Number.isFinite(delta) && delta >= 0 ? delta : undefined;
}

export function signedToday(state: SignState | undefined, time = Date.now()) {
  return ['ok', 'ignore'].includes(state?.state ?? '') && Number(state?.signed_date) === Math.floor((time / 1000 + 8 * 3600) / 86400);
}

interface GameCandidate { app_id: string; h_src: string }
function gamesIn(node: unknown, output: GameCandidate[] = []): GameCandidate[] {
  if (!node || typeof node !== 'object') return output;
  const item = node as Record<string, unknown>;
  if (item.appid && item.h_src && !output.some(game => game.app_id === String(item.appid))) {
    output.push({ app_id: String(item.appid), h_src: item.h_src as string });
  }
  for (const child of Object.values(node)) gamesIn(child, output);
  return output;
}

export async function selectShare(client: Pick<TaskClient, 'web'>, id: ShareId): Promise<ShareContent> {
  if (id === '1') {
    const feed = await client.web<FeedResult>('/bbs/app/feeds', { offset: '0', limit: '20', pull: '1', last_pull: '1' });
    const post = feed?.links?.find(item => (item.linkid || item.link_id) && item.h_src);
    if (!post) throw new Error('没有找到可分享的帖子');
    return { src: 'link', link_id: String(post.linkid || post.link_id), h_src: post.h_src! };
  }
  const games = gamesIn(await client.web('/game/all_recommend/v2'));
  if (!games.length) throw new Error('没有找到可分享的游戏');
  if (id === '19') return { src: 'game_detail', ...games[0] };
  if (id !== '31') throw new Error('不支持的任务');
  for (const game of games.slice(0, 5)) {
    const comments = await client.web<FeedResult>('/bbs/app/link/game/comments', { appid: game.app_id, api_version: '4', offset: '0', limit: '20' });
    const review = comments?.links?.find(item => (item.linkid || item.link_id) && item.userid);
    if (!review) continue;
    const detail = await client.web<ReviewShareResult>('/game/comment/share_data/', { appid: game.app_id, userid: String(review.userid) });
    const linkId = detail?.comment_detail?.linkid;
    if (linkId) return { src: 'game_comment', link_id: String(linkId) };
  }
  throw new Error('没有找到可分享的游戏评价');
}

export async function inspect(client: Pick<TaskClient, 'tasks' | 'signState'>, account: string, now = Date.now): Promise<Inspection> {
  const current = snapshot(await client.tasks(), account);
  const sign = await client.signState();
  return { ...current, signed: signedToday(sign, now()) };
}

interface RunOptions { onSignDiagnostic?: (event: SignDiagnostic) => void; onStage?: (stage: string) => void; now?: () => number; sleep?: (ms: number) => Promise<unknown>; log?: (message: string) => void; checkpoint?: () => Promise<void>; onSnapshot?: (value: TaskSnapshot, expDelta: number | undefined) => void; onTask?: (id: keyof TaskExecution, action: 'executed' | 'skipped') => void }
export async function runDaily(client: TaskClient, account: string, { now = Date.now, sleep = setTimeout, log = console.log, checkpoint = async () => {}, onSnapshot = () => {}, onTask = () => {}, onStage = () => {}, onSignDiagnostic }: RunOptions = {}) {
  const diagnose = (event: Omit<SignDiagnostic, 'at'>) => {
    try { onSignDiagnostic?.({ ...event, at: new Date(now()).toISOString() }); }
    catch { /* Diagnostic output must not change task execution. */ }
  };
  const execution: TaskExecution = {};
  const recordTask = (id: keyof TaskExecution, action: 'executed' | 'skipped') => {
    execution[id] = action;
    onTask(id, action);
  };
  await checkpoint();
  onStage('inspect');
  const before = await inspect(client, account, now);
  let expDelta: number | undefined = 0;
  onSnapshot(before, expDelta);
  let current: TaskSnapshot = before;
  const record = (value: TaskSnapshot) => {
    const gain = experienceDelta(current, value);
    expDelta = expDelta === undefined || gain === undefined ? undefined : expDelta + gain;
    current = value;
    onSnapshot(current, expDelta);
  };
  onStage('sign');
  if (!before.signed) {
    if (onSignDiagnostic) diagnose({ phase: 'before', balance: signBalance(before), history: await readSignHistory(client, now()) });
    await checkpoint();
    recordTask('sign', 'executed');
    try {
      const response = await client.sign();
      diagnose({ phase: 'submitted', response: signResponse(response) });
      let verified = false;
      let state: SignState | undefined;
      for (const delay of delays) {
        await sleep(delay);
        state = await client.signState();
        if (signedToday(state, now())) { verified = true; break; }
      }
      if (!verified) throw new Error('签到未确认到账，任务已停止');
      log('签到完成');
      record(snapshot(await client.tasks(), account));
      if (onSignDiagnostic) diagnose({ phase: 'verified', response: signResponse(state), balance: signBalance(current),
        history: await readSignHistory(client, now()) });
    } catch (error) {
      diagnose({ phase: 'failed', error: signFailure(error) });
      throw error;
    }
  } else { recordTask('sign', 'skipped'); log('今天已签到'); }

  for (const id of shareIds) {
    onStage(`share_${id}`);
    if (current.tasks.find(task => task.id === id)!.state === 'finish') { recordTask(id, 'skipped'); log(`${names[id]}已完成，跳过`); continue; }
    await checkpoint();
    const addition = await selectShare(client, id);
    const sessionId = randomUUID();
    for (const action of ['show', 'tap', 'success'] as const) {
      await checkpoint();
      if (action === 'show') recordTask(id, 'executed');
      await client.report(shareEvent(action, addition, sessionId, Math.floor(now() / 1000)), sessionId);
      if (action === 'tap') await sleep(2000);
    }
    let settled = false;
    for (const delay of delays) {
      await sleep(delay);
      record(snapshot(await client.tasks(), account));
      if (current.tasks.find(task => task.id === id)!.state === 'finish') { settled = true; break; }
    }
    if (!settled) throw new Error(`${names[id]}上报后未结算，请稍后重新检查`);
    log(`${names[id]}完成`);
  }
  onStage('verify');
  const after = await inspect(client, account, now);
  record(after);
  if (!after.signed || shareIds.some(id => after.tasks.find(task => task.id === id)!.state !== 'finish')) {
    throw new Error('最终状态未通过检查，可能跨日或任务状态已变化');
  }
  return { completed: true, expDelta, coinDelta: after.coin - before.coin,
    batteryDelta: before.battery === undefined || after.battery === undefined ? undefined : after.battery - before.battery,
    execution, snapshot: after };
}
