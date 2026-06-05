<template>
  <div class="app">
    <div class="toolbar">
      <strong>flow-test</strong>
      <select v-model="current" @change="openProject">
        <option value="" disabled>选择工程</option>
        <option v-for="p in projects" :key="p" :value="p">{{ p }}</option>
      </select>
      <button @click="newProject">新建工程</button>
      <button @click="save" :disabled="!current">保存</button>
      <button @click="run" :disabled="!current || running">▶ 运行</button>
      <button @click="stop" :disabled="!running">■ 停止</button>
      <button @click="openHistory" :disabled="!current">运行历史</button>
      <template v-if="lastResult">
        <a v-if="lastResult.pdf_url" :href="lastResult.pdf_url" target="_blank" class="dl">报告PDF</a>
        <a :href="lastResult.report_url" target="_blank" class="dl">JSON</a>
        <a :href="lastResult.junit_url" target="_blank" class="dl">JUnit</a>
      </template>
      <span class="status">{{ status }}</span>
    </div>
    <div class="stage" ref="stage">
      <canvas ref="canvasEl" class="graph"></canvas>
      <div ref="overlayEl" class="overlay"></div>

      <div class="toasts">
        <div v-for="t in toasts" :key="t.id" class="toast" :class="t.level">
          {{ t.message }}
        </div>
      </div>

      <div v-if="showHistory" class="drawer">
        <div class="drawer-head">
          <span>运行历史 — {{ current }}</span>
          <span class="head-actions">
            <button v-if="runs.length" class="clear" @click="clearRuns">清空</button>
            <button @click="showHistory = false">×</button>
          </span>
        </div>
        <div class="drawer-body">
          <ul class="runs">
            <li v-for="r in runs" :key="r" :class="{ active: r === selRun }" @click="selectRun(r)">
              <span class="rname">{{ r }}</span>
              <button class="del" title="删除此记录" @click.stop="deleteRun(r)">🗑</button>
            </li>
            <li v-if="!runs.length" class="empty">暂无运行记录</li>
          </ul>
          <div v-if="report" class="report">
            <div class="rsum" :class="report.passed ? 'ok' : 'fail'">
              {{ report.passed ? '✅ 通过' : '❌ 失败 ' + report.failed + '/' + report.total }} · {{ report.duration }}s
            </div>
            <div class="dls">
              <a :href="resultUrl(selRun, 'report.pdf')" target="_blank">PDF</a>
              <a :href="resultUrl(selRun, 'report.json')" target="_blank">JSON</a>
              <a :href="resultUrl(selRun, 'report.junit.xml')" target="_blank">JUnit</a>
            </div>
            <table class="atable">
              <tr v-for="(a, idx) in report.asserts" :key="idx" :class="a.ok ? 'ok' : 'fail'">
                <td>{{ a.ok ? '✓' : '✗' }}</td><td>{{ a.message }}</td><td>n{{ a.node }}</td>
              </tr>
            </table>
            <div v-for="(a, idx) in failedEvidence" :key="'e' + idx" class="evid">
              <div class="ecap">证据 · {{ a.message }}</div>
              <img :src="a.evidence" />
            </div>
            <pre v-if="report.logs && report.logs.length" class="logs">{{ report.logs.join('\n') }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref } from 'vue'
import { LGraph, LGraphCanvas } from 'litegraph.js'
import { api } from './api.js'
import { registerCatalog, setDeviceActionHandler, setCaptureHandler, setImageActionHandler } from './graph/litegraph-setup.js'
import { VideoOverlay } from './graph/video-overlay.js'
import { ShotOverlay } from './graph/shot-overlay.js'
import { CodeOverlay } from './graph/code-overlay.js'
import { DeviceConnection } from './webrtc/device.js'

const projects = ref([])
const current = ref('')
const status = ref('')
const running = ref(false)
const lastResult = ref(null)
let runWs = null

// 运行期「提示」节点弹出的 toast
const toasts = ref([])
let toastSeq = 0
function showToast(message, level = 'info') {
  const id = ++toastSeq
  toasts.value.push({ id, message, level })
  setTimeout(() => { toasts.value = toasts.value.filter(t => t.id !== id) }, 4000)
}

// 运行历史
const showHistory = ref(false)
const runs = ref([])
const selRun = ref('')
const report = ref(null)
const failedEvidence = computed(() =>
  (report.value?.asserts || []).filter(a => !a.ok && a.evidence))

async function openHistory() {
  if (!current.value) return
  runs.value = await api.listResults(current.value)
  report.value = null
  selRun.value = ''
  showHistory.value = true
}
async function selectRun(r) {
  selRun.value = r
  try { report.value = await api.getReport(current.value, r) }
  catch (e) { report.value = null }
}
function resultUrl(run, file) { return api.resultUrl(current.value, run, file) }

