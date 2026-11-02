import test from 'node:test'
import assert from 'node:assert/strict'
import { pathToFileURL, fileURLToPath } from 'node:url'
import { install } from '../lib/index.js'
import { createClient } from '../lib/client.js'
import { topicsView, legacyTopicsView } from '../lib/topics.js'
import { detail } from '../lib/presentation.js'

const scope={sessionId:'topics-test',draft:'介绍开源工具'}
const id='a'.repeat(32)
const event=name=>({value:{name}})
const search=query=>({value:{values:{'data.search.query':query}}})
function host(client){
  const panels={},handlers={}
  install({dshGo:{panel:(id,value)=>{panels[id]=value},on:(id,value)=>{handlers[id]=value}}},client)
  return {...panels,handlers}
}
async function snapshot(panel,context=scope){
  let close
  const value=await new Promise(resolve=>{close=panel.data(context,resolve)})
  close();return value
}

test('phone inherits live backend defaults until explicitly changed, isolated per session',async()=>{
  let defaults=['GitHub','AI'];const calls=[]
  const {topics,handlers,desk,settings}=host({
    preferences:async()=>({topics:defaults}),
    start:async(_text,options)=>{calls.push(options);return {job:{id}}},
    fromMaterial:async(_id,options)=>{calls.push(options);return {job:{id}}},
  })
  assert.equal((await snapshot(topics)).summary,'跟随后端默认：GitHub / AI')
  await handlers['write-post'](scope)
  assert.equal(calls[0].topics,undefined)
  topics.actions['toggle-topic'](scope,event('AI'))
  assert.match((await snapshot(settings)).topics,/本对话分区：GitHub$/)
  await handlers['write-post'](scope)
  await desk.actions['use-material'](scope,{value:{id}})
  assert.deepEqual(calls[1].topics,['GitHub'])
  assert.deepEqual(calls[2].topics,['GitHub'])
  // An earlier request owns a separate array.
  topics.actions['toggle-topic'](scope,event('PC游戏'))
  assert.deepEqual(calls[1].topics,['GitHub'])
  await handlers['write-post']({...scope,sessionId:'other'})
  assert.equal(calls[3].topics,undefined)
  defaults=['软件']
  assert.match((await snapshot(topics)).summary,/GitHub \/ PC游戏/)
  topics.actions['inherit-topics'](scope)
  assert.equal((await snapshot(topics)).summary,'跟随后端默认：软件')
  await handlers['write-post'](scope)
  assert.equal(calls[4].topics,undefined)
})

test('search shows canonical names and IDs and additions are bounded and deduplicated',async()=>{
  const {topics}=host({preferences:async()=>({topics:['GitHub','AI']}),findTopics:async()=>({items:[
    {name:'软件',topic_id:42},{name:'软件',topic_id:42},{name:'无效',topic_id:'not-id'},
    {name:'',topic_id:44},{name:'x'.repeat(101),topic_id:45},
  ]})})
  await snapshot(topics)
  await topics.actions['search-topics'](scope,search('软件'))
  let data=await snapshot(topics)
  assert.equal(data.results.length,1)
  assert.match(data.results[0].subtitle,/ID 42/)
  assert.match(topics.actions['add-topic'](scope,{value:{name:'伪造',id:'42'}}).toast,/已变化/)
  assert.equal(topics.actions['add-topic'](scope,{value:data.results[0].action.args}).refresh,true)
  assert.match(topics.actions['add-topic'](scope,{value:data.results[0].action.args}).toast,/已经选择/)
  data=await snapshot(topics)
  assert.deepEqual(data.selected.map(x=>x.title),['GitHub','AI','软件'])
  assert.equal(data.search.query,'软件')
})

