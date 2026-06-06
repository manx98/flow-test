// REST 客户端
const J = { 'Content-Type': 'application/json' }

async function req(url, opts) {
  const r = await fetch(url, opts)
  if (!r.ok) throw new Error((await r.text()) || r.status)
  const ct = r.headers.get('content-type') || ''
  return ct.includes('application/json') ? r.json() : r
}

export const api = {
  health: () => req('/api/health'),
  catalog: () => req('/api/nodes'),
  complete: (code, line, column) =>
    req('/api/complete', { method: 'POST', headers: J, body: JSON.stringify({ code, line, column }) }).then(d => d.completions),
  check: (code) =>
    req('/api/check', { method: 'POST', headers: J, body: JSON.stringify({ code }) }).then(d => d.errors),
  // 工程
  listProjects: () => req('/api/projects').then(d => d.projects),
  createProject: (name) => req('/api/projects', { method: 'POST', headers: J, body: JSON.stringify({ name }) }),
  deleteProject: (name) => req(`/api/projects/${name}`, { method: 'DELETE' }),
  loadFlow: (name) => req(`/api/projects/${name}/flow`).then(d => d.graph),
  saveFlow: (name, graph) => req(`/api/projects/${name}/flow`, { method: 'PUT', headers: J, body: JSON.stringify({ graph }) }),
  loadMeta: (name) => req(`/api/projects/${name}/meta`).then(d => d.meta),
  saveMeta: (name, meta) => req(`/api/projects/${name}/meta`, { method: 'PUT', headers: J, body: JSON.stringify({ meta }) }),
  listImages: (name) => req(`/api/projects/${name}/images`).then(d => d.images),
  imageUrl: (name, img) => `/api/projects/${name}/images/${img}`,
  uploadImage: (name, blob, filename) => {
    const fd = new FormData()
    fd.append('file', blob, filename)
    return req(`/api/projects/${name}/images`, { method: 'POST', body: fd })
  },
  renameImage: (name, img, newName) =>
    req(`/api/projects/${name}/images/${img}/rename`, { method: 'POST', headers: J, body: JSON.stringify({ name: newName }) }),
  // 运行结果
  listResults: (name) => req(`/api/projects/${name}/results`).then(d => d.runs),
  getReport: (name, run) => req(`/api/projects/${name}/results/${run}/report.json`),
  resultUrl: (name, run, file) => `/api/projects/${name}/results/${run}/${file}`,
  deleteResult: (name, run) => req(`/api/projects/${name}/results/${run}`, { method: 'DELETE' }),
  clearResults: (name) => req(`/api/projects/${name}/results`, { method: 'DELETE' }),
  // 设备 + WebRTC
  connectDevice: (kind, config, project, node_id) => req('/api/devices/connect', { method: 'POST', headers: J, body: JSON.stringify({ kind, config, project, node_id }) }),
  disconnectDevice: (sid) => req(`/api/devices/${sid}/disconnect`, { method: 'POST' }),
  webrtcOffer: (session_id, sdp, type) => req('/api/webrtc/offer', { method: 'POST', headers: J, body: JSON.stringify({ session_id, sdp, type }) }),
}