async function deleteRun(r) {
  if (!confirm(`删除运行记录 ${r}？`)) return
  try {
    await api.deleteResult(current.value, r)
    runs.value = runs.value.filter(x => x !== r)
    if (selRun.value === r) { selRun.value = ''; report.value = null }
    status.value = `已删除记录 ${r}`
  } catch (e) { alert('删除失败: ' + e.message) }
}

async function clearRuns() {
  if (!confirm('清空全部运行历史？')) return
  try {
    const { deleted } = await api.clearResults(current.value)
    runs.value = []; selRun.value = ''; report.value = null
    status.value = `已清空 ${deleted} 条运行记录`
  } catch (e) { alert('清空失败: ' + e.message) }
}
const stage = ref(null)
const canvasEl = ref(null)
const overlayEl = ref(null)

let graph = null
let lgcanvas = null
let overlay = null
let shots = null
let codes = null

onMounted(async () => {
  const catalog = await api.catalog()
  registerCatalog(catalog)

  graph = new LGraph()
  lgcanvas = new LGraphCanvas(canvasEl.value, graph)
  resize()
  window.addEventListener('resize', resize)

  overlay = new VideoOverlay(lgcanvas, overlayEl.value)
  shots = new ShotOverlay(lgcanvas, overlayEl.value)
  shots.setRenameHandler(onRenameImage)
  codes = new CodeOverlay(lgcanvas, overlayEl.value)
  const prevForeground = lgcanvas.onDrawForeground
  lgcanvas.onDrawForeground = function (ctx) {
    prevForeground && prevForeground.call(this, ctx)
    reconcileInteractions()   // 连线/连接状态变化时挂载/卸载交互画面
    overlay.update()
    shots.update(graph._nodes)   // 截图节点回显 + 裁剪框定位
    codes.update(graph._nodes)   // 脚本节点多行代码编辑器
  }
  setDeviceActionHandler(onDeviceAction)
  setCaptureHandler(onCapture)
  setImageActionHandler(onImageAction)

  graph.start()
  projects.value = await api.listProjects()
  status.value = '就绪'
})

function resize() {
  const r = stage.value.getBoundingClientRect()
  canvasEl.value.width = r.width
  canvasEl.value.height = r.height
  lgcanvas && lgcanvas.resize(r.width, r.height)
}

async function newProject() {
  const name = prompt('工程名')
  if (!name) return
  try {
    await api.createProject(name)
    projects.value = await api.listProjects()
    current.value = name
    await openProject()
  } catch (e) { alert('新建失败: ' + e.message) }
}

async function openProject() {
  if (!current.value) return
  // 关闭所有设备连接与交互画面
  for (const node of graph._nodes.slice()) {
    if (node._conn) { try { await node._conn.close() } catch (e) {} node._conn = null }
    overlay.detach(node)
  }
  const data = await api.loadFlow(current.value)
  graph.configure(data)
  reloadShots()
  status.value = `已打开 ${current.value}`
}

// 工程打开后，把截图节点的帧 / 模板图片节点的图重新载入回显。
function reloadShots() {
  for (const node of graph._nodes) {
    const t = node._spec?.type
    if (t === 'vision/screenshot' && node.properties?.image) {
      shots.setImage(node, api.imageUrl(current.value, node.properties.image))
    } else if (t === 'const/image' && node.properties?.name) {
      shots.setImage(node, api.imageUrl(current.value, node.properties.name))
    }
  }
}

// 模板图片：本地上传 / 剪贴板粘贴 → 存到 images/ 并回显，写入 properties.name。
async function onImageAction(node, mode) {
  if (!current.value) { alert('请先打开工程'); return }
  try {
    const file = mode === 'paste' ? await readClipboardImage() : await pickLocalImage()
    if (!file) return
    const ext = (file.type.split('/')[1] || 'png').replace('jpeg', 'jpg')
    // 弹框指定名称（上传默认用原文件名，粘贴默认 tpl_<id>）
    const suggested = mode === 'paste'
      ? `tpl_${node.id}` : (file.name ? file.name.replace(/\.[^.]+$/, '') : `tpl_${node.id}`)
    const input = prompt('图片名称', suggested)
    if (input === null) return                       // 取消
    let fname = input.trim() || suggested
    if (!/\.[a-z0-9]+$/i.test(fname)) fname += '.' + ext   // 无扩展名则补上
    const r = await api.uploadImage(current.value, file, fname)
    node.properties.name = r.name
    shots.setImage(node, api.imageUrl(current.value, r.name), { fit: true })
    status.value = `已设置模板 ${r.name}`
  } catch (e) {
    alert('设置模板失败: ' + e.message)
  }
}