test('empty selection and sixth topic cannot change the valid selection',async()=>{
  const {topics}=host({preferences:async()=>({topics:['GitHub']}),findTopics:async()=>({items:
    Array.from({length:5},(_,i)=>({name:'分区'+i,topic_id:i+10}))})})
  await snapshot(topics)
  assert.match(topics.actions['remove-topic'](scope,event('GitHub')).toast,/至少/)
  await topics.actions['search-topics'](scope,search('分区'))
  const data=await snapshot(topics)
  for(const row of data.results.slice(0,4))assert.equal(topics.actions['add-topic'](scope,{value:row.action.args}).refresh,true)
  assert.match(topics.actions['add-topic'](scope,{value:data.results[4].action.args}).toast,/最多/)
  assert.equal((await snapshot(topics)).selected.length,5)
})

test('save default updates the shared backend only on explicit action and never retries',async()=>{
  let defaults=['GitHub','AI'],writes=[]
  const {topics}=host({preferences:async()=>({topics:defaults}),savePreferences:async values=>{
    writes.push(values);defaults=values;return {topics:defaults}
  }})
  await snapshot(topics)
  topics.actions['toggle-topic'](scope,event('AI'))
  assert.deepEqual(writes,[])
  assert.match((await topics.actions['save-topics'](scope)).toast,/网页和手机/)
  assert.deepEqual(writes,[['GitHub']])
  assert.match((await snapshot(topics,{sessionId:'new'})).summary,/默认：GitHub$/)
  const failed=host({preferences:async()=>({topics:['GitHub','AI']}),savePreferences:async()=>{
    writes.push('failed');throw new Error('private-secret')
  }})
  await snapshot(failed.topics)
  const result=await failed.topics.actions['save-topics'](scope)
  assert.match(result.toast,/未确认/);assert.doesNotMatch(result.toast,/secret/)
  assert.equal(writes.filter(x=>x==='failed').length,1)
})

test('failed settings read leaves task creation inheriting defaults, and close cancels reads',async()=>{
  let options
  const {topics,handlers}=host({preferences:async()=>{throw new Error('cookie=secret')},start:async(_text,value)=>{
    options=value;return {job:{id}}
  }})
  const data=await snapshot(topics)
  assert.match(data.status,/读取失败/);assert.doesNotMatch(data.status,/secret/)
  assert.deepEqual(data.presets,[])
  assert.match(topics.actions['toggle-topic'](scope,event('GitHub')).toast,/连接后端/)
  await handlers['write-post'](scope)
  assert.equal(options.topics,undefined)
  let finish,signal,emitted=false
  const pending=host({preferences:s=>{signal=s;return new Promise(resolve=>{finish=resolve})}})
  const close=pending.topics.data(scope,()=>{emitted=true})
  close();finish({topics:['GitHub']})
  await new Promise(resolve=>setImmediate(resolve))
  assert.equal(signal.aborted,true);assert.equal(emitted,false)
})

test('late searches cannot replace newer results and invalid queries make no requests',async()=>{
  let finish,calls=0
  const {topics}=host({preferences:async()=>({topics:['GitHub','AI']}),findTopics:query=>{
    calls++
    return query==='旧查询'?new Promise(resolve=>{finish=resolve}):{items:[{name:'新查询',topic_id:22}]}
  }})
  for(const value of [undefined,{},'','x'.repeat(101)])assert.ok((await topics.actions['search-topics'](scope,search(value))).toast)
  assert.equal(calls,0)
  const old=topics.actions['search-topics'](scope,search('旧查询'))
  await topics.actions['search-topics'](scope,search('新查询'))
  finish({items:[{name:'旧查询',topic_id:21}]});await old
  assert.equal((await snapshot(topics)).results[0].title,'新查询')
})

test('native HTTP requests use backend preference and topic APIs, with no publish privilege',async()=>{
  const calls=[]
  const client=createClient({fetchImpl:async(url,options)=>{
    calls.push({path:new URL(url).pathname,method:options.method,body:options.body&&JSON.parse(options.body)})
    return Response.json({ok:true,topics:['GitHub','AI'],items:[],job:{id}})
  }})
  await client.preferences()
  await client.savePreferences(['GitHub','AI'])
  await client.findTopics('软件')
  await client.start('写工具',{topics:['GitHub']})
  await client.fromMaterial(id,{topics:['AI']})
  assert.deepEqual(calls.map(x=>[x.path,x.method]),[
    ['/api/authoring-settings','GET'],['/api/authoring-settings','POST'],['/api/operate','POST'],
    ['/api/autopilot','POST'],['/api/autopilot','POST'],
  ])
  assert.deepEqual(calls[1].body,{topics:['GitHub','AI']})
  assert.deepEqual(calls[2].body,{action:'find_topics',query:'软件'})
  assert.deepEqual(calls[3].body.topics,['GitHub'])
  assert.deepEqual(calls[4].body.topics,['AI'])
  assert.ok(calls.slice(3).every(x=>x.body.publish===false&&x.body.confirm===false))
})

