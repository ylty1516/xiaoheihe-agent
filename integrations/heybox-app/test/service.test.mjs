import test from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync, mkdtempSync, existsSync, rmSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join, resolve, dirname, basename } from 'node:path'
import { NativeService, taskRows, safeError } from '../lib/service.mjs'
import { createLoginConfig } from '../lib/vendor/login-core.js'
import { saveConfig } from '../lib/vendor/config.js'
import { signNative, makeNativeNonce } from '../lib/vendor/native-algorithm.js'
const time=Date.UTC(2026,10,3,1), signedDate=Math.floor((time/1000+8*3600)/86400)
const fixture=JSON.parse(readFileSync(new URL('./native-v14.json',import.meta.url),'utf8'))
for(const record of fixture.records)test('native signature matches original '+record.id,()=>{
 const actual=signNative(record.input)
 for(const key of ['_time','hkey','_rnd'])assert.equal(actual[key],record.signature[key])
 assert.match(actual.nonce,/^[A-Za-z0-9]{32}$/)
})
test('native nonce replay matches the observed original',()=>{
 let i=0;assert.equal(makeNativeNonce(fixture.nonceReplay.timeSeconds,()=>fixture.nonceReplay.indices[i++]),fixture.nonceReplay.actual)
})
function setup(t,ids=['1','19','31']){
 const root=mkdtempSync(join(tmpdir(),'xhh-native-test-'));t.after(()=>{const target=resolve(root);assert.equal(dirname(target),resolve(tmpdir()));assert.ok(basename(target).startsWith('xhh-native-test-'));rmSync(target,{recursive:true,force:true})})
 const config={...createLoginConfig('device-token-test'),session:{heybox_id:'123',pkey:'pkey-test',device_id:'test-device',x_xhh_tokenid:'device-token-test'}}
 let signed=false;const completed=new Set(),calls=[]
 const list=()=>({user:{userid:'123',username:'test'},task_list:[{title:'每日任务',tasks:[
  {title:'签到',type:'sign',state:signed?'finish':'waiting'},
  ...ids.map(id=>({title:({1:'分享帖子',19:'分享游戏',31:'分享游戏评价',11:'分享评论'}[id]||'分享'+id),type:'open_window',state:completed.has(id)?'finish':'waiting',report_extra:{task_id:id}}))
 ]}]})
 const client={
  tasks:async()=>list(),signState:async()=>({state:signed?'ok':'waiting',signed_date:signed?signedDate:0}),
  sign:async()=>{calls.push('sign');signed=true},
  report:async event=>{calls.push(event);if(event.path.endsWith('/success'))completed.add({link:'1',game_detail:'19',game_comment:'31'}[event.addition.src])},
  native:async endpoint=>{calls.push(endpoint);return endpoint.includes('login_code/')?{profile:{heybox_id:'123'},account_detail:{userid:'123'},pkey:'pkey-test'}:{}},
  web:async endpoint=>{
   if(endpoint==='/bbs/app/feeds')return {links:[{linkid:'42',h_src:'real-source'}]}
   if(endpoint==='/game/all_recommend/v2')return {games:[{appid:'570',h_src:'game-source'}]}
   if(endpoint==='/bbs/app/link/game/comments')return {links:[{linkid:'43',userid:'123'}]}
   if(endpoint==='/game/comment/share_data/')return {comment_detail:{linkid:'43'}}
   throw new Error('unexpected endpoint '+endpoint)
  },
 }
 const service=new NativeService(root,{factory:()=>client,token:async()=>'device-token-test',now:()=>time,sleep:async()=>{}})
 return {root,service,config,client,calls,completed,list}
}
test('SMS login is explicit, rate limited, accepts actual task variants and saves no phone or code',async t=>{
 const {root,service,calls}=setup(t,['1','11','19'])
 assert.equal(service.status().configured,false);assert.equal(calls.length,0)
 const pending=await service.send('13800000000','123')
 assert.equal(calls.filter(x=>x==='/account/get_login_code/').length,1)
 await assert.rejects(service.send('13800000000','123'),error=>error.code==='cooldown')
 await service.verify(pending.login_id,'123456','123')
 const text=readFileSync(join(root,'.data/app/session.json'),'utf8')
 assert.ok(!text.includes('13800000000')&&!text.includes('123456'))
 assert.equal(service.status('123').configured,true)
 assert.equal(calls.filter(x=>x==='/account/login_code/').length,1)
})
test('different App account cannot replace the existing authorization',async t=>{
 const {root,service,config}=setup(t);saveConfig(config,service.configFile)
 const pending=await service.send('13800000000','456')
 await assert.rejects(service.verify(pending.login_id,'123456','456'),error=>error.code==='account_mismatch')
 assert.equal(JSON.parse(readFileSync(join(root,'.data/app/session.json'),'utf8')).session.heybox_id,'123')
})
test('wrong-account reads and writes stop before contacting the platform',async t=>{
 const {service,config,calls}=setup(t);saveConfig(config,service.configFile)
 await assert.rejects(service.run('456'),error=>error.code==='account_mismatch')
 assert.deepEqual(calls,[])
 assert.throws(()=>taskRows({user:{userid:'999'}},'123'),error=>error.code==='account_mismatch')
})
test('confirmed task execution signs once and skips completed tasks on subsequent runs',async t=>{
 const {root,service,config,calls}=setup(t);saveConfig(config,service.configFile)
 const first=await service.run('123')
 assert.equal(first.complete,true)
 assert.equal(calls.filter(x=>x==='sign').length,1)
 assert.equal(calls.filter(x=>typeof x==='object').length,9)
 assert.ok(calls.filter(x=>typeof x==='object').every(x=>['link','game_detail','game_comment'].includes(x.addition.src)))
 const count=calls.length;assert.equal((await service.run('123')).complete,true);assert.equal(calls.length,count)
 const journal=JSON.parse(readFileSync(join(root,'.data/app-daily/123/2026-11-03.json'),'utf8'))
 assert.equal(journal.complete,true)
 assert.ok(Object.values(journal.steps).every(x=>x.state==='verified'))
})
test('unverified comment-share variant is retained and never mapped to a game review',async t=>{
 const {service,config,calls}=setup(t,['11']);saveConfig(config,service.configFile)
 const result=await service.run('123')
 assert.equal(result.complete,false);assert.equal(result.steps['11'].state,'unsupported')
 assert.equal(calls.filter(x=>typeof x==='object').length,0)
})
test('ambiguous submission remains uncertain across process restart and is not repeated',async t=>{
 const {root,service,config,client,calls}=setup(t,[]);saveConfig(config,service.configFile)
 client.sign=async()=>{calls.push('uncertain-sign');throw new Error('private-token')}
 await assert.rejects(service.run('123'))
 const second=new NativeService(root,{factory:()=>client,now:()=>time,sleep:async()=>{}})
 await assert.rejects(second.run('123'),error=>error.code==='result_uncertain')
 assert.equal(calls.filter(x=>x==='uncertain-sign').length,1)
 const safe=safeError(new Error('cookie=private-token'))
 assert.ok(!JSON.stringify(safe).includes('private-token'))
})
test('empty or unknown platform task states fail closed',()=>{
 assert.throws(()=>taskRows({user:{userid:'123'},task_list:[]},'123'))
 assert.throws(()=>taskRows({user:{userid:'123'},task_list:[{title:'每日任务',tasks:[{title:'a',state:'new-state'}]}]},'123'))
})
test('unsettled shares cannot be recorded as successful completion',async t=>{
 const {service,config,client}=setup(t,['1']);saveConfig(config,service.configFile);client.report=async()=>{}
 await assert.rejects(service.run('123'),error=>error.code==='result_uncertain')
 assert.equal((await service.read('123')).complete,false)
})