// 重命名图片：改 images/ 里的文件名并更新节点引用与回显
async function onRenameImage(node, newName) {
  const key = node._spec?.type === 'const/image' ? 'name' : 'image'
  const old = node.properties?.[key]
  if (!old) return
  const r = await api.renameImage(current.value, old, newName)
  node.properties[key] = r.name
  shots.setImage(node, api.imageUrl(current.value, r.name))
  status.value = `已重命名为 ${r.name}`
}

// 弹系统文件选择器取一张本地图片
function pickLocalImage() {
  return new Promise((resolve) => {
    const inp = document.createElement('input')
    inp.type = 'file'; inp.accept = 'image/*'
    inp.onchange = () => resolve(inp.files && inp.files[0])
    inp.click()
  })
}

// 从剪贴板读取一张图片（需 https 或 localhost，且用户授权）
async function readClipboardImage() {
  if (!navigator.clipboard?.read) throw new Error('当前环境不支持读取剪贴板，请用上传')
  const items = await navigator.clipboard.read()
  for (const it of items) {
    const type = it.types.find(t => t.startsWith('image/'))
    if (type) return await it.getType(type)
  }
  throw new Error('剪贴板里没有图片')
}

async function save() {
  await api.saveFlow(current.value, graph.serialize())
  status.value = `已保存 ${current.value}（${new Date().toLocaleTimeString()}）`
}

const STATUS_COLOR = { running: '#b58900', ok: '#2a7d4f', fail: '#c0392b', skip: '#555' }

function resetNodeColors() {
  for (const n of graph._nodes) { n.color = null; n.bgcolor = null }
  lgcanvas.setDirty(true, true)
}

function setNodeStatus(id, st) {
  const n = graph.getNodeById(id)
  if (!n) return
  n.color = STATUS_COLOR[st] || null
  lgcanvas.setDirty(true, true)
}