test('job details show frozen topics and old tasks need no topic field',()=>{
  assert.match(detail({topics:['GitHub','AI']}),/本任务分区：GitHub \/ AI/)
  assert.equal(detail({}), '')
})

test('view negotiation keeps old clients on the native v1 picker',()=>{
  const {topics}=host({})
  assert.equal(topics.view(scope,{components:['textField','form']}),topicsView)
  assert.equal(topics.view(scope,{components:['text','actions']}),legacyTopicsView)
})

test('official bridge dispatches topic forms and composer actions without manifest violations',
  {skip:!process.env.DSH_GO_SDK},async()=>{
    const {createTestHost}=await import(pathToFileURL(process.env.DSH_GO_SDK+'/lib/testing.js').href)
    const bridge=createTestHost({dir:fileURLToPath(new URL('../',import.meta.url))})
    const requests=[]
    install({dshGo:bridge.dshGo},{preferences:async()=>({topics:['GitHub','AI']}),
      findTopics:async()=>({items:[{name:'软件',topic_id:42}]}),
      start:async(instruction,options)=>{requests.push({instruction,options});return {job:{id}}},
    })
    try{
      const feed=bridge.subscribe('topics',scope)
      await new Promise(resolve=>setImmediate(resolve))
      assert.deepEqual(feed.errors,[])
      assert.equal(feed.data.selected.length,2)
      for(const request of [
        {action:'toggle-topic',value:{name:'AI'}},
        {action:'search-topics',value:{values:{'data.search.query':'软件'}}},
        {action:'add-topic',value:{id:'42',name:'软件'}},
      ]){
        const result=await bridge.invoke('topics',{surface:'panel',scope,...request})
        assert.deepEqual(result.issues,[])
        assert.ok(result.effects.some(x=>x.type==='refresh'))
      }
      const result=await bridge.invoke('write-post',{scope,context:{draft:'介绍软件项目'}})
      assert.deepEqual(result.issues,[])
      assert.deepEqual(result.effects,[{type:'open',page:'panel:desk'}])
      assert.deepEqual(requests,[{instruction:'介绍软件项目',options:{profile:'flexible',images:'auto',subject:'auto',topics:['GitHub','软件']}}])
      assert.deepEqual(bridge.violations,[])
      assert.deepEqual(bridge.parsed.issues,[])
    }finally{bridge.dispose()}
  })

test('populated v1 and v2 topic views pass SDK budgets in every phone placement',
  {skip:!process.env.DSH_GO_SDK},async()=>{
    const {checkView}=await import(pathToFileURL(process.env.DSH_GO_SDK+'/lib/check.js').href)
    const {topics}=host({preferences:async()=>({topics:['GitHub','AI']}),findTopics:async()=>({items:
      Array.from({length:10},(_,i)=>({name:'软件'+i,topic_id:i+30}))})})
    await topics.actions['search-topics'](scope,search('软件'))
    const data=await snapshot(topics)
    assert.equal(data.results.length,8)
    for(const view of [topicsView,legacyTopicsView])for(const lang of ['zh','en']){
      const result=checkView(view,{budget:'panel',data,lang})
      assert.equal(result.ok,true,JSON.stringify(result.issues))
      assert.equal(result.truncated,0,JSON.stringify(result.issues))
      // The SDK may correct the user's accent to meet text contrast requirements.
      assert.ok(result.issues.every(issue=>issue.kind==='note'&&issue.path==='view.accent'),JSON.stringify(result.issues))
    }
  })
