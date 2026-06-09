// REST 客户端
import { getLocale } from './i18n.js'

const jsonHeaders = () => ({ 'Content-Type': 'application/json', 'Accept-Language': getLocale() })
const langHeaders = () => ({ 'Accept-Language': getLocale() })

async function req(url, opts) {
  const r = await fetch(url, opts)
  if (!r.ok) throw new Error((await r.text()) || r.status)
  const ct = r.headers.get('content-type') || ''
  return ct.includes('application/json') ? r.json() : r
}

export const api = {
  health: () => req('/api/health', { headers: langHeaders() }),
  catalog: () => req('/api/nodes', { headers: langHeaders() }),
  complete: (code, line, column) =>
    req('/api/complete', { method: 'POST', headers: jsonHeaders(), body: JSON.stringify({ code, line, column }) }).then(d => d.completions),
  check: (code) =>
    req('/api/check', { method: 'POST', headers: jsonHeaders(), body: JSON.stringify({ code }) }).then(d => d.errors),
  aiDraft: (name, state, files = []) => {
    const fd = new FormData()
    fd.append('state', JSON.stringify(state || {}))
    for (const f of files || []) fd.append('files', f, f.name)
    return req(`/api/projects/${name}/ai/draft`, { method: 'POST', headers: langHeaders(), body: fd })
  },
  // 工程
  loadSettings: () => req('/api/settings', { headers: langHeaders() }).then(d => d.settings),
  saveSettings: (settings) => req('/api/settings', { method: 'PUT', headers: jsonHeaders(), body: JSON.stringify({ settings }) }),
  listProjects: () => req('/api/projects', { headers: langHeaders() }).then(d => d.projects),
  createProject: (name) => req('/api/projects', { method: 'POST', headers: jsonHeaders(), body: JSON.stringify({ name }) }),
  deleteProject: (name) => req(`/api/projects/${name}`, { method: 'DELETE', headers: langHeaders() }),
  loadFlow: (name) => req(`/api/projects/${name}/flow`, { headers: langHeaders() }).then(d => d.graph),
  saveFlow: (name, graph) => req(`/api/projects/${name}/flow`, { method: 'PUT', headers: jsonHeaders(), body: JSON.stringify({ graph }) }),
  loadMeta: (name) => req(`/api/projects/${name}/meta`, { headers: langHeaders() }).then(d => d.meta),
  saveMeta: (name, meta) => req(`/api/projects/${name}/meta`, { method: 'PUT', headers: jsonHeaders(), body: JSON.stringify({ meta }) }),
  listImages: (name) => req(`/api/projects/${name}/images`, { headers: langHeaders() }).then(d => d.images),
  imageUrl: (name, img) => `/api/projects/${name}/images/${img}`,
  uploadImage: (name, blob, filename) => {
    const fd = new FormData()
    fd.append('file', blob, filename)
    return req(`/api/projects/${name}/images`, { method: 'POST', headers: langHeaders(), body: fd })
  },
  renameImage: (name, img, newName) =>
    req(`/api/projects/${name}/images/${img}/rename`, { method: 'POST', headers: jsonHeaders(), body: JSON.stringify({ name: newName }) }),
  // 运行结果
  listResults: (name) => req(`/api/projects/${name}/results`, { headers: langHeaders() }).then(d => d.runs),
  getReport: (name, run) => req(`/api/projects/${name}/results/${run}/report.json`, { headers: langHeaders() }),
  resultUrl: (name, run, file) => `/api/projects/${name}/results/${run}/${file}`,
  deleteResult: (name, run) => req(`/api/projects/${name}/results/${run}`, { method: 'DELETE', headers: langHeaders() }),
  clearResults: (name) => req(`/api/projects/${name}/results`, { method: 'DELETE', headers: langHeaders() }),
  // 设备 + WebRTC
  connectDevice: (kind, config, project, node_id) => req('/api/devices/connect', { method: 'POST', headers: jsonHeaders(), body: JSON.stringify({ kind, config, project, node_id }) }),
  disconnectDevice: (sid) => req(`/api/devices/${sid}/disconnect`, { method: 'POST', headers: langHeaders() }),
  webrtcOffer: (session_id, sdp, type) => req('/api/webrtc/offer', { method: 'POST', headers: jsonHeaders(), body: JSON.stringify({ session_id, sdp, type }) }),
}
