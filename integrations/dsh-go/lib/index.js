import { createClient } from './client.js'

export const name = 'local-xiaoheihe'
export const deskView = {
  type: 'stack', title: '小黑盒创作台', children: [
    { type: 'text', text: { $: 'data.status' } },
    { type: 'text', text: '在聊天输入框写要求，再点「自动成稿」。留空则从游戏热榜选题。', tone: 'muted' },
    { type: 'list', items: { $: 'data.items' } },
    { type: 'text', text: { $: 'data.preview' } },
    { type: 'actions', items: [
      { label: '刷新', action: 'reload', icon: 'refresh' },
      { label: '复制成稿', action: 'copy-draft', icon: 'copy' },
      { label: '交给助手', action: 'continue-agent', icon: 'chat' },
    ] },
  ],
}

// Export the factory for tests; production uses the same loopback client.
export function install(ctx, client) {
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
          if (!selected) Object.assign(state, { file: '', markdown: '', preview: '' })
          if (selected?.file) {
            const draft = await client.draft(selected.file, controller.signal)
            state.file = selected.file; state.markdown = draft.markdown
            state.preview = (draft.title + '\n\n' + draft.markdown).slice(0, 3500)
          }
          if (!closed) emit({ status: rows.length ? '任务在主机后台执行，关闭面板后继续。' : '还没有创作任务。',
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
