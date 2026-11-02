import test from 'node:test'
import assert from 'node:assert/strict'
import { pathToFileURL } from 'node:url'
import { install } from '../lib/index.js'
const scope={sessionId:'daily-phone'}
function host(client){
 const panels={};install({dshGo:{panel:(id,value)=>panels[id]=value,on:()=>{}}},client);return panels
}
async function snapshot(panel){let close;const data=await new Promise(resolve=>{close=panel.data(scope,resolve)});close();return data}
test('phone daily panel shares settings without adding a fifth manifest panel',async()=>{
 const calls=[]
 const panels=host({dailyTasks:async()=>({tasks:[{title:'签到',finished:false,reason:'待完成'}],settings:{auto_execute:true}}),appSession:async()=>({configured:true}),startDaily:async()=>calls.push('start'),dailySettings:async value=>calls.push(value)})
 assert.equal(Object.keys(panels).length,4)
 assert.deepEqual(panels.desk.actions['open-daily'](scope),{open:'panel:settings'})
 assert.equal(panels.settings.view(scope).title,'签到与每日任务')
 const data=await snapshot(panels.settings)
 assert.equal(data.auto,'on');assert.equal(data.actions[0].action,'run-daily')
 assert.deepEqual(calls,[])
 assert.equal((await panels.settings.actions['run-daily']()).refresh,true)
 assert.equal((await panels.settings.actions['set-daily-auto'](scope,{value:{value:'off'}})).refresh,true)
 assert.deepEqual(calls,['start',false])
 panels.settings.actions['back-writing'](scope)
 assert.equal(panels.settings.view(scope).title,'创作设置')
})
test('phone hides run until authorized and offers only a local host console address',async()=>{
 const panels=host({consoleURL:'http://127.0.0.1:8765/',dailyTasks:async()=>({tasks:[]}),appSession:async()=>({configured:false})})
 panels.desk.actions['open-daily'](scope)
 const data=await snapshot(panels.settings)
 assert.ok(!data.actions.some(x=>x.action==='run-daily'))
 assert.equal(panels.settings.actions['copy-console']().copy,'http://127.0.0.1:8765/')
 assert.match(data.status,/主机控制台/)
})
test('populated daily phone view passes official SDK budget', {skip:!process.env.DSH_GO_SDK},async()=>{
 const {checkView}=await import(pathToFileURL(process.env.DSH_GO_SDK+'/lib/check.js').href)
 const panels=host({dailyTasks:async()=>({tasks:Array.from({length:4},()=>({title:'分享游戏详情',finished:false,reason:'等待执行App分享流程'})),settings:{auto_execute:true}}),appSession:async()=>({configured:true})})
 panels.desk.actions['open-daily'](scope)
 const result=checkView(panels.settings.view(scope),{budget:'panel',data:await snapshot(panels.settings)})
 assert.equal(result.ok,true);assert.equal(result.truncated,0);assert.deepEqual(result.issues,[])
})
