// Requests run on the DSH host, not on Android. Never expose the account UI to LAN.
export function endpoint(value = process.env.XHH_WEBUI_URL || 'http://127.0.0.1:8765') {
  const url = new URL(value)
  if (url.protocol !== 'http:' || !['127.0.0.1', 'localhost', '[::1]'].includes(url.hostname)
      || url.username || url.password || url.search || url.hash || url.pathname !== '/') {
    throw new Error('小黑盒服务地址必须是本机 HTTP 回环地址')
  }
  return url.origin
}

export function createClient({ baseURL, fetchImpl = fetch } = {}) {
  const base = endpoint(baseURL)
  async function request(path, body, signal) {
    const timeout = AbortSignal.timeout(1800)
    const response = await fetchImpl(base + path, {
      method: body === undefined ? 'GET' : 'POST', redirect: 'error',
      signal: signal ? AbortSignal.any([signal, timeout]) : timeout,
      headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    })
    // Bound streamed data too; Content-Length alone is not a reliable limit.
    const reader = response.body.getReader()
    const chunks = []; let size = 0
    try {
      while (true) {
        const { done, value } = await reader.read()
        if (done) break
        size += value.byteLength
        if (size > 1024 * 1024) throw new Error('服务响应过大')
        chunks.push(value)
      }
    } finally { await reader.cancel().catch(() => {}) }
    const data = JSON.parse(Buffer.concat(chunks).toString('utf8'))
    if (!response.ok || data.ok === false) throw new Error('小黑盒服务未完成请求')
    return data
  }
  return {
    list: signal => request('/api/autopilot', undefined, signal),
    capture: text => request('/api/desk', { kind: 'note', event: '手机随记', text }),
    materials: signal => request('/api/desk', undefined, signal),
    persona: signal => request('/api/personas?summary=1', undefined, signal),
    personas: signal => request('/api/personas?list=1', undefined, signal),
    activatePersona: id => request('/api/personas', { action: 'activate', id }),
    preferences: signal => request('/api/authoring-settings', undefined, signal),
    savePreferences: topics => request('/api/authoring-settings', { topics }),
    findTopics: query => request('/api/operate', { action: 'find_topics', query }),
    control: (id, action) => request('/api/autopilot', { id, action }),
    fromMaterial: (id, options = {}) => request('/api/autopilot', {
      material_id: id, subject: options.subject ?? 'auto', profile: options.profile ?? 'flexible',
      publish: false, confirm: false, images: options.images ?? 'auto',
      ...(options.topics ? { topics: options.topics.slice() } : {}),
    }),
    job: (id, signal) => request('/api/autopilot?id=' + encodeURIComponent(id), undefined, signal),
    draft: (file, signal) => request('/api/editorial?file=' + encodeURIComponent(file), undefined, signal),
    start: (instruction, options = {}) => request('/api/autopilot', {
      action: 'start', instruction, subject: options.subject ?? 'auto', genre: 'auto', profile: options.profile ?? 'flexible',
      images: options.images ?? 'auto', publish: false, confirm: false,
      ...(options.topics ? { topics: options.topics.slice() } : {}),
    }),
  }
}
