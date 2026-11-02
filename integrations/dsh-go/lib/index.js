import { createClient } from './client.js'

export const name = 'local-xiaoheihe'
export const deskView = {
  type: 'stack', title: '小黑盒创作台', children: [
    { type: 'text', text: { $: 'data.status' } },
    { type: 'text', text: { $: 'data.persona' }, tone: 'muted' },
    { type: 'text', text: '在聊天输入框写要求，再点「自动成稿」。留空则从游戏热榜选题。', tone: 'muted' },
    { type: 'list', items: { $: 'data.items' } },
    { type: 'list', items: { $: 'data.materials' } },
    { type: 'text', text: { $: 'data.preview' } },
    { type: 'actions', items: [
      { label: '刷新', action: 'reload', icon: 'refresh' },
      { label: '复制成稿', action: 'copy-draft', icon: 'copy' },
      { label: '交给助手', action: 'continue-agent', icon: 'chat' },
      { label: '暂停任务', action: 'pause-job', icon: 'clock' },
    ] },
    { type: 'actions', items: [
      { label: '继续任务', action: 'resume-job', icon: 'play' },
      { label: '取消任务', action: 'cancel-job', icon: 'remove' },
      { label: '切换人设', action: 'open-personas', icon: 'chat' },
    ] },
  ],
}

