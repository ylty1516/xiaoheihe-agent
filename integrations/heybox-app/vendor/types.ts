export interface Config {
  session: { heybox_id: string; pkey: string; device_id: string; x_xhh_tokenid: string };
  device: { model: string; osVersion: string };
  app: { version: string; build: string; shaderVersion: string };
  profile?: AccountProfile;
}

export interface AccountProfile { nickname?: string; avatar?: string }

export interface WebSignature { hkey: string; _time: string; nonce: string }
export interface NativeSignature extends WebSignature { _rnd: string }
export type Query = Record<string, string>;
export type ShareId = '1' | '19' | '31';
export type TaskExecution = Partial<Record<'sign' | ShareId, 'executed' | 'skipped'>>;
export type ShareAction = 'show' | 'tap' | 'success';
export type ShareContent =
  | { src: 'link'; link_id: string; h_src: string }
  | { src: 'game_detail'; app_id: string; h_src: string }
  | { src: 'game_comment'; link_id: string };
export interface ShareEvent {
  type: '3' | '4';
  path: string;
  time: string;
  addition: (ShareContent & { h_session_id: string } | {
    src: 'web'; act_id: string; web_url: string;
  }) & { plat?: string };
}

// API fields stay optional where the existing runtime checks handle missing data.
export interface TaskListResult {
  user?: { userid?: string | number; username?: string; avatar?: string; battery?: string | number; level_info?: { exp?: string | number; coin?: string | number; level?: string | number; max_exp?: string | number } };
  task_list?: Array<{ title?: string; tasks?: Array<{ title?: string; state?: string; report_extra?: { task_id?: string | number } }> }>;
}
export interface TaskSnapshot {
  tasks: Array<{ id: string; title?: string; state?: string }>;
  exp: number;
  level?: number;
  maxExp?: number;
  coin: number;
  battery?: number;
  profile?: AccountProfile;
}
export interface SignState { state?: string; signed_date?: string | number }
export interface Inspection extends TaskSnapshot { signed: boolean }
export interface FeedResult { links?: Array<{ linkid?: string | number; link_id?: string | number; h_src?: string; userid?: string | number }> }
export interface ReviewShareResult { comment_detail?: { linkid?: string | number } }

export interface TaskClient {
  tasks(): Promise<TaskListResult>;
  signState(): Promise<SignState>;
  sign(): Promise<SignState>;
  web<T = unknown>(endpoint: string, extra?: Query): Promise<T>;
  report(event: ShareEvent, sessionId: string): Promise<unknown>;
}
