// Stay within the v1 native renderer's 2000 UTF-16 unit text limit.
export const PAGE_SIZE = 1800
export const JOBS_PER_PAGE = 8
export function pages(text, size = PAGE_SIZE) {
  const result = []
  while (text.length) {
    let end = Math.min(size, text.length)
    if (end < text.length && /[\uD800-\uDBFF]/.test(text[end - 1])) end--
    result.push(text.slice(0, end))
    text = text.slice(end)
  }
  return result.length ? result : ['']
}

export const clip = (value, limit) => String(value ?? '').slice(0, limit)
export const stateLabel = state => ({
  queued: '排队中', collecting: '整理资料', planning: '构思中', writing: '写作中',
  checking: '检查中', awaiting_images: '等待配图', ready: '成稿已保存',
  review: '需要检查', paused: '任务暂缓', user_paused: '已暂停', failed: '任务失败',
  waiting_slot: '等待发布时段', publishing: '正在提交', published: '已发布',
  uncertain: '发布结果待核对', cancelled: '已取消', skipped: '已跳过',
}[state] || '任务进度')

export function detail(job) {
  if (!job) return ''
  const notes = [
    ...(job.issues || []), ...(job.check?.blockers || []).filter(x => job.publish || !x.startsWith('现在不能发')),
    ...(job.check?.warnings || []),
  ]
  if (job.state === 'awaiting_images') notes.unshift('正文已保存。点「交给助手」接续配图；宿主需提供生图工具。')
  if (job.state === 'uncertain') notes.unshift('请先核对发布结果，不要重复提交。')
  const persona = job.persona_snapshot
  if (Array.isArray(job.topics) && job.topics.length) notes.unshift('本任务分区：' + job.topics.join(' / '))
  if (persona?.card?.name) notes.unshift('本任务人设：' + persona.card.name + ' · 修订 ' + persona.revision)
  return clip([...new Set(notes)].join('\n'), 1800)
}

export function controls(job) {
  if (!job) return []
  const items = []
  if (['queued', 'collecting', 'planning', 'writing', 'checking'].includes(job.state))
    items.push({ label: '暂停任务', action: 'pause-job', icon: 'clock' })
  if (['paused', 'user_paused', 'failed', 'review', 'ready'].includes(job.state))
    items.push({ label: '继续任务', action: 'resume-job', icon: 'play' })
  if (!['published', 'publishing', 'uncertain', 'cancelled', 'skipped'].includes(job.state))
    items.push({ label: '取消任务', action: 'cancel-job', icon: 'remove' })
  return items
}
