import test from 'node:test'
import assert from 'node:assert/strict'
import { endpoint, createClient } from '../lib/client.js'
import { install } from '../lib/index.js'
import { createServer } from 'node:http'

function host(client) {
  const handlers = {}, panels = {}
  install({ dshGo: { on: (id, fn) => { handlers[id] = fn }, panel: (id, spec) => { panels[id] = spec } } }, client)
  return { handlers, panel: panels.desk, personas: panels.personas }
}
const id = 'a'.repeat(32)
const scope = { sessionId: 'mobile-session', draft: '写一篇软件教程' }

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
