import test from 'node:test'
import assert from 'node:assert/strict'
import { endpoint, createClient } from '../lib/client.js'
import { install, deskView, settingsView } from '../lib/index.js'
import { pages, controls } from '../lib/presentation.js'
import { createServer } from 'node:http'
import { pathToFileURL } from 'node:url'

function host(client) {
  const handlers = {}, panels = {}
  install({ dshGo: { on: (id, fn) => { handlers[id] = fn }, panel: (id, spec) => { panels[id] = spec } } }, client)
  return { handlers, panel: panels.desk, personas: panels.personas, settings: panels.settings }
}
const id = 'a'.repeat(32)
const scope = { sessionId: 'mobile-session', draft: '写一篇软件教程' }

async function snapshot(panel, context = scope) {
  let close
  const data = await new Promise(resolve => { close = panel.data(context, resolve) })
  close()
  return data
}

test('long Chinese drafts can be read and copied completely across pages', async () => {
  const markdown = '长文测试😀'.repeat(1700)
  const { panel } = host({ list: async () => ({ items: [{id, file:'long.md'}] }),
    draft: async () => ({title:'长文', markdown}) })
  let data = await snapshot(panel), combined = '', total = pages('长文\n\n' + markdown).length
  for (let i = 0; i < total; i++) {
    assert.ok(data.preview.length <= 1800)
    assert.equal(panel.actions['copy-page'](scope).copy, data.preview)
    combined += data.preview
    panel.actions['next-page'](scope)
    data = await snapshot(panel)
  }
  assert.equal(combined, '长文\n\n' + markdown)
  assert.match(panel.actions['copy-draft'](scope).toast, /翻页/)
  assert.match(data.previewPage, new RegExp(`${total} / ${total}`))
})

test('Chinese drafts within the native character budget copy in full', async () => {
  const markdown = '中'.repeat(7999)
  const { panel } = host({list:async()=>({items:[{id,file:'draft.md'}]}),draft:async()=>({markdown})})
  await snapshot(panel)
  assert.equal(panel.actions['copy-draft'](scope).copy, markdown)
})

test('task groups include all recent rows and retain an older selected task', async () => {
  let rows = Array.from({length:20},(_,i)=>({id:i.toString(16).padStart(32,'0'),title:'任务'+i}))
  const {panel} = host({list:async()=>({items:rows}),job:async selected=>({job:{id:selected,title:'旧任务',state:'ready',file:'old.md'}}),draft:async()=>({markdown:'旧任务正文'})})
  await snapshot(panel)
  panel.actions['next-jobs'](scope)
  let data = await snapshot(panel)
  assert.equal(data.items[0].title, '任务8')
  panel.actions['select-job'](scope,{value:{id:rows[9].id}})
  rows = [] // The selected task fell outside the backend's most recent 20.
  data = await snapshot(panel)
  assert.match(data.preview,/旧任务正文/)
  assert.match(data.selected,/旧任务.*成稿已保存/)
})

test('optional materials and personas failing cannot hide task progress', async () => {
  const {panel}=host({list:async()=>({items:[{id,file:'draft.md',message:null}]}),
    draft:async()=>({markdown:'正文仍可读'}),materials:async()=>{throw new Error('secret')},persona:async()=>{throw new Error('404')}})
  const data=await snapshot(panel)
  assert.match(data.status,/素材暂时/)
  assert.doesNotMatch(data.status,/未连接|secret/)
  assert.equal(data.preview,'正文仍可读')
})

test('a task losing its draft cannot copy stale text', async () => {
  let file='draft.md'
  const {panel}=host({list:async()=>({items:[{id,file}]}),draft:async()=>({markdown:'旧正文'})})
  await snapshot(panel)
  file=null
  const data=await snapshot(panel)
  assert.equal(data.preview,'')
  assert.match(panel.actions['copy-draft'](scope).toast,/没有/)
})

test('disconnect clears copy state and automatic polling reconnects to the selected task', async t => {
  t.mock.timers.enable({apis:['setTimeout']})
  let connected=true,notify
  const {panel}=host({list:async()=>{if(!connected)throw new Error('offline');return {items:[{id,file:'draft.md'}]}},
    draft:async()=>({markdown:'恢复正文'})})
  await snapshot(panel)
  connected=false
  let next=new Promise(resolve=>{notify=resolve})
  const close=panel.data(scope,data=>notify(data))
  try{
    const offline=await next
    assert.match(offline.status,/未连接/)
    assert.match(panel.actions['copy-draft'](scope).toast,/没有/)
    connected=true
    next=new Promise(resolve=>{notify=resolve})
    t.mock.timers.tick(4000)
    const online=await next
    assert.equal(online.preview,'恢复正文')
    assert.ok(panel.actions['continue-agent'](scope).insert.includes(id))
  }finally{close()}
})

