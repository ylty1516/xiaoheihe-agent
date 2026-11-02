import { createClient } from './client.js'
import { pages, clip, detail, controls, stateLabel, JOBS_PER_PAGE } from './presentation.js'
import { installTopics } from './topics.js'

export const name = 'local-xiaoheihe'
export const deskView = {
  type: 'stack', title: '小黑盒创作台', children: [
    { type: 'text', text: { $: 'data.status' } },
    { type: 'text', text: { $: 'data.persona' }, tone: 'muted' },
    { type: 'text', text: '在聊天输入框写要求，再点「自动成稿」。留空默认找 GitHub 开源项目。', tone: 'muted' },
    { type: 'text', text: { $: 'data.topics' }, tone: 'muted' },
    { type: 'text', text: { $: 'data.daily' }, tone: 'muted' },
    { type: 'actions', items: [{ label: '创作设置', action: 'open-settings', icon: 'settings' }] },
    { type: 'list', items: { $: 'data.items' } },
    { type: 'text', text: { $: 'data.jobsPage' }, tone: 'muted' },
    { type: 'actions', items: [
      { label: '上一组任务', action: 'previous-jobs', icon: 'list' },
      { label: '下一组任务', action: 'next-jobs', icon: 'list' },
    ] },
    { type: 'text', text: { $: 'data.selected' } },
    { type: 'text', text: { $: 'data.detail' } },
    { type: 'list', items: { $: 'data.materials' } },
    { type: 'text', text: { $: 'data.previewPage' }, tone: 'muted' },
    { type: 'text', text: { $: 'data.preview' } },
    { type: 'actions', items: [
      { label: '正文上一页', action: 'previous-page', icon: 'read' },
      { label: '正文下一页', action: 'next-page', icon: 'read' },
      { label: '复制本页', action: 'copy-page', icon: 'copy' },
    ] },
    { type: 'actions', items: [
      { label: '刷新', action: 'reload', icon: 'refresh' },
      { label: '复制成稿', action: 'copy-draft', icon: 'copy' },
      { label: '交给助手', action: 'continue-agent', icon: 'chat' },
      { label: '切换人设', action: 'open-personas', icon: 'chat' },
    ] },
    { type: 'actions', items: { $: 'data.controls' } },
  ],
}

