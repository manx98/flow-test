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
      <button @click="locateGraph" title="居中适配所有节点">⊹ 定位</button>
      <template v-if="lastResult">
        <a v-if="lastResult.pdf_url" :href="lastResult.pdf_url" target="_blank" class="dl">报告PDF</a>
        <a :href="lastResult.report_url" target="_blank" class="dl">JSON</a>
        <a :href="lastResult.junit_url" target="_blank" class="dl">JUnit</a>
      </template>
      <span class="status">{{ status }}</span>
    </div>
    <div class="body">
      <div class="palette" :class="{ closed: !paletteOpen }">
        <div class="palette-head">
          <span v-if="paletteOpen">组件</span>
          <button class="pal-toggle" :title="paletteOpen ? '收起' : '展开'" @click="togglePalette">
            {{ paletteOpen ? '⟨' : '⟩' }}
          </button>
        </div>
        <div v-if="paletteOpen" class="palette-body">
          <div v-for="(items, cat) in categories" :key="cat" class="pal-cat">
            <div class="pal-cat-head" @click="toggleCat(cat)">
              <span class="pal-arrow">{{ collapsedCats[cat] ? '▸' : '▾' }}</span>{{ cat }}
            </div>
            <template v-if="!collapsedCats[cat]">
              <div v-for="n in items" :key="n.type" class="pal-item"
                   draggable="true" @dragstart="onNodeDragStart($event, n.type)" :title="n.type">
                {{ n.title }}
              </div>
            </template>
          </div>
        </div>
      </div>

    <div class="stage" ref="stage" @dragover="onCanvasDragOver" @drop="onCanvasDrop">
      <canvas ref="canvasEl" class="graph"></canvas>
      <div ref="overlayEl" class="overlay"></div>

      <div v-if="showCropper" class="crop-modal" @mousedown.self="closeCropper">
        <div class="crop-dialog">
          <div class="crop-head">截图编辑 — 裁剪并命名</div>
          <div class="crop-stage">
            <img ref="cropImgEl" :src="cropperSrc" />
          </div>
          <div class="crop-foot">
            <label>名称 <input v-model="cropName" @keyup.enter="saveCrop" /></label>
            <span class="spacer"></span>
            <button @click="closeCropper">取消</button>
            <button class="primary" @click="saveCrop">保存</button>
          </div>
        </div>
      </div>

      <div v-if="showMask" class="crop-modal" @mousedown.self="closeMask">
        <div class="crop-dialog">
          <div class="crop-head">编辑遮罩 — 涂抹要忽略的区域（白=匹配 / 涂抹=忽略）</div>
          <div class="crop-stage mask-stage">
            <canvas ref="maskCanvasEl"></canvas>
          </div>
          <div class="crop-foot">
            <label>笔刷 <input type="range" min="4" max="80" v-model.number="maskBrush" @input="onMaskBrush" /></label>
            <button @click="clearMask">清除</button>
            <span class="spacer"></span>
            <button @click="closeMask">取消</button>
            <button class="primary" @click="saveMask">保存</button>
          </div>
        </div>
      </div>

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
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, ref } from 'vue'
import { LGraph, LGraphCanvas, LiteGraph } from 'litegraph.js'
import Cropper from 'cropperjs'
import 'cropperjs/dist/cropper.css'
import { fabric } from 'fabric'
import { api } from './api.js'
import { registerCatalog, setDeviceActionHandler, setCaptureHandler, setImageActionHandler, setMaskActionHandler } from './graph/litegraph-setup.js'
import { VideoOverlay } from './graph/video-overlay.js'
import { ShotOverlay } from './graph/shot-overlay.js'
import { CodeOverlay } from './graph/code-overlay.js'
import { ErrorOverlay } from './graph/error-overlay.js'
import { AgentTraceOverlay } from './graph/agent-overlay.js'
import { DeviceConnection } from './webrtc/device.js'

const projects = ref([])
const current = ref('')
const status = ref('')

// 组件栏（侧边可折叠节点面板）
const paletteOpen = ref(true)
const catalogNodes = ref([])
const collapsedCats = ref({})
const categories = computed(() => {
  const g = {}
  for (const n of catalogNodes.value) (g[n.category || '其它'] ||= []).push(n)
  return g
})
function toggleCat(cat) { collapsedCats.value = { ...collapsedCats.value, [cat]: !collapsedCats.value[cat] } }
function togglePalette() {
  paletteOpen.value = !paletteOpen.value
  nextTick(() => { resize(); lgcanvas && lgcanvas.draw(true, true) })   // 布局更新后重算画布并强制重绘
}