test('closing the desk aborts its request and suppresses late data', async()=>{
  let finish,signal,emitted=false
  const {panel}=host({list:s=>{signal=s;return new Promise(resolve=>{finish=resolve})}})
  const close=panel.data(scope,()=>{emitted=true})
  close();finish({items:[]})
  await new Promise(resolve=>setImmediate(resolve))
  assert.equal(signal.aborted,true)
  assert.equal(emitted,false)
})

test('late draft response cannot overwrite a newly selected task', async () => {
  let finish, started
  const ready=new Promise(resolve=>{started=resolve})
  const {panel}=host({list:async()=>({items:[{id,file:'old.md'}]}),draft:()=>{started();return new Promise(resolve=>{finish=resolve})}})
  let emitted=false
  const close=panel.data(scope,()=>{emitted=true})
  await ready
  panel.actions['select-job'](scope,{value:{id:'b'.repeat(32)}})
  finish({markdown:'过期结果'})
  await new Promise(resolve=>setImmediate(resolve))
  close()
  assert.equal(emitted,false)
  assert.match(panel.actions['copy-draft'](scope).toast,/没有/)
})

test('a failed draft read leaves progress and check warnings visible', async () => {
  const {panel}=host({list:async()=>({items:[{id}]}),job:async()=>({job:{id,file:'lost.md',state:'awaiting_images',issues:['需核对资料'],check:{warnings:['引用不足']}}}),draft:async()=>{throw new Error('missing')}})
  const data=await snapshot(panel)
  assert.match(data.selected,/等待配图/)
  assert.match(data.detail,/交给助手.*\n需核对资料\n引用不足/)
  assert.match(data.status,/正文暂时/)
  assert.doesNotMatch(data.status,/未连接/)
})

test('material and composer taps share the task creation guard', async () => {
  let finish,calls=0
  const {panel,handlers}=host({fromMaterial:()=>{calls++;return new Promise(resolve=>{finish=resolve})},start:()=>{calls++}})
  const first=panel.actions['use-material'](scope,{value:{id}})
  assert.match((await panel.actions['use-material'](scope,{value:{id}})).toast,/正在启动/)
  assert.match((await handlers['write-post'](scope)).toast,/正在启动/)
  finish({job:{id}});await first
  assert.equal(calls,1)
})

test('controls reflect backend task states and pagination preserves surrogate pairs',()=>{
  for(const state of ['published','publishing','uncertain','cancelled','skipped'])assert.deepEqual(controls({state}),[])
  assert.equal(controls({state:'writing'})[0].action,'pause-job')
  assert.equal(controls({state:'user_paused'})[0].action,'resume-job')
  const text='a'.repeat(1799)+'😀结束'
  const result=pages(text)
  assert.equal(result.join(''),text)
  assert.equal(result[0].length,1799)
})

test('populated phone views pass the actual DSH SDK without truncation', {skip:!process.env.DSH_GO_SDK}, async()=>{
  const {checkView}=await import(pathToFileURL(process.env.DSH_GO_SDK+'/lib/check.js').href)
  const {panel}=host({list:async()=>({items:Array.from({length:20},(_,i)=>({id:i.toString(16).padStart(32,'0'),title:'标题'.repeat(100),message:'进度'.repeat(100)}))}),
    job:async()=>({job:{id,state:'review',file:'long.md',title:'标题'.repeat(100),issues:['检查'.repeat(2000)]}}),
    draft:async()=>({title:'长文',markdown:'正文😀'.repeat(9000)}),
    materials:async()=>({items:Array.from({length:5},()=>({id,kind:'note',event:'素材'.repeat(200),text:'资料'.repeat(200)}))})})
  const data=await snapshot(panel)
  assert.ok(Buffer.byteLength(JSON.stringify(data))<=32768)
  for(const lang of ['zh','en']){
    const checked=checkView(deskView,{budget:'panel',data,lang})
    assert.equal(checked.ok,true,JSON.stringify(checked.issues))
    assert.deepEqual(checked.issues,[])
    assert.equal(checked.truncated,0)
  }
  const checked=checkView(settingsView,{budget:'panel',data:{profile:'short',images:'none',subject:'software'}})
  assert.deepEqual(checked.issues,[])
})

