import { readFileSync, existsSync, mkdirSync, renameSync, writeFileSync, rmSync } from 'node:fs'
import { randomUUID } from 'node:crypto'
import { join, dirname } from 'node:path'
import { userInfo } from 'node:os'
import { spawnSync } from 'node:child_process'
import { HeyboxClient } from './vendor/client.js'
import { validateConfig, saveConfig } from './vendor/config.js'
import { createLoginConfig, normalizePhone, sendLoginCode, verifyLoginCode } from './vendor/login-core.js'
import { getDeviceToken } from './vendor/device-token.js'
import { selectShare, signedToday } from './vendor/tasks.js'
import { shareEvent } from './vendor/report.js'

export const day = time => new Date(time+8*3600000).toISOString().slice(0,10)
const wait = ms => new Promise(resolve=>setTimeout(resolve,ms))
export class NativeError extends Error {
 constructor(code,message){super(message);this.code=code}
}
export function safeError(error){
 if(error instanceof NativeError)return {code:error.code,message:error.message}
 if(error?.captchaRequired)return {code:'captcha_required',message:'平台要求人机验证，请先在小黑盒App处理；没有自动绕过验证。'}
 if(error?.category==='auth')return {code:'login_required',message:'App登录已失效，请重新在本机登录。'}
 if(error?.rateLimited)return {code:'rate_limited',message:'平台限制请求频率，已停止；请稍后再操作。'}
 if(error?.stage)return {code:'device_token_failed',message:'设备授权组件没有完成，请检查网络后重试。'}
 return {code:'request_failed',message:'平台请求未确认，请先刷新状态；没有自动重复提交。'}
}
export function taskRows(result,account){
 if(String(result?.user?.userid)!==account)throw new NativeError('account_mismatch','App账号与当前账号不一致，未执行任务。')
 const rows=result?.task_list?.find(g=>g.title==='每日任务')?.tasks
 if(!Array.isArray(rows)||!rows.length)throw new NativeError('schema_changed','平台没有返回可识别的每日任务。')
 return rows.map(task=>{
  if(typeof task.title!=='string'||!['finish','waiting','todo'].includes(task.state))throw new NativeError('schema_changed','每日任务格式发生变化，已停止。')
  return {id:task.type==='sign'?'sign':String(task.report_extra?.task_id??''),title:task.title,type:task.type,state:task.state}
 })
}
export class NativeService {
 constructor(root,{factory=config=>new HeyboxClient(config),token=getDeviceToken,now=Date.now,sleep=wait}={}){
  this.root=root;this.factory=factory;this.token=token;this.now=now;this.sleep=sleep
  this.sessions=new Map();this.lastCode=new Map()
  this.configFile=join(root,'.data','app','session.json')
 }
 config(expected=''){
  if(!existsSync(this.configFile))throw new NativeError('login_required','请先完成本机App短信登录。')
  let config
  try{config=validateConfig(JSON.parse(readFileSync(this.configFile,'utf8')))}catch{throw new NativeError('login_required','本机App授权不可用，请重新登录。')}
  if(expected&&config.session.heybox_id!==expected)throw new NativeError('account_mismatch','App账号与当前网页版账号不一致，请登录同一账号。')
  return config
 }
 status(expected=''){
  try{const config=this.config(expected);return {configured:true,account:config.session.heybox_id}}
  catch(error){return {configured:false,...safeError(error)}}
 }
 atomic(file,value){
  mkdirSync(dirname(file),{recursive:true,mode:0o700})
  const temp=file+'.'+randomUUID()+'.tmp'
  try{writeFileSync(temp,JSON.stringify(value,null,2)+'\n',{mode:0o600,flag:'wx'});renameSync(temp,file)}
  finally{rmSync(temp,{force:true})}
 }
 async send(phone,expected=''){
  try{phone=normalizePhone(phone)}catch{throw new NativeError('invalid_phone','请填写有效手机号，海外号码包含国家区号。')}
  const timestamp=this.now()
  if(timestamp-(this.lastCode.get(phone)??-Infinity)<60000)throw new NativeError('cooldown','验证码请求未满一分钟，请等待或使用已收到的验证码。')
  // Record before transmission: a timeout must not cause a duplicate SMS.
  this.lastCode.set(phone,timestamp)
  const config=createLoginConfig(await this.token())
  await sendLoginCode(config,phone,{clientFactory:this.factory})
  const id=randomUUID();this.sessions.set(id,{phone,config,expected,expires:timestamp+600000,attempts:0})
  for(const [key,value] of this.sessions)if(value.expires<this.now())this.sessions.delete(key)
  return {login_id:id,expires_at:timestamp+600000,phone_hint:phone.slice(0,3)+'****'+phone.slice(-4)}
 }
 async verify(id,code,expected=''){
  const session=this.sessions.get(id)
  if(!session||session.expires<this.now())throw new NativeError('login_expired','本次登录已过期，请重新获取验证码。')
  if(session.expected!==expected)throw new NativeError('account_mismatch','当前账号已经变化，请重新开始登录。')
  if(typeof code!=='string'||!/^\d{4,8}$/.test(code))throw new NativeError('invalid_code','验证码应为4至8位数字。')
  if(session.attempts>=3)throw new NativeError('attempt_limit','验证码尝试已达三次，请重新登录。')
  session.attempts++
  let config
  try{config=await verifyLoginCode(session.config,session.phone,code,{clientFactory:this.factory})}
  catch(error){
   if(error?.retryCode)throw new NativeError('invalid_code','验证码未通过，请核对后重试；不会自动重新发送短信。')
   throw error
  }
  if(expected&&config.session.heybox_id!==expected)throw new NativeError('account_mismatch','该手机号不是当前网页版账号，原App授权保持不变。')
  const folder=dirname(this.configFile)
  mkdirSync(folder,{recursive:true,mode:0o700})
  if(process.platform==='win32'){
   const user=(process.env.USERDOMAIN?process.env.USERDOMAIN+'\\':'')+userInfo().username
   const secured=spawnSync('icacls.exe',[folder,'/inheritance:r','/grant:r',user+':(OI)(CI)F','*S-1-5-18:(OI)(CI)F'],{windowsHide:true,stdio:'ignore'})
   if(secured.status!==0)throw new NativeError('permissions_failed','无法保护本地授权目录，未保存新登录。')
  }
  saveConfig(config,this.configFile);this.sessions.delete(id)
  return {configured:true,account:config.session.heybox_id}
 }
 async inspect(client,account){
  const result=await client.tasks(),tasks=taskRows(result,account)
  const signed=signedToday(await client.signState(),this.now())
  return {tasks:tasks.map(t=>t.id==='sign'?{...t,state:signed?'finish':'waiting'}:t),signed,date:day(this.now())}
 }
 async read(expected=''){
  const config=this.config(expected),state=await this.inspect(this.factory(config),config.session.heybox_id)
  return {...state,complete:state.signed&&state.tasks.every(t=>t.state==='finish'),account:config.session.heybox_id}
 }
 async run(expected=''){
  const config=this.config(expected),account=config.session.heybox_id,client=this.factory(config),date=day(this.now())
  const file=join(this.root,'.data','app-daily',account,date+'.json')
  let journal={date,account,steps:{}}
  if(existsSync(file)){
   try{journal=JSON.parse(readFileSync(file,'utf8'))}catch{throw new NativeError('journal_invalid','任务执行记录损坏，请核对状态后处理，未重新提交。')}
   if(journal.date!==date||journal.account!==account||(!journal.steps||typeof journal.steps!=='object'||Array.isArray(journal.steps)))throw new NativeError('journal_invalid','任务执行记录不匹配，未重新提交。')
  }
  const save=()=>this.atomic(file,journal)
  const sameDay=()=>{if(day(this.now())!==date)throw new NativeError('day_changed','执行期间跨日，已停止，请重新读取今天的任务。')}
  let state=await this.inspect(client,account)
  for(const task of state.tasks){
   sameDay()
   const done=task.id==='sign'?state.signed:task.state==='finish'
   if(done){journal.steps[task.id]={state:'verified'};save();continue}
   const label=new Map([['1',/帖子|文章/],['19',/游戏/],['31',/评价|评测/]]).get(task.id)
   if(task.id!=='sign'&&(!label||!label.test(task.title))){
    journal.steps[task.id||task.title]={state:'unsupported',message:'当前任务类型尚未验证，未套用其他任务的上报格式。'};save();continue
   }
   if(['submitted','uncertain','verified'].includes(journal.steps[task.id]?.state)){
    throw new NativeError('result_uncertain','上次任务结果未确认；已读取平台状态，但不会自动重复提交。')
   }
   // Select real, existing platform content before recording a write attempt.
   const content=task.id==='sign'?null:await selectShare(client,task.id)
   sameDay();journal.steps[task.id]={state:'submitted',at:this.now()};save()
   try{
    if(task.id==='sign')await client.sign()
    else{
     const session=randomUUID()
     for(const action of ['show','tap','success']){
      sameDay();await client.report(shareEvent(action,content,session,Math.floor(this.now()/1000)),session)
      if(action==='tap')await this.sleep(2000)
     }
    }
    let verified=false
    for(const delay of [1500,2500,5000,10000]){
     await this.sleep(delay);sameDay();state=await this.inspect(client,account)
     verified=task.id==='sign'?state.signed:state.tasks.find(t=>t.id===task.id)?.state==='finish'
     if(verified)break
    }
    if(!verified)throw new NativeError('result_uncertain','请求已提交但任务未确认完成，已保留记录，不会重复上报。')
    journal.steps[task.id]={state:'verified',at:this.now()};save()
   }catch(error){
    const issue=safeError(error)
    journal.steps[task.id]={state:issue.code==='login_required'?'needs_login':'uncertain',code:issue.code,at:this.now()};save()
    throw error
   }
  }
  sameDay();state=await this.inspect(client,account)
  const complete=state.signed&&state.tasks.every(t=>t.state==='finish')
  journal.complete=complete;journal.checked_at=this.now();save()
  return {...state,complete,account,steps:journal.steps}
 }
}