const choices = {
  profile: [['flexible', '按材料决定篇幅'], ['short', '短帖'], ['article', '长文']],
  images: [['auto', '按需配图，由助手接续'], ['none', '不配图']],
  subject: [['auto', '按本次要求'], ['games', '游戏'], ['hardware', '硬件外设'], ['software', '软件'], ['ai', 'AI 工具']],
}
export const settingsView = {
  type: 'stack', title: '创作设置', children: [
    {type:'text',text:'设置用于当前对话后续新建的任务，已有任务保持原设置。'},
    {type:'text',text:{$:'data.topics'}},
    {type:'actions',items:[{label:'发布分区',action:'open-topics',icon:'list'}]},
    ...Object.entries(choices).flatMap(([key, values]) => [
      {type:'text',text:({profile:'篇幅',images:'配图',subject:'题材'})[key]},
      {type:'options',id:'set-'+key,selected:{$:'data.'+key},options:values.map(([value,label])=>({value,label}))},
    ]),
    {type:'text',text:'长文沿用账号长文检查要求。无图短稿请选择短帖和不配图。'},
    {type:'actions',items:[{label:'返回创作台',action:'back-desk',icon:'write'}]},
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
        if(!closed)emit({status:'当前人设：'+clip(data.active.name,80),items:data.items.slice(0,30).map(item=>({
          title:clip(item.name,80),subtitle:(item.active?'当前使用 · ':'点击使用 · ')+'修订 '+item.revision,
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
    const text = typeof scope.draft === 'string' ? scope.draft.trim() : ''
    if (!text || text.length > 30000) return { toast: '先在输入框写下要保存的素材' }
    try { await client.capture(text); return { open: 'panel:desk' } }
    catch { return { toast: '保存未确认，请查看素材后再操作' } }
  })
  const states = new Map()
  const stateFor = scope => {
    const key = scope.sessionId || 'features'
    if (!states.has(key)) states.set(key, { selected: '', file: '', markdown: '', preview: '', page: 0, jobsPage: 0, jobsCount: 0,
      options: {profile:'flexible', images:'auto', subject:'auto'} })
    return states.get(key)
  }
  const topicSettings = installTopics(ctx, client, stateFor)
  ctx.dshGo.panel('settings', {
    view: settingsView,
    data: (scope, emit) => { emit({...stateFor(scope).options,topics:topicSettings.summary(scope)}); return () => {} },
    actions: {
      'back-desk': () => ({open:'panel:desk'}),
      'open-topics': () => ({open:'panel:topics'}),
      ...Object.fromEntries(Object.entries(choices).map(([key, values]) => ['set-'+key, (scope, event) => {
        const value = event.value?.value
        if (!values.some(item => item[0] === value)) return {toast:'设置选项无效'}
        stateFor(scope).options[key] = value
        return {refresh:true,toast:'已更新后续创作设置'}
      }])),
    },
  })
  let starting = false
  ctx.dshGo.on('write-post', async scope => {
    if (starting) return { toast: '正在启动，请查看创作进度' }
    const instruction = scope.draft ?? ''
    if (typeof instruction !== 'string' || instruction.length > 8000) return { toast: '写作要求请控制在八千字以内' }
    starting = true
    try {
      const data = await client.start(instruction.trim(), topicSettings.options(scope))
      Object.assign(stateFor(scope), {selected: data.job.id, page: 0, file: '', markdown: '', preview: ''})
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
          if (closed) return
          const rows = data.items || [], warnings = []
          state.jobsCount = rows.length
          state.jobsPage = Math.min(state.jobsPage, Math.max(0, Math.ceil(rows.length / JOBS_PER_PAGE) - 1))
          if (!state.selected && rows[0]) state.selected = rows[0].id
          const selectedId = state.selected
          let selected = rows.find(x => x.id === selectedId)
          // The backend list is bounded; always load the chosen task by id.
          if (selectedId && client.job) {
            try { selected = (await client.job(selectedId, controller.signal)).job }
            catch { warnings.push('所选任务详情暂不可用，稍后刷新。') }
          }
          if (closed || state.selected !== selectedId) return
          // Clear stale text before loading a different file, including no-file tasks.
          let file = '', markdown = '', previewText = ''
          if (selected?.file) {
            try {
              const draft = await client.draft(selected.file, controller.signal)
              if (closed || state.selected !== selectedId) return
              file = selected.file; markdown = draft.markdown
              previewText = (draft.title ? draft.title + '\n\n' : '') + draft.markdown
            } catch { warnings.push('正文暂时无法读取，稍后刷新。') }
          }
          const optional = await Promise.allSettled([
            client.materials?.(controller.signal), client.persona?.(controller.signal), client.dailyTasks?.(controller.signal),
          ])
          if (closed || state.selected !== selectedId) return
          Object.assign(state, { file, markdown, preview: previewText })
          const [materialsResult, personaResult, dailyResult] = optional
          const daily = dailyResult.value
          const dailyText = daily?.state === 'checked' && Array.isArray(daily.tasks)
            ? `每日任务 ${daily.tasks.filter(x=>x.finished).length}/${daily.tasks.length} 已完成`+(daily.complete?'':' · 签到或分享仍待完成')
            : '每日任务：'+(daily?.message || '暂未读取到进度')
          const materials = (materialsResult.value?.items || []).filter(x=>['note','source','question','experiment'].includes(x.kind)).slice(0,5)
          if (materialsResult.status === 'rejected') warnings.push('素材暂时无法读取。')
          const active = personaResult.value?.active
          const persona = active ? '当前人设：' + clip(active.name, 80) + ' · 修订 ' + active.revision : '当前主机暂未提供人设信息'
          const preview = pages(state.preview)
          state.page = Math.min(state.page, preview.length - 1)
          emit({ persona, daily:dailyText, topics:topicSettings.summary(scope), materials: materials.map(x=>({title:clip(x.event,80),subtitle:clip(x.text,100),action:{id:'use-material',args:{id:x.id}}})),
            status: (rows.length || selected ? '任务在主机后台执行，关闭面板后继续。' : '还没有创作任务。') + warnings.join(''),
            jobsPage: `任务第 ${state.jobsPage + 1} / ${Math.max(1, Math.ceil(rows.length / JOBS_PER_PAGE))} 组 · 最近 ${rows.length} 项`,
            selected: selected ? clip((selected.title || '自动选题') + ' · ' + stateLabel(selected.state) + '\n' + (selected.message || ''), 500) : '',
            detail: detail(selected), controls: controls(selected),
            items: rows.slice(state.jobsPage * JOBS_PER_PAGE, (state.jobsPage + 1) * JOBS_PER_PAGE).map(x => ({
              title: (x.id === selectedId ? '✓ ' : '') + clip(x.title || '自动选题', 100), subtitle: clip(stateLabel(x.state) + ' · ' + (x.message || ''), 200),
              action: { id: 'select-job', args: { id: x.id } } })),
            previewPage: state.markdown ? `正文第 ${state.page + 1} / ${preview.length} 页` : '暂无可预览正文',
            preview: preview[state.page] })
        } catch {
          if (!closed) {
            Object.assign(stateFor(scope), { file: '', markdown: '', preview: '' })
            emit({ status: '未连接。请在当前 DSH 主机启动 xhh auto --no-open；服务恢复后会自动重连。', items: [], materials: [], controls: [], persona: '', daily: '', topics:topicSettings.summary(scope), selected: '', detail: '', jobsPage: '', previewPage: '', preview: '' })
          }
        } finally { if (!closed) { timer = setTimeout(poll, 4000); timer.unref?.() } }
      }
      void poll()
      return () => { closed = true; clearTimeout(timer); controller.abort() }
    },
    actions: {
      'open-settings': () => ({open:'panel:settings'}),
      'previous-jobs': scope => { const state = stateFor(scope); state.jobsPage = Math.max(0, state.jobsPage - 1); return {refresh:true} },
      'next-jobs': scope => { const state = stateFor(scope); state.jobsPage = Math.min(Math.max(0, Math.ceil(state.jobsCount / JOBS_PER_PAGE) - 1), state.jobsPage + 1); return {refresh:true} },
      'previous-page': scope => { const state = stateFor(scope); state.page = Math.max(0, state.page - 1); return {refresh:true} },
      'next-page': scope => { const state = stateFor(scope); state.page = Math.min(pages(state.preview).length - 1, state.page + 1); return {refresh:true} },
      'copy-page': scope => {
        const state = stateFor(scope)
        return state.markdown ? {copy: pages(state.preview)[state.page], toast:'已复制本页'} : {toast:'还没有可复制的成稿'}
      },
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
        if (starting) return {toast:'正在启动，请查看创作进度'}
        starting = true
        try { const data=await client.fromMaterial(id,topicSettings.options(scope));Object.assign(stateFor(scope),{selected:data.job.id,page:0,file:'',markdown:'',preview:''});return {refresh:true} }
        catch { return {toast:'启动未确认，请查看任务，勿重复启动'} }
        finally { starting = false }
      },
      'select-job': (scope, event) => {
        const id = event.value?.id
        if (typeof id !== 'string' || !/^[0-9a-f]{32}$/.test(id)) return { toast: '任务编号无效' }
        Object.assign(stateFor(scope), { selected: id, file: '', markdown: '', preview: '', page: 0 })
        return { refresh: true }
      },
      reload: () => ({ refresh: true }),
      'copy-draft': scope => {
        const text = stateFor(scope).markdown
        if (!text) return { toast: '还没有可复制的成稿' }
        if ([...text].length > 8000) return { toast: '正文超过八千字，请翻页并复制本页，或交给助手导出' }
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