test('native writing settings reach both creation paths and remain session scoped', async()=>{
  const calls=[]
  const client=createClient({fetchImpl:async(url,options)=>{calls.push(JSON.parse(options.body));return Response.json({ok:true,job:{id}})}})
  const {settings,handlers,panel}=host(client)
  for(const [key,value] of Object.entries({profile:'short',images:'none',subject:'software'})){
    assert.equal(settings.actions['set-'+key](scope,{value:{value}}).refresh,true)
  }
  assert.match(settings.actions['set-images'](scope,{value:{value:'invalid'}}).toast,/无效/)
  await handlers['write-post'](scope)
  await panel.actions['use-material'](scope,{value:{id}})
  await handlers['write-post']({sessionId:'other',draft:'另一篇'})
  for(const body of calls.slice(0,2)){
    assert.equal(body.profile,'short');assert.equal(body.images,'none');assert.equal(body.subject,'software')
    assert.equal(body.publish,false);assert.equal(body.confirm,false)
  }
  assert.equal(calls[2].profile,'flexible');assert.equal(calls[2].images,'auto')
})

test('only host-local endpoints are permitted', () => {
  assert.equal(endpoint('http://127.0.0.1:9876'), 'http://127.0.0.1:9876')
  for (const value of ['http://192.168.1.2:8765', 'https://example.com', 'http://user:pass@localhost', 'http://localhost/?key=secret']) {
    assert.throws(() => endpoint(value))
  }
})

test('one tap sends the draft but never authorizes publication', async () => {
  const calls = []
  const client = createClient({ baseURL: 'http://localhost:8765', fetchImpl: async (url, options) => {
    calls.push({ url, ...options }); return Response.json({ ok: true, job: { id } })
  } })
  const { handlers } = host(client)
  assert.equal(calls.length, 0)
  assert.deepEqual(await handlers['write-post'](scope), { open: 'panel:desk' })
  assert.equal(calls.length, 1)
  const body = JSON.parse(calls[0].body)
  assert.equal(body.instruction, scope.draft)
  assert.equal(body.publish, false)
  assert.equal(body.confirm, false)
  assert.equal(calls[0].redirect, 'error')
})

test('ambiguous POST failure is never retried', async () => {
  let calls = 0
  const { handlers } = host({ start: async () => { calls++; throw new Error('private provider body') } })
  const result = await handlers['write-post'](scope)
  assert.equal(calls, 1)
  assert.match(result.toast, /勿重复/)
  assert.ok(!result.toast.includes('provider'))
})

test('double tap while starting cannot create a second job', async () => {
  let finish, count = 0
  const { handlers } = host({ start: () => { count++; return new Promise(r => { finish = r }) } })
  const first = handlers['write-post'](scope)
  assert.match((await handlers['write-post'](scope)).toast, /正在启动/)
  finish({ job: { id } }); await first
  assert.equal(count, 1)
})

test('panel streams read-only state and releases polling on close', async () => {
  let polls = 0, notify
  const ready = new Promise(resolve => { notify = resolve })
  const { panel } = host({ list: async () => { polls++; return { items: [{ id, title: '测试稿', message: '已保存', file: 'post-test.md' }] } },
    draft: async () => ({ title: '测试稿', markdown: '完整正文' }) })
  let state
  const close = panel.data(scope, data => { state = data; notify() })
  await ready; close()
  assert.equal(polls, 1)
  assert.match(state.preview, /完整正文/)
  assert.deepEqual(panel.actions['copy-draft'](scope), { copy: '完整正文', toast: '已复制完整正文' })
  assert.ok(panel.actions['continue-agent'](scope).insert.includes(id))
  assert.match(panel.actions['copy-draft']({ sessionId: 'other' }).toast, /没有/)
})

test('disconnected panel returns a setup message, not an exception', async () => {
  let notify
  const ready = new Promise(resolve => { notify = resolve })
  const { panel } = host({ list: async () => { throw new Error('secret') } })
  let state
  const close = panel.data(scope, data => { state = data; notify() })
  await ready; close()
  assert.match(state.status, /未连接/)
  assert.ok(!state.status.includes('secret'))
})

test('oversized streamed responses are refused', async () => {
  const client = createClient({ baseURL: 'http://localhost', fetchImpl: async () => new Response('x'.repeat(1024 * 1024 + 1)) })
  await assert.rejects(client.list(), /过大/)
})

test('long or invalid instructions do not touch the service', async () => {
  const { handlers } = host({ start: () => { throw new Error('must not be called') } })
  assert.match((await handlers['write-post']({ draft: 'x'.repeat(8001) })).toast, /八千/)
})