// 居中适配：把所有节点框进视图（空图则回到原点 1:1）
function locateGraph() {
  if (!graph || !lgcanvas) return
  const ds = lgcanvas.ds
  const r = stage.value.getBoundingClientRect()
  const nodes = graph._nodes || []
  if (!nodes.length) {
    ds.offset[0] = 0; ds.offset[1] = 0; ds.scale = 1
    lgcanvas.setDirty(true, true)
    return
  }
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  const th = LiteGraph.NODE_TITLE_HEIGHT || 20
  for (const n of nodes) {
    minX = Math.min(minX, n.pos[0]); minY = Math.min(minY, n.pos[1] - th)
    maxX = Math.max(maxX, n.pos[0] + n.size[0]); maxY = Math.max(maxY, n.pos[1] + n.size[1])
  }
  const pad = 40
  const bw = Math.max(1, maxX - minX), bh = Math.max(1, maxY - minY)
  const scale = Math.max(0.1, Math.min((r.width - pad * 2) / bw, (r.height - pad * 2) / bh, 1.2))
  ds.scale = scale
  ds.offset[0] = (r.width / 2) / scale - (minX + maxX) / 2
  ds.offset[1] = (r.height / 2) / scale - (minY + maxY) / 2
  lgcanvas.setDirty(true, true)
}
function onNodeDragStart(ev, type) {
  ev.dataTransfer.setData('text/node-type', type)
  ev.dataTransfer.effectAllowed = 'copy'
}
function onCanvasDragOver(ev) { ev.preventDefault(); ev.dataTransfer.dropEffect = 'copy' }
function onCanvasDrop(ev) {
  ev.preventDefault()
  const type = ev.dataTransfer.getData('text/node-type')
  if (!type || !graph) return
  const node = LiteGraph.createNode(type)
  if (!node) return
  // 屏幕坐标 → 画布坐标（overlay 定位公式的逆运算）
  const rect = canvasEl.value.getBoundingClientRect()
  const ds = lgcanvas.ds
  node.pos = [(ev.clientX - rect.left) / ds.scale - ds.offset[0],
              (ev.clientY - rect.top) / ds.scale - ds.offset[1]]
  graph.add(node)
  lgcanvas.setDirty(true, true)
}
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
let errors = null
let agentTrace = null