function run() {
  if (!current.value || running.value) return
  resetNodeColors()
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${location.host}/ws/run/${current.value}`)
  runWs = ws
  ws.onopen = () => {
    running.value = true
    status.value = '运行中…'
    ws.send(JSON.stringify({ cmd: 'run', graph: graph.serialize() }))
  }
  ws.onmessage = (e) => {
    const m = JSON.parse(e.data)
    if (m.type === 'node') setNodeStatus(m.id, m.status)
    else if (m.type === 'alert') showToast(m.message, m.level)
    else if (m.type === 'run' && m.status === 'done') {
      const r = m.report
      status.value = `运行完成：${r.passed ? '✅ 通过' : '❌ 失败 ' + r.failed + '/' + r.total}（${r.duration}s）`
      if (m.report_url) lastResult.value = { report_url: m.report_url, junit_url: m.junit_url, pdf_url: m.pdf_url }
      finishRun()
    } else if (m.type === 'run' && (m.status === 'error')) {
      status.value = '运行错误：' + (m.error || '')
      finishRun()
    }
  }
  ws.onclose = () => finishRun()
  ws.onerror = () => { status.value = '运行连接出错'; finishRun() }
}

function stop() {
  if (runWs && runWs.readyState === WebSocket.OPEN) runWs.send(JSON.stringify({ cmd: 'stop' }))
}

function finishRun() {
  running.value = false
  if (runWs) { try { runWs.close() } catch (e) {} runWs = null }
}

// 设备节点「连接/断开」：仅建立/关闭设备会话（视频源），不负责显示与控制。
async function onDeviceAction(node) {
  if (node._conn) {
    const conn = node._conn
    node._conn = null
    reconcileInteractions()        // 卸载显示此设备的交互画面
    try { await conn.close() } catch (e) {}
    status.value = '已断开'
    return
  }
  const kind = node._spec.type.split('/')[1] // device/local -> local
  const conn = new DeviceConnection()
  status.value = '连接中…'
  try {
    const dev = await conn.connect(kind, { ...node.properties }, current.value, node.id)
    node._conn = conn
    reconcileInteractions()        // 挂载到已连线的交互节点
    status.value = `已连接 ${kind} ${dev.width}x${dev.height}`
  } catch (e) {
    try { await conn.close() } catch (_) {}
    alert('连接失败: ' + e.message)
    status.value = '连接失败'
  }
}

// 顺着 video 输入往上游走，找到提供视频的设备连接（设备节点 _conn）。
function connFeeding(node) {
  let cur = node, guard = 0
  while (cur && guard++ < 20) {
    if (cur._conn) return cur._conn
    const slot = (cur.inputs || []).findIndex(i => i.name === 'video')
    cur = slot >= 0 ? cur.getInputNode(slot) : null
  }
  return null
}

// 视频截图：抓上游设备当前帧，存到工程 images/。
async function onCapture(node) {
  if (!current.value) { alert('请先打开工程'); return }
  const conn = connFeeding(node)
  if (!conn || !conn.stream) { alert('该截图节点未接入已连接的设备视频'); return }
  status.value = '截图中…'
  try {
    const blob = await conn.grabBlob()
    const fname = `shot_${node.id}_${Date.now()}.png`
    const r = await api.uploadImage(current.value, blob, fname)
    node.properties.image = r.name
    node.properties.crop = null
    shots.setImage(node, api.imageUrl(current.value, r.name), { fit: true })   // 回显 + 适配卡片尺寸
    status.value = `已截图 ${r.name}`
  } catch (e) {
    alert('截图失败: ' + e.message)
    status.value = '截图失败'
  }
}

// 找人机交互节点上游的设备节点（经 Video 连线）。
function upstreamDevice(node) {
  const slot = (node.inputs || []).findIndex(i => i.name === 'video')
  if (slot >= 0) {
    const up = node.getInputNode(slot)
    if (up && up._spec?.category === '设备') return up
  }
  return null
}

// 把每个人机交互节点的画面/控制对齐到其上游设备当前的连接状态。
function reconcileInteractions() {
  if (!graph) return
  for (const node of graph._nodes) {
    if (node._spec?.type !== 'io/interaction') continue
    const conn = upstreamDevice(node)?._conn || null
    if (overlay.connOf(node) !== conn) {
      overlay.detach(node)
      if (conn) overlay.attach(node, conn)
    }
  }
}
</script>

<style>
html, body, #app { height: 100%; margin: 0; }
.app { display: flex; flex-direction: column; height: 100vh; font-family: sans-serif; }
.toolbar { display: flex; gap: 8px; align-items: center; padding: 6px 10px; background: #2b2b2b; color: #eee; }
.toolbar select, .toolbar button { padding: 3px 8px; }
.toolbar .dl { color: #6cf; font-size: 12px; text-decoration: underline; }
.toolbar .status { margin-left: auto; color: #9c9; font-size: 12px; }
.stage { position: relative; flex: 1; overflow: hidden; }
.graph { position: absolute; inset: 0; }
.overlay { position: absolute; inset: 0; pointer-events: none; }
.overlay > video { pointer-events: auto; }

.toasts { position: absolute; top: 12px; left: 50%; transform: translateX(-50%);
  display: flex; flex-direction: column; gap: 6px; z-index: 200; pointer-events: none; }
.toast { min-width: 200px; max-width: 420px; padding: 8px 14px; border-radius: 6px;
  color: #fff; font-size: 13px; box-shadow: 0 2px 8px rgba(0,0,0,.4);
  background: #2b6cb0; }
.toast.warn { background: #b7791f; }
.toast.error { background: #c0392b; }

.drawer { position: absolute; top: 0; right: 0; width: 380px; height: 100%;
  background: #1f1f1f; color: #ddd; box-shadow: -2px 0 8px rgba(0,0,0,.5);
  display: flex; flex-direction: column; z-index: 100; font-size: 13px; }
.drawer-head { display: flex; justify-content: space-between; align-items: center;
  padding: 8px 10px; background: #2b2b2b; }
.drawer-head button { background: none; color: #ccc; border: none; font-size: 18px; cursor: pointer; }
.drawer-body { display: flex; flex-direction: column; overflow: auto; padding: 8px; gap: 8px; }
.head-actions { display: flex; align-items: center; gap: 6px; }
.head-actions .clear { background: #5a2a2a; color: #f4c7c7; border: none;
  border-radius: 4px; padding: 2px 8px; cursor: pointer; font-size: 12px; }
.runs { list-style: none; margin: 0; padding: 0; max-height: 140px; overflow: auto;
  border: 1px solid #333; }
.runs li { padding: 4px 8px; cursor: pointer; border-bottom: 1px solid #2a2a2a;
  display: flex; align-items: center; gap: 6px; }
.runs li.active { background: #335; }
.runs li.empty { color: #777; cursor: default; }
.runs .rname { flex: 1; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.runs .del { background: none; border: none; color: #c88; cursor: pointer;
  font-size: 13px; opacity: .6; }
.runs li:hover .del { opacity: 1; }
.rsum { font-weight: bold; padding: 4px 0; }
.rsum.ok { color: #5c6; } .rsum.fail { color: #e66; }
.dls a { color: #6cf; margin-right: 10px; text-decoration: underline; }
.atable { width: 100%; border-collapse: collapse; margin-top: 6px; }
.atable td { border-bottom: 1px solid #2a2a2a; padding: 2px 4px; }
.atable tr.ok td:first-child { color: #5c6; } .atable tr.fail td:first-child { color: #e66; }
.evid { margin-top: 6px; } .evid .ecap { color: #e88; margin-bottom: 2px; }
.evid img { max-width: 100%; border: 1px solid #444; }
.logs { background: #111; padding: 6px; overflow: auto; white-space: pre-wrap; color: #9b9; }
</style>