// Export the factory for tests; production uses the same loopback client.
export function install(ctx, client) {
  ctx.dshGo.panel('personas', {
    view: {type:'stack',title:'人设选择',children:[
      {type:'text',text:{$:'data.status'}},
      {type:'text',text:'切换只影响后续生成，运行中的任务保持原版本。',tone:'muted'},
      {type:'list',items:{$:'data.items'}},
      {type:'actions',items:[{label:'刷新列表',action:'reload-personas',icon:'refresh'}]},
    ]},
    data: (_scope,emit) => {
      const controller=new AbortController();let closed=false;
      void (async()=>{try{
        const data=await client.personas(controller.signal);
        if(!closed)emit({status:'当前人设：'+data.active.name,items:data.items.slice(0,30).map(item=>({
          title:item.name,subtitle:(item.active?'当前使用 · ':'点击使用 · ')+'修订 '+item.revision,
          action:{id:'activate-persona',args:{id:item.id}},
        }))});
      }catch{if(!closed)emit({status:'无法读取人设列表，请确认后端已更新并启动。',items:[]})}})();
      return ()=>{closed=true;controller.abort()};
    },
    actions:{
      'reload-personas':()=>({refresh:true}),
      'activate-persona':async(_scope,event)=>{
        const id=event.value?.id;
        if(typeof id!=='string'||!/^[a-zA-Z0-9_-]{1,64}$/.test(id))return {toast:'人设编号无效'};
        try{await client.activatePersona(id);return {refresh:true,toast:'已切换，后续生成使用此人设'}}
        catch{return {toast:'切换未确认，请刷新列表核对'}}
      },
    },
  });
  ctx.dshGo.on('open-desk', async scope => {
    const text = scope.draft?.trim()
    if (!text || text.length > 30000) return { toast: '先在输入框写下要保存的素材' }
    try { await client.capture(text); return { open: 'panel:desk' } }
    catch { return { toast: '保存未确认，请查看素材后再操作' } }
  })
  const states = new Map()
  const stateFor = scope => {
    const key = scope.sessionId || 'features'
    if (!states.has(key)) states.set(key, { selected: '', file: '', markdown: '', preview: '' })
    return states.get(key)
  }
  let starting = false
  ctx.dshGo.on('write-post', async scope => {
    if (starting) return { toast: '正在启动，请查看创作进度' }
    const instruction = scope.draft ?? ''
    if (typeof instruction !== 'string' || instruction.length > 8000) return { toast: '写作要求请控制在八千字以内' }
    starting = true
    try {
      const data = await client.start(instruction.trim())
      stateFor(scope).selected = data.job.id
      return { open: 'panel:desk' }
    } catch {
      // POST may have reached the backend. Never automatically retry it.
      return { toast: '启动未确认，请先查看进度，勿重复启动' }
    } finally { starting = false }
  })
  ctx.dshGo.panel('desk', {
    view: deskView,
    data: (scope, emit) => {
      const controller = new AbortController()
      let timer, closed = false
      const poll = async () => {
        try {
          const state = stateFor(scope), data = await client.list(controller.signal)
          const rows = (data.items || []).slice(0, 8)
          if (!state.selected && rows[0]) state.selected = rows[0].id
          const selected = rows.find(x => x.id === state.selected)
          if (!selected) Object.assign(state, { selected:'', file: '', markdown: '', preview: '' })
          if (selected?.file) {
            const draft = await client.draft(selected.file, controller.signal)
            state.file = selected.file; state.markdown = draft.markdown
            state.preview = (draft.title + '\n\n' + draft.markdown).slice(0, 3500)
          }
          const materials = client.materials ? (await client.materials(controller.signal)).items.filter(x=>['note','source','question','experiment'].includes(x.kind)).slice(0,5) : []
          let persona=''
          if(client.persona){try{const data=await client.persona(controller.signal);persona='当前人设：'+data.active.name+' · 修订 '+data.active.revision}catch{persona='当前主机暂未提供人设信息'}}
          if (!closed) emit({ persona, materials: materials.map(x=>({title:x.event,subtitle:x.text.slice(0,100),action:{id:'use-material',args:{id:x.id}}})), status: rows.length ? '任务在主机后台执行，关闭面板后继续。' : '还没有创作任务。',
            items: rows.map(x => ({ title: (x.title || '自动选题').slice(0, 100), subtitle: x.message.slice(0, 200),
              action: { id: 'select-job', args: { id: x.id } } })), preview: state.preview })
        } catch {
          if (!closed) emit({ status: '未连接。请在当前 DSH 主机启动 xhh auto --no-open，并配置文本模型。', items: [], preview: '' })
        } finally { if (!closed) { timer = setTimeout(poll, 4000); timer.unref?.() } }
      }
      void poll()
      return () => { closed = true; clearTimeout(timer); controller.abort() }
    },
    actions: {
      'open-personas':()=>({open:'panel:personas'}),
      'resume-job':async scope=>{
        const id=stateFor(scope).selected;if(!id)return {toast:'先选择一个任务'};
        try{await client.control(id,'resume');return {refresh:true}}
        catch{return {toast:'无法继续，请检查任务是否已结束或结果待核对'}}
      },
      'cancel-job':async scope=>{
        const id=stateFor(scope).selected;if(!id)return {toast:'先选择一个任务'};
        try{await client.control(id,'cancel');return {refresh:true}}
        catch{return {toast:'无法取消，任务可能已完成或正在提交'}}
      },
      'pause-job': async scope => {
        const id=stateFor(scope).selected
        if(!id)return {toast:'先选择一个任务'}
        try {await client.control(id,'pause');return {refresh:true}}
        catch {return {toast:'未能暂停，请查看任务是否已完成或正在提交'}}
      },
      'use-material': async (scope, event) => {
        const id = event.value?.id
        if (typeof id !== 'string' || !/^[0-9a-f]{32}$/.test(id)) return {toast:'素材编号无效'}
        try { const data=await client.fromMaterial(id);stateFor(scope).selected=data.job.id;return {refresh:true} }
        catch { return {toast:'启动未确认，请查看任务，勿重复启动'} }
      },
      'select-job': (scope, event) => {
        const id = event.value?.id
        if (typeof id !== 'string' || !/^[0-9a-f]{32}$/.test(id)) return { toast: '任务编号无效' }
        Object.assign(stateFor(scope), { selected: id, file: '', markdown: '', preview: '' })
        return { refresh: true }
      },
      reload: () => ({ refresh: true }),
      'copy-draft': scope => {
        const text = stateFor(scope).markdown
        if (!text) return { toast: '还没有可复制的成稿' }
        if (Buffer.byteLength(text) > 7500) return { toast: '成稿较长，请交给助手导出完整文件' }
        return { copy: text, toast: '已复制完整正文' }
      },
      'continue-agent': scope => {
        const id = stateFor(scope).selected
        if (!id) return { toast: '先选择一个创作任务' }
        return { insert: `请在当前主机的小黑盒项目中继续自动任务 ${id}：先查状态；待配图且已有生图授权时生成并回填；发布权限按已有约定，结果不明时不要重发。` }
      },
    },
  })
}

export function apply(ctx) {
  ctx.inject(['dshGo'], ctx => install(ctx, createClient()))
}