onMounted(async () => {
  const catalog = await api.catalog()
  registerCatalog(catalog)
  catalogNodes.value = catalog.nodes

  graph = new LGraph()
  lgcanvas = new LGraphCanvas(canvasEl.value, graph)
  resize()
  window.addEventListener('resize', resize)

  overlay = new VideoOverlay(lgcanvas, overlayEl.value)
  shots = new ShotOverlay(lgcanvas, overlayEl.value)
  shots.setRenameHandler(onRenameImage)
  codes = new CodeOverlay(lgcanvas, overlayEl.value)
  errors = new ErrorOverlay(lgcanvas, overlayEl.value)
  agentTrace = new AgentTraceOverlay(lgcanvas, overlayEl.value)
  const prevForeground = lgcanvas.onDrawForeground
  lgcanvas.onDrawForeground = function (ctx) {
    prevForeground && prevForeground.call(this, ctx)
    reconcileInteractions()   // 连线/连接状态变化时挂载/卸载交互画面
    reconcilePreviews()       // 图片预览节点跟随上游图片
    overlay.update()
    shots.update(graph._nodes)   // 截图/模板/预览节点画面 + 裁剪框定位
    codes.update(graph._nodes)   // 脚本节点多行代码编辑器
    errors.update(graph._nodes)  // 运行错误（可选中/可复制）
    agentTrace.update(graph._nodes)   // Agent 展示节点执行过程
  }
  setDeviceActionHandler(onDeviceAction)
  setCaptureHandler(onCapture)
  setImageActionHandler(onImageAction)
  setMaskActionHandler(onMaskEdit)

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

// 工程打开后，把模板图片 / 遮罩节点的图重新载入回显。
function reloadShots() {
  for (const node of graph._nodes) {
    const t = node._spec?.type
    if (t === 'const/image' && node.properties?.name) {
      shots.setImage(node, api.imageUrl(current.value, node.properties.name))
    } else if (t === 'mask/create' && node.properties?.mask) {
      shots.setImage(node, api.imageUrl(current.value, node.properties.mask))
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
  for (const n of graph._nodes) { n.color = null; n.bgcolor = null; n._error = null }
  lgcanvas.setDirty(true, true)
}

function setNodeStatus(id, st, info) {
  const n = graph.getNodeById(id)
  if (!n) return
  n.color = STATUS_COLOR[st] || null
  // fail 有消息=触发节点(标红+展示错误)；无消息=链路上层(只标红，不展示)
  if (st === 'fail') n._error = info || null
  else if (st === 'running' || st === 'ok') n._error = null   // 重跑到此节点时清旧错误
  lgcanvas.setDirty(true, true)
}

function run() {
  if (!current.value || running.value) return
  resetNodeColors()
  if (shots) shots.clearMatches()   // 清掉上次运行的找图/找文字/等出现结果回显
  if (agentTrace) agentTrace.clearAll()   // 清掉上次 Agent 执行过程
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
    if (m.type === 'node') setNodeStatus(m.id, m.status, m.info)
    else if (m.type === 'alert') showToast(m.message, m.level)
    else if (m.type === 'node_shot') {   // 找图/找文字/等出现：回显带命中框的画面
      const n = graph.getNodeById(m.id)
      if (n) shots.setImage(n, m.url, { fit: true })
    }
    else if (m.type === 'agent_step') agentTrace.onStep(m.id, m)   // Agent 每步过程
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

// 人机交互节点截图：抓当前帧 → 打开 Cropper 裁剪/命名弹框（交互节点的设备连接即 overlay.connOf）。
async function onCapture(node) {
  if (!current.value) { alert('请先打开工程'); return }
  const conn = overlay.connOf(node)
  if (!conn || !conn.stream) { alert('该交互节点未接入已连接的设备视频'); return }
  try {
    const canvas = await conn.grabFrame()
    openCropper(canvas.toDataURL('image/png'), node)
  } catch (e) {
    alert('截图失败: ' + e.message)
  }
}

// ---- 截图裁剪弹框（Cropper.js）----
const showCropper = ref(false)
const cropperSrc = ref('')
const cropName = ref('')
const cropImgEl = ref(null)
let cropper = null
let cropAnchor = null   // 触发截图的交互节点，用于放置新建的模板节点

async function openCropper(dataUrl, node) {
  cropperSrc.value = dataUrl
  cropName.value = `shot_${Date.now()}`
  cropAnchor = node
  showCropper.value = true
  await nextTick()
  if (cropper) { cropper.destroy(); cropper = null }
  const img = cropImgEl.value
  const init = () => {
    cropper = new Cropper(img, { viewMode: 1, autoCropArea: 0.85, background: false })
  }
  // 等图片加载完再初始化，否则 Cropper 按未就绪尺寸建容器，右侧手柄会被裁掉
  if (img.complete && img.naturalWidth) init()
  else img.onload = init
}

function closeCropper() {
  if (cropper) { cropper.destroy(); cropper = null }
  showCropper.value = false
  cropperSrc.value = ''
  cropAnchor = null
}

async function saveCrop() {
  if (!cropper) return
  let name = (cropName.value || `shot_${Date.now()}`).trim()
  if (!/\.[a-z0-9]+$/i.test(name)) name += '.png'
  try {
    const canvas = cropper.getCroppedCanvas()
    const blob = await new Promise((res, rej) =>
      canvas.toBlob((b) => b ? res(b) : rej(new Error('裁剪失败')), 'image/png'))
    const r = await api.uploadImage(current.value, blob, name)
    // 创建模板图片节点，放在触发截图的交互节点右侧
    const n = LiteGraph.createNode('const/image')
    n.properties.name = r.name
    const a = cropAnchor
    n.pos = a ? [a.pos[0] + a.size[0] + 40, a.pos[1]] : [120, 120]
    graph.add(n)
    shots.setImage(n, api.imageUrl(current.value, r.name), { fit: true })
    status.value = `已创建模板图片 ${r.name}`
    closeCropper()
  } catch (e) {
    alert('保存失败: ' + e.message)
  }
}

// ---- 遮罩编辑弹框（Fabric.js）----
const showMask = ref(false)
const maskBrush = ref(24)
const maskCanvasEl = ref(null)
let fcanvas = null
let maskAnchor = null
let maskW = 0, maskH = 0   // 模板原生尺寸（导出用）

// 创建遮罩节点「编辑遮罩」：取 picture 上游模板图为底，打开画板涂抹要忽略的区域
async function onMaskEdit(node) {
  if (!current.value) { alert('请先打开工程'); return }
  const slot = (node.inputs || []).findIndex(i => i.name === 'picture')
  const src = slot >= 0 ? pictureSource(node.getInputNode(slot)) : null
  if (!src) { alert('请先在 picture 输入连接一个模板图片'); return }
  maskAnchor = node
  showMask.value = true
  await nextTick()
  const img = await loadImage(api.imageUrl(current.value, src.name))
  maskW = img.naturalWidth; maskH = img.naturalHeight
  // 画布用固定可见区（铺满弹框），与图片原生尺寸解耦，避免低高度图片编辑区过窄
  const stageEl = maskCanvasEl.value.parentElement
  const vw = Math.max(240, stageEl.clientWidth)
  const vh = Math.max(240, stageEl.clientHeight)
  fcanvas = new fabric.Canvas(maskCanvasEl.value, { isDrawingMode: true })
  fcanvas.setWidth(vw); fcanvas.setHeight(vh)
  fcanvas.freeDrawingBrush.width = maskBrush.value
  fcanvas.freeDrawingBrush.color = 'rgba(255,40,40,0.5)'
  fabric.Image.fromURL(img.src, (im) => {
    fcanvas.setBackgroundImage(im, fcanvas.requestRenderAll.bind(fcanvas))
    const z = Math.min(vw / maskW, vh / maskH)   // fit 初始缩放并居中
    fcanvas.setZoom(z)
    fcanvas.viewportTransform[4] = (vw - maskW * z) / 2
    fcanvas.viewportTransform[5] = (vh - maskH * z) / 2
    fcanvas.requestRenderAll()
  })
  _bindMaskNav()
}

// 滚轮以光标为锚点缩放；右键/Alt 拖拽平移
function _bindMaskNav() {
  fcanvas.on('mouse:wheel', (opt) => {
    const e = opt.e
    let z = fcanvas.getZoom() * (0.999 ** e.deltaY)
    z = Math.min(20, Math.max(0.05, z))
    fcanvas.zoomToPoint({ x: e.offsetX, y: e.offsetY }, z)
    e.preventDefault(); e.stopPropagation()
  })
  let panning = false, lx = 0, ly = 0
  fcanvas.on('mouse:down', (opt) => {
    if (opt.e.button === 2 || opt.e.altKey) {
      panning = true; fcanvas.isDrawingMode = false
      lx = opt.e.clientX; ly = opt.e.clientY
    }
  })
  fcanvas.on('mouse:move', (opt) => {
    if (!panning) return
    const vpt = fcanvas.viewportTransform
    vpt[4] += opt.e.clientX - lx; vpt[5] += opt.e.clientY - ly
    lx = opt.e.clientX; ly = opt.e.clientY
    fcanvas.requestRenderAll()
  })
  fcanvas.on('mouse:up', () => { if (panning) { panning = false; fcanvas.isDrawingMode = true } })
  fcanvas.upperCanvasEl.addEventListener('contextmenu', (e) => e.preventDefault())
}

function onMaskBrush() { if (fcanvas) fcanvas.freeDrawingBrush.width = maskBrush.value }
function clearMask() {
  if (!fcanvas) return
  fcanvas.getObjects().slice().forEach((o) => fcanvas.remove(o))
  fcanvas.requestRenderAll()
}
function closeMask() {
  if (fcanvas) { try { fcanvas.dispose() } catch (_) {} fcanvas = null }
  showMask.value = false
  maskAnchor = null
}

// 保存：白底 + 涂抹处黑（255 参与匹配 / 0 忽略），按原生分辨率导出，上传并回显
async function saveMask() {
  if (!fcanvas || !maskAnchor) return
  const w = maskW, h = maskH
  try {
    // 重置视图/尺寸到原生、去背景，导出仅笔迹（与原生分辨率对齐）
    const vpt = fcanvas.viewportTransform.slice()
    const cw = fcanvas.getWidth(), ch = fcanvas.getHeight()
    const bg = fcanvas.backgroundImage
    fcanvas.setBackgroundImage(null)
    fcanvas.setViewportTransform([1, 0, 0, 1, 0, 0])
    fcanvas.setWidth(w); fcanvas.setHeight(h)
    fcanvas.requestRenderAll()
    const strokesUrl = fcanvas.toDataURL({ format: 'png' })
    fcanvas.setWidth(cw); fcanvas.setHeight(ch)
    fcanvas.setViewportTransform(vpt)
    fcanvas.setBackgroundImage(bg, fcanvas.requestRenderAll.bind(fcanvas))
    const strokes = await loadImage(strokesUrl)

    const c = document.createElement('canvas'); c.width = w; c.height = h
    const cx = c.getContext('2d')
    cx.fillStyle = '#fff'; cx.fillRect(0, 0, w, h)
    const t = document.createElement('canvas'); t.width = w; t.height = h
    const tctx = t.getContext('2d'); tctx.drawImage(strokes, 0, 0, w, h)
    const sd = tctx.getImageData(0, 0, w, h).data
    const out = cx.getImageData(0, 0, w, h)
    for (let i = 0; i < sd.length; i += 4) {
      if (sd[i + 3] > 20) { out.data[i] = out.data[i + 1] = out.data[i + 2] = 0 }  // 涂抹处=黑(忽略)
    }
    cx.putImageData(out, 0, 0)

    const blob = await new Promise((res, rej) =>
      c.toBlob((b) => b ? res(b) : rej(new Error('生成遮罩失败')), 'image/png'))
    const name = `mask_${maskAnchor.id}_${Date.now()}.png`
    const r = await api.uploadImage(current.value, blob, name)
    maskAnchor.properties.mask = r.name
    shots.setImage(maskAnchor, api.imageUrl(current.value, r.name), { fit: true })
    status.value = `已保存遮罩 ${r.name}`
    closeMask()
  } catch (e) {
    alert('保存遮罩失败: ' + e.message)
  }
}

// 顺着图片来源解析出 { name }（模板图片 / 预览透传）
function pictureSource(node, depth = 0) {
  if (!node || depth > 20) return null
  const t = node._spec?.type
  if (t === 'const/image') return node.properties?.name ? { name: node.properties.name, crop: null } : null
  if (t === 'vision/preview') {
    const s = (node.inputs || []).findIndex(i => i.name === 'picture')
    return s >= 0 ? pictureSource(node.getInputNode(s), depth + 1) : null
  }
  return null
}

function loadImage(url) {
  return new Promise((res, rej) => { const i = new Image(); i.onload = () => res(i); i.onerror = rej; i.src = url })
}

// 把图片裁剪区域生成 dataURL（带缓存）
const _cropCache = new Map()
async function croppedSource(name, crop) {
  const key = `${name}|${crop.x},${crop.y},${crop.w},${crop.h}`
  if (_cropCache.has(key)) return _cropCache.get(key)
  const img = await loadImage(api.imageUrl(current.value, name))
  const cvs = document.createElement('canvas')
  cvs.width = crop.w; cvs.height = crop.h
  cvs.getContext('2d').drawImage(img, crop.x, crop.y, crop.w, crop.h, 0, 0, crop.w, crop.h)
  const data = cvs.toDataURL('image/png')
  if (_cropCache.size > 50) _cropCache.delete(_cropCache.keys().next().value)
  _cropCache.set(key, data)
  return data
}

// 图片预览节点：跟随其 picture 上游显示对应图片（截图带裁剪则显示裁剪区域）
function reconcilePreviews() {
  if (!graph || !shots) return
  for (const node of graph._nodes) {
    if (node._spec?.type !== 'vision/preview') continue
    const s = (node.inputs || []).findIndex(i => i.name === 'picture')
    const src = s >= 0 ? pictureSource(node.getInputNode(s)) : null
    const sig = src ? `${src.name}|${src.crop ? `${src.crop.x},${src.crop.y},${src.crop.w},${src.crop.h}` : 'full'}` : ''
    if (node._previewSig === sig) continue
    node._previewSig = sig
    if (!src) { shots.clear(node); continue }
    if (src.crop) {
      croppedSource(src.name, src.crop)
        .then((d) => { if (node._previewSig === sig) shots.setImage(node, d) })
        .catch(() => {})
    } else {
      shots.setImage(node, api.imageUrl(current.value, src.name))
    }
  }
}

// 找人机交互节点上游的设备源节点（经 device 连线）。
function upstreamDevice(node) {
  const slot = (node.inputs || []).findIndex(i => i.name === 'device')
  if (slot >= 0) {
    const up = node.getInputNode(slot)
    // 设备源节点：device/local 等；排除「设备属性」(device/attrs，它不是源)
    if (up && up._spec?.type?.startsWith('device/') && up._spec.type !== 'device/attrs') return up
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
/* 节点右键菜单需盖过画面区 DOM 覆盖层（脚本编辑器 z-index:45、错误条 60 等），否则会被遮挡 */
.litegraph.litecontextmenu { z-index: 1000 !important; }
.app { display: flex; flex-direction: column; height: 100vh; font-family: sans-serif; }
.toolbar { display: flex; gap: 8px; align-items: center; padding: 6px 10px; background: #2b2b2b; color: #eee; }
.toolbar select, .toolbar button { padding: 3px 8px; }
.toolbar .dl { color: #6cf; font-size: 12px; text-decoration: underline; }
.toolbar .status { margin-left: auto; color: #9c9; font-size: 12px; }
.body { display: flex; flex: 1; min-height: 0; }
.palette { width: 180px; background: #232323; color: #ddd; display: flex; flex-direction: column;
  border-right: 1px solid #111; flex-shrink: 0; }
.palette.closed { width: 26px; }
.palette-head { display: flex; align-items: center; justify-content: space-between;
  padding: 6px 8px; background: #2b2b2b; font-size: 13px; }
.pal-toggle { background: none; border: none; color: #ccc; cursor: pointer; font-size: 14px; padding: 0 2px; }
.palette-body { overflow: auto; flex: 1; }
.pal-cat-head { padding: 5px 8px; font-size: 12px; color: #9cc; cursor: pointer; user-select: none;
  background: #282828; border-top: 1px solid #1c1c1c; }
.pal-arrow { display: inline-block; width: 12px; color: #888; }
.pal-item { padding: 4px 8px 4px 22px; font-size: 12px; cursor: grab; border-bottom: 1px solid #262626; }
.pal-item:hover { background: #314050; }
.pal-item:active { cursor: grabbing; }
.stage { position: relative; flex: 1; overflow: hidden; background: #1e1e1e; }
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

/* 截图裁剪弹框 */
.crop-modal { position: absolute; inset: 0; z-index: 300; background: rgba(0,0,0,.6);
  display: flex; align-items: center; justify-content: center; }
.crop-dialog { width: min(820px, 90%); max-height: 88%; background: #1f1f1f; color: #ddd;
  border-radius: 6px; display: flex; flex-direction: column; box-shadow: 0 8px 30px rgba(0,0,0,.6); }
.crop-head { padding: 8px 12px; background: #2b2b2b; font-size: 13px; border-radius: 6px 6px 0 0; }
.crop-stage { flex: 1; min-height: 0; padding: 10px; overflow: hidden; background: #111;
  display: flex; align-items: center; justify-content: center; }
/* Cropper 会接管 img 的盒子；限制最大尺寸，保证容器(含右/下手柄)落在可视区内 */
.crop-stage img { display: block; max-width: 100%; max-height: 58vh; }
.crop-stage .cropper-container { max-width: 100%; }
.mask-stage { display: block; padding: 0; overflow: hidden; height: min(460px, 60vh); width: 100%; }
.crop-foot { display: flex; align-items: center; gap: 8px; padding: 8px 12px; background: #262626; }
.crop-foot .spacer { flex: 1; }
.crop-foot input { background: #111; color: #eee; border: 1px solid #444; border-radius: 4px;
  padding: 3px 6px; }
.crop-foot button { padding: 4px 12px; }
.crop-foot .primary { background: #2b6cb0; color: #fff; border: none; border-radius: 4px; cursor: pointer; }
</style>