test('phone note capture and task pause use explicit actions', async () => {
  const captured = [], controls = []
  const { handlers, panel } = host({capture: async text=>captured.push(text), control: async (...args)=>controls.push(args)})
  assert.deepEqual(await handlers['open-desk'](scope), {open:'panel:desk'})
  assert.deepEqual(captured,[scope.draft])
  panel.actions['select-job'](scope,{value:{id}})
  assert.deepEqual(await panel.actions['pause-job'](scope),{refresh:true})
  assert.deepEqual(controls,[[id,'pause']])
})

test('persona badge does not expose a prompt or break older hosts', async () => {
  for(const compatible of [true,false]){
    let notify;const ready=new Promise(resolve=>{notify=resolve});let state;
    const {panel}=host({list:async()=>({items:[]}),persona:async()=>{if(!compatible)throw new Error('404');return {active:{name:'统一人设',revision:3}}}});
    const close=panel.data(scope,data=>{state=data;notify()});await ready;close();
    assert.match(state.persona,compatible?/统一人设.*3/:/暂未提供/);
    assert.ok(!JSON.stringify(state).includes('system_prompt'));
  }
})

test('adapter communicates with a real loopback HTTP server', async () => {
  const calls = []
  const server = createServer(async (req, res) => {
    let body = ''
    for await (const part of req) body += part
    calls.push({ method: req.method, path: req.url, body: body ? JSON.parse(body) : null })
    res.setHeader('Content-Type', 'application/json')
    res.end(JSON.stringify(req.method === 'POST' ? { ok: true, job: { id } } : { ok: true, items: [] }))
  })
  await new Promise(resolve => server.listen(0, '127.0.0.1', resolve))
  try {
    const client = createClient({ baseURL: `http://127.0.0.1:${server.address().port}` })
    assert.equal((await client.start('手机写稿')).job.id, id)
    assert.deepEqual((await client.list()).items, [])
    assert.equal(calls.length, 2)
    assert.deepEqual(calls.map(x => x.path), ['/api/autopilot', '/api/autopilot'])
    assert.equal(calls[0].body.publish, false)
    const controller = new AbortController(); controller.abort()
    await assert.rejects(client.list(controller.signal))
    assert.equal(calls.length, 2)
  } finally {
    server.closeAllConnections()
    await new Promise(resolve => server.close(resolve))
  }
})


test('phone persona panel reads metadata and changes only on explicit tap', async () => {
  const calls=[];let notify,state;
  const ready=new Promise(resolve=>{notify=resolve});
  const {personas,panel}=host({
    personas:async()=>({active:{name:'白川澪'},items:[{id:'shirakawa-mio',name:'白川澪',revision:0,active:true}]}),
    activatePersona:async id=>calls.push(id),
  });
  assert.deepEqual(panel.actions['open-personas'](),{open:'panel:personas'});
  const close=personas.data(scope,data=>{state=data;notify()});await ready;close();
  assert.match(state.status,/白川澪/);assert.deepEqual(calls,[]);
  assert.deepEqual(state.items[0].action,{id:'activate-persona',args:{id:'shirakawa-mio'}});
  assert.equal((await personas.actions['activate-persona'](scope,{value:{id:'shirakawa-mio'}})).refresh,true);
  assert.deepEqual(calls,['shirakawa-mio']);
  assert.match((await personas.actions['activate-persona'](scope,{value:{id:'../bad'}})).toast,/无效/);
  assert.equal(calls.length,1);
});

test('closing persona panel aborts request and suppresses late emission', async () => {
  let finish,signal,emitted=false;
  const {personas}=host({personas:s=>{signal=s;return new Promise(resolve=>{finish=resolve})}});
  const close=personas.data(scope,()=>{emitted=true});close();
  finish({active:{name:'默认'},items:[]});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(signal.aborted,true);assert.equal(emitted,false);
});

test('resume and cancel target the selected session task without publishing', async () => {
  const calls=[];
  const client=createClient({fetchImpl:async(url,options)=>{calls.push({url,body:JSON.parse(options.body)});return Response.json({ok:true})}});
  const {panel}=host(client);
  assert.match((await panel.actions['resume-job'](scope)).toast,/先选择/);
  panel.actions['select-job'](scope,{value:{id}});
  assert.equal((await panel.actions['resume-job'](scope)).refresh,true);
  assert.equal((await panel.actions['cancel-job'](scope)).refresh,true);
  assert.deepEqual(calls.map(x=>x.body),[{action:'resume',id},{action:'cancel',id}]);
  assert.ok(calls.every(x=>x.url.endsWith('/api/autopilot')));
});
