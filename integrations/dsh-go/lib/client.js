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
    control: (id, action) => request('/api/autopilot', { id, action }),
    fromMaterial: id => request('/api/autopilot', { material_id: id, profile: 'flexible', publish: false, images: 'auto' }),
    job: (id, signal) => request('/api/autopilot?id=' + encodeURIComponent(id), undefined, signal),
    draft: (file, signal) => request('/api/editorial?file=' + encodeURIComponent(file), undefined, signal),
    start: instruction => request('/api/autopilot', {
      action: 'start', instruction, subject: 'auto', genre: 'auto', profile: 'flexible',
      images: 'auto', publish: false, confirm: false,
    }),
  }
}
