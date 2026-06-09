<template>
  <div class="app">
    <div class="toolbar">
      <strong>flow-test</strong>
      <select v-model="current" @change="openProject">
        <option value="" disabled>{{ t('app.projectPlaceholder') }}</option>
        <option v-for="p in projects" :key="p" :value="p">{{ p }}</option>
      </select>
      <button @click="newProject">{{ t('app.toolbar.newProject') }}</button>
      <button class="icon-btn" @click="undoGraph" :disabled="!canUndo" :title="t('app.toolbar.undoTitle')">↶</button>
      <button class="icon-btn" @click="redoGraph" :disabled="!canRedo" :title="t('app.toolbar.redoTitle')">↷</button>
      <button @click="save" :disabled="!current">{{ t('app.toolbar.save') }}</button>
      <button @click="run" :disabled="!current || running">▶ {{ t('app.toolbar.run') }}</button>
      <button @click="stop" :disabled="!running">■ {{ t('app.toolbar.stop') }}</button>
      <button @click="openHistory" :disabled="!current">{{ t('app.toolbar.history') }}</button>
      <button @click="openSettings">{{ t('app.toolbar.settings') }}</button>
      <button @click="openAiBuilder" :disabled="!current">{{ t('app.toolbar.aiBuilder') }}</button>
      <button class="locate-btn" @click="locateGraph" :title="t('app.toolbar.locateTitle')">{{ t('app.toolbar.locate') }}</button>
      <select class="lang-select" :value="locale" @change="changeLocale($event.target.value)">
        <option v-for="lang in languages" :key="lang.code" :value="lang.code">{{ lang.label }}</option>
      </select>
      <template v-if="lastResult">
        <a v-if="lastResult.pdf_url" :href="lastResult.pdf_url" target="_blank" class="dl">{{ t('app.reports.pdf') }}</a>
        <a :href="lastResult.report_url" target="_blank" class="dl">JSON</a>
        <a :href="lastResult.junit_url" target="_blank" class="dl">JUnit</a>
      </template>
      <span class="status">{{ status }}</span>
    </div>
    <div class="body">
      <div class="palette" :class="{ closed: !paletteOpen }">
        <div class="palette-head">
          <span v-if="paletteOpen">{{ t('app.palette.title') }}</span>
          <button class="pal-toggle" :title="paletteOpen ? t('app.palette.collapse') : t('app.palette.expand')" @click="togglePalette">
            {{ paletteOpen ? '⟨' : '⟩' }}
          </button>
        </div>
        <div v-if="paletteOpen" class="palette-body">
          <div v-for="(items, cat) in categories" :key="cat" class="pal-cat">
            <div class="pal-cat-head" @click="toggleCat(cat)">
              <span class="pal-arrow">{{ collapsedCats[cat] ? '▸' : '▾' }}</span>{{ categoryLabel(cat) }}
            </div>
            <template v-if="!collapsedCats[cat]">
              <div v-for="n in items" :key="n.type" class="pal-item"
                   draggable="true" @dragstart="onNodeDragStart($event, n.type)" :title="n.type">
                {{ nodeTitle(n) }}
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
          <div class="crop-head">{{ t('app.crop.title') }}</div>
          <div class="crop-stage">
            <img ref="cropImgEl" :src="cropperSrc" />
          </div>
          <div class="crop-foot">
            <label>{{ t('app.crop.name') }} <input v-model="cropName" @keyup.enter="saveCrop" /></label>
            <span class="spacer"></span>
            <button @click="closeCropper">{{ t('app.common.cancel') }}</button>
            <button class="primary" @click="saveCrop">{{ t('app.common.save') }}</button>
          </div>
        </div>
      </div>

      <div v-if="showMask" class="crop-modal" @mousedown.self="closeMask">
        <div class="crop-dialog">
          <div class="crop-head">{{ t('app.mask.title') }}</div>
          <div class="crop-stage mask-stage">
            <canvas ref="maskCanvasEl"></canvas>
          </div>
          <div class="crop-foot">
            <label>{{ t('app.mask.brush') }} <input type="range" min="4" max="80" v-model.number="maskBrush" @input="onMaskBrush" /></label>
            <button @click="clearMask">{{ t('app.mask.clear') }}</button>
            <span class="spacer"></span>
            <button @click="closeMask">{{ t('app.common.cancel') }}</button>
            <button class="primary" @click="saveMask">{{ t('app.common.save') }}</button>
          </div>
        </div>
      </div>

      <div v-if="showSettings" class="settings-modal" @mousedown.self="closeSettings">
        <div class="settings-dialog">
          <div class="settings-head">{{ t('app.settings.title') }}</div>
          <div class="settings-body">
            <div class="settings-section">{{ t('app.settings.connectionSection') }}</div>
            <label>
              <span>{{ t('app.settings.rdpConnectTimeout') }}</span>
              <input type="number" min="5" max="300" step="5" v-model.number="settingsDraft.rdp_connect_timeout" />
            </label>
            <label>
              <span>{{ t('app.settings.rdpFirstUpdateTimeout') }}</span>
              <input type="number" min="5" max="300" step="5" v-model.number="settingsDraft.rdp_first_update_timeout" />
            </label>
            <div class="settings-section">{{ t('app.settings.aiBuilderSection') }}</div>
            <label>
              <span>{{ t('app.settings.aiProvider') }}</span>
              <select v-model="settingsDraft.ai_builder.provider">
                <option value="openai">openai</option>
                <option value="ollama">ollama</option>
                <option value="custom">custom</option>
              </select>
            </label>
            <label>
              <span>{{ t('app.settings.aiBaseUrl') }}</span>
              <input v-model="settingsDraft.ai_builder.base_url" />
            </label>
            <label>
              <span>{{ t('app.settings.aiModel') }}</span>
              <input v-model="settingsDraft.ai_builder.model" />
            </label>
            <label>
              <span>{{ t('app.settings.aiApiKey') }}</span>
              <input type="password" v-model="settingsDraft.ai_builder.api_key" />
            </label>
            <label>
              <span>{{ t('app.settings.aiTemperature') }}</span>
              <input type="number" min="0" max="2" step="0.1" v-model.number="settingsDraft.ai_builder.temperature" />
            </label>
          </div>
          <div class="settings-foot">
            <button @click="closeSettings">{{ t('app.common.cancel') }}</button>
            <button class="primary" @click="saveSettings">{{ t('app.common.save') }}</button>
          </div>
        </div>
      </div>

      <div class="toasts">
        <div v-for="t in toasts" :key="t.id" class="toast" :class="t.level">
          {{ t.message }}
        </div>
      </div>

      <div v-if="showHistory" class="history-modal" @mousedown.self="showHistory = false">
        <div class="history-dialog">
          <div class="history-head">
            <span>{{ t('app.history.title') }} - {{ current }}</span>
            <span class="head-actions">
              <button v-if="runs.length" class="clear" @click="clearRuns">{{ t('app.history.clear') }}</button>
              <button @click="showHistory = false">×</button>
            </span>
          </div>
          <div class="history-body">
            <aside class="history-runs">
              <ul class="runs">
                <li v-for="r in runs" :key="r" :class="{ active: r === selRun }" @click="selectRun(r)">
                  <span class="rname">{{ r }}</span>
                  <button class="del" :title="t('app.history.deleteTitle')" @click.stop="deleteRun(r)">🗑</button>
                </li>
                <li v-if="!runs.length" class="empty">{{ t('app.history.empty') }}</li>
              </ul>
            </aside>
            <section class="history-report">
              <div v-if="report" class="report">
                <div class="rsum" :class="report.passed ? 'ok' : 'fail'">
                  {{ report.passed ? '✅ ' + t('app.history.passed') : '❌ ' + t('app.history.failed') + ' ' + report.failed + '/' + report.total }} · {{ report.duration }}s
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
                  <div class="ecap">{{ t('app.history.evidence') }} · {{ a.message }}</div>
                  <img :src="a.evidence" />
                </div>
                <pre v-if="report.logs && report.logs.length" class="logs">{{ report.logs.join('\n') }}</pre>
              </div>
              <div v-else class="history-empty">{{ runs.length ? t('app.history.selectPrompt') : t('app.history.empty') }}</div>
            </section>
          </div>
        </div>
      </div>

      <div v-if="showAiBuilder" class="drawer ai-builder">
        <div class="drawer-head">
          <span>{{ t('app.aiBuilder.title') }} - {{ current }}</span>
          <button @click="showAiBuilder = false">×</button>
        </div>
        <div class="ai-builder-body">
          <div class="ai-chat">
            <div v-for="(m, idx) in aiMessages" :key="idx" class="ai-msg" :class="m.role">
              <div class="ai-role">{{ m.role === 'user' ? t('app.aiBuilder.user') : t('app.aiBuilder.assistant') }}</div>
              <div v-if="m.content" class="ai-text">{{ m.content }}</div>
              <div v-if="m.files && m.files.length" class="ai-files">
                <span v-for="f in m.files" :key="f">{{ f }}</span>
              </div>
              <div v-if="m.form" class="ai-form">
                <div class="ai-form-title">{{ m.form.title }}</div>
                <div v-if="m.form.description" class="ai-form-desc">{{ m.form.description }}</div>
                <template v-if="m.form.kind === 'device'">
                  <label>
                    <span>{{ t('app.aiBuilder.deviceType') }}</span>
                    <select v-model="m.form.values.type" :disabled="m.form.submitted">
                      <option v-for="d in m.form.devices" :key="d.type" :value="d.type">{{ d.title }}</option>
                    </select>
                  </label>
                  <label v-for="p in deviceFormProps(m.form)" :key="p.name">
                    <span>{{ p.name }}</span>
                    <select v-if="p.type === 'enum'" v-model="m.form.values.properties[p.name]" :disabled="m.form.submitted">
                      <option v-for="opt in p.options || []" :key="opt" :value="opt">{{ opt }}</option>
                    </select>
                    <input v-else-if="p.type === 'bool'" type="checkbox" v-model="m.form.values.properties[p.name]" :disabled="m.form.submitted" />
                    <input v-else :type="formInputType(p.type)" v-model="m.form.values.properties[p.name]" :disabled="m.form.submitted" />
                    <small>{{ p.desc }}</small>
                  </label>
                </template>
                <template v-else>
                  <label v-for="f in m.form.fields" :key="f.name">
                    <span>{{ f.label }}</span>
                    <select v-if="f.type === 'enum'" v-model="m.form.values[f.name]" :disabled="m.form.submitted">
                      <option v-for="opt in f.options || []" :key="opt" :value="opt">{{ opt }}</option>
                    </select>
                    <input v-else-if="f.type === 'bool'" type="checkbox" v-model="m.form.values[f.name]" :disabled="m.form.submitted" />
                    <input v-else :type="formInputType(f.type)" v-model="m.form.values[f.name]" :disabled="m.form.submitted" />
                  </label>
                </template>
                <button class="primary" @click="submitAiForm(m.form)" :disabled="m.form.submitted || aiSending">
                  {{ m.form.submitted ? t('app.aiBuilder.submitted') : (m.form.submit_label || t('app.aiBuilder.continue')) }}
                </button>
              </div>
            </div>
          </div>

          <div v-if="aiDraft" class="ai-draft">
            <div class="ai-draft-head">
              <strong>{{ aiDraft.title }}</strong>
              <span>{{ tr('app.aiBuilder.stats', aiDraft.stats || {}) }}</span>
            </div>
            <div v-if="aiDraft.summary" class="ai-draft-summary">{{ aiDraft.summary }}</div>
            <ol>
              <li v-for="(s, i) in aiDraftSteps" :key="i">{{ stepLabel(s) }}</li>
            </ol>
            <div v-for="note in aiDraft.notes || []" :key="note" class="ai-note">{{ note }}</div>
            <button class="primary" @click="applyAiDraft">{{ t('app.aiBuilder.apply') }}</button>
          </div>

          <div class="ai-compose">
            <input ref="aiFileInput" type="file" multiple accept=".txt,.md,.json,.csv,.docx" @change="onAiFiles" hidden />
            <div v-if="aiFiles.length" class="ai-files selected">
              <span v-for="f in aiFiles" :key="f.name">{{ f.name }}</span>
              <button @click="aiFiles = []">{{ t('app.aiBuilder.clearFiles') }}</button>
            </div>
            <textarea v-model="aiInput" :placeholder="t('app.aiBuilder.placeholder')" @keydown.ctrl.enter.prevent="sendAiMessage"></textarea>
            <div class="ai-compose-actions">
              <button @click="aiFileInput && aiFileInput.click()">{{ t('app.aiBuilder.upload') }}</button>
              <button class="primary" @click="sendAiMessage" :disabled="aiSending || (!aiInput.trim() && !aiFiles.length)">
                {{ aiSending ? t('app.aiBuilder.generating') : t('app.aiBuilder.send') }}
              </button>
            </div>
          </div>
        </div>
      </div>
    </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue'
import { LGraph, LGraphCanvas, LiteGraph } from 'litegraph.js'
import Cropper from 'cropperjs'
import 'cropperjs/dist/cropper.css'
import { fabric } from 'fabric'
import { api } from './api.js'
import { registerCatalog, setDeviceActionHandler, setCaptureHandler, setImageActionHandler, setMaskActionHandler } from './graph/litegraph-setup.js'
import { installLiteGraphI18n } from './graph/litegraph-i18n.js'
import { getLocale, languages, locale, setLocale, t, tr } from './i18n.js'
import { VideoOverlay } from './graph/video-overlay.js'
import { ShotOverlay } from './graph/shot-overlay.js'
import { CodeOverlay } from './graph/code-overlay.js'
import { ErrorOverlay } from './graph/error-overlay.js'
import { AgentTraceOverlay } from './graph/agent-overlay.js'
import { DeviceConnection } from './webrtc/device.js'

const projects = ref([])
const current = ref('')
const status = ref('')
const DEFAULT_TIMEOUT_SETTINGS = {
  rdp_connect_timeout: 60,
  rdp_first_update_timeout: 30,
}
const DEFAULT_AI_BUILDER_SETTINGS = {
  provider: 'openai',
  base_url: '',
  model: 'gpt-4o',
  api_key: '',
  temperature: 0,
}
const timeoutSettings = ref({ ...DEFAULT_TIMEOUT_SETTINGS })
const aiBuilderSettings = ref({ ...DEFAULT_AI_BUILDER_SETTINGS })
const settingsDraft = ref({
  ...DEFAULT_TIMEOUT_SETTINGS,
  ai_builder: { ...DEFAULT_AI_BUILDER_SETTINGS },
})
const showSettings = ref(false)

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
function categoryLabel(cat) { return t(`app.categories.${cat}`, cat) }
function nodeTitle(node) { return t(`app.nodes.${node.type}`, node.title) }
async function changeLocale(nextLocale) {
  const oldReady = t('app.status.ready')
  setLocale(nextLocale)
  await reloadCatalogForLocale()
  if (status.value === '' || status.value === oldReady) status.value = t('app.status.ready')
  applyNodeTypeTitles()
  refreshGraphI18n()
  lgcanvas && lgcanvas.setDirty(true, true)
}

async function reloadCatalogForLocale() {
  const catalog = await api.catalog()
  registerCatalog(catalog)
  catalogNodes.value = catalog.nodes
  const byType = new Map(catalog.nodes.map((spec) => [spec.type, spec]))
  for (const node of graph?._nodes || []) {
    const spec = byType.get(node._spec?.type || node.type)
    if (spec) _updateNodeSpec(node, spec)
  }
}

function _updateNodeSpec(node, spec) {
  node._spec = spec
  node.title = nodeTitle(spec)
}
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

// Graph 撤销/重做：保存结构化快照，运行期颜色/错误等临时状态不入历史。
const undoStack = ref([])
const redoStack = ref([])
const canUndo = computed(() => undoStack.value.length > 1)
const canRedo = computed(() => redoStack.value.length > 0)
const GRAPH_HISTORY_LIMIT = 80
let historyTimer = null
let historyRestoring = false
let lastHistoryJson = ''

function cleanGraphForHistory(data) {
  const copy = JSON.parse(JSON.stringify(data || {}))
  for (const node of copy.nodes || []) {
    delete node.color
    delete node.bgcolor
    delete node._error
  }
  return copy
}

function graphHistoryJson() {
  if (!graph) return ''
  return JSON.stringify(cleanGraphForHistory(graph.serialize()))
}

function resetGraphHistory() {
  clearTimeout(historyTimer)
  historyTimer = null
  const json = graphHistoryJson()
  lastHistoryJson = json
  undoStack.value = json ? [json] : []
  redoStack.value = []
}

function scheduleGraphHistory() {
  if (!graph || historyRestoring) return
  clearTimeout(historyTimer)
  historyTimer = setTimeout(pushGraphHistoryNow, 250)
}

function flushGraphHistory() {
  if (!historyTimer) return
  clearTimeout(historyTimer)
  historyTimer = null
  pushGraphHistoryNow()
}

function pushGraphHistoryNow() {
  if (!graph || historyRestoring) return
  const json = graphHistoryJson()
  if (!json || json === lastHistoryJson) return
  lastHistoryJson = json
  const stack = [...undoStack.value, json]
  if (stack.length > GRAPH_HISTORY_LIMIT) stack.splice(0, stack.length - GRAPH_HISTORY_LIMIT)
  undoStack.value = stack
  redoStack.value = []
}

function cleanupGraphRuntime() {
  if (!graph) return
  for (const node of graph._nodes.slice()) {
    if (node._conn) {
      try {
        const closing = node._conn.close()
        if (closing?.catch) closing.catch(() => {})
      } catch (_) {}
      node.setDeviceConnectionState ? node.setDeviceConnectionState({ conn: null, connecting: false }) : (node._conn = null)
    }
    if (node._connecting) node.setDeviceConnectionState ? node.setDeviceConnectionState({ connecting: false }) : (node._connecting = false)
    try { overlay && overlay.detach(node) } catch (_) {}
    try { shots && shots.clear && shots.clear(node) } catch (_) {}
  }
  try { codes && codes.update([]) } catch (_) {}
  try { errors && errors.update([]) } catch (_) {}
  try { agentTrace && agentTrace.clearAll && agentTrace.clearAll() } catch (_) {}
}

function restoreGraphHistory(json) {
  if (!graph || !json) return
  historyRestoring = true
  try {
    cleanupGraphRuntime()
    graph.configure(JSON.parse(json))
    refreshGraphI18n()
    reloadShots()
    lastHistoryJson = json
    lgcanvas && lgcanvas.setDirty(true, true)
  } finally {
    historyRestoring = false
  }
}

function undoGraph() {
  flushGraphHistory()
  if (!canUndo.value) return
  const stack = [...undoStack.value]
  const currentJson = stack.pop()
  const previousJson = stack[stack.length - 1]
  undoStack.value = stack
  redoStack.value = currentJson ? [currentJson, ...redoStack.value] : redoStack.value
  restoreGraphHistory(previousJson)
}

function redoGraph() {
  flushGraphHistory()
  if (!canRedo.value) return
  const [nextJson, ...rest] = redoStack.value
  undoStack.value = [...undoStack.value, nextJson]
  redoStack.value = rest
  restoreGraphHistory(nextJson)
}

function installGraphHistoryHooks() {
  if (!graph) return
  graph._requestHistory = scheduleGraphHistory
  const prevChange = graph.on_change
  graph.on_change = function (...args) {
    prevChange && prevChange.apply(this, args)
    scheduleGraphHistory()
  }
  const prevAfterChange = graph.onAfterChange
  graph.onAfterChange = function (...args) {
    prevAfterChange && prevAfterChange.apply(this, args)
    scheduleGraphHistory()
  }
  const prevConnectionChange = graph.onConnectionChange
  graph.onConnectionChange = function (...args) {
    prevConnectionChange && prevConnectionChange.apply(this, args)
    scheduleGraphHistory()
  }
}

function isTextEditingTarget(el) {
  if (!el) return false
  const tag = el.tagName?.toLowerCase()
  return tag === 'input' || tag === 'textarea' || tag === 'select' || !!el.isContentEditable
}

function onGlobalKeyDown(ev) {
  if (isTextEditingTarget(ev.target)) return
  const mod = ev.ctrlKey || ev.metaKey
  if (!mod) return
  const key = ev.key.toLowerCase()
  if (key === 'z' && !ev.shiftKey) {
    ev.preventDefault()
    undoGraph()
  } else if (key === 'y' || (key === 'z' && ev.shiftKey)) {
    ev.preventDefault()
    redoGraph()
  }
}

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
  if (!confirm(tr('app.prompts.deleteRun', { run: r }))) return
  try {
    await api.deleteResult(current.value, r)
    runs.value = runs.value.filter(x => x !== r)
    if (selRun.value === r) { selRun.value = ''; report.value = null }
    status.value = tr('app.status.deletedRun', { run: r })
  } catch (e) { alert(tr('app.alerts.deleteFailed', { message: e.message })) }
}

async function clearRuns() {
  if (!confirm(t('app.prompts.clearRuns'))) return
  try {
    const { deleted } = await api.clearResults(current.value)
    runs.value = []; selRun.value = ''; report.value = null
    status.value = tr('app.status.clearedRuns', { count: deleted })
  } catch (e) { alert(tr('app.alerts.clearFailed', { message: e.message })) }
}

// AI 辅助流程搭建
const showAiBuilder = ref(false)
const aiMessages = ref([])
const aiInput = ref('')
const aiFiles = ref([])
const aiFileInput = ref(null)
const aiSending = ref(false)
const aiDraft = ref(null)
const aiFormValues = ref({})
const aiDraftSteps = computed(() => aiDraft.value?.dsl?.steps || [])

function openAiBuilder() {
  if (!current.value) { alert(t('app.alerts.openProjectFirst')); return }
  showAiBuilder.value = true
  if (!aiMessages.value.length) {
    aiMessages.value.push({ role: 'assistant', content: t('app.aiBuilder.welcome') })
  }
}

function onAiFiles(ev) {
  aiFiles.value = Array.from(ev.target.files || [])
  ev.target.value = ''
}

async function sendAiMessage() {
  await requestAiDraft(aiInput.value.trim(), aiFiles.value, true)
}

async function requestAiDraft(message, files = [], pushUser = false) {
  if (!current.value || aiSending.value) return
  if (pushUser && !message && !files.length) return
  if (pushUser) {
    aiMessages.value.push({
      role: 'user',
      content: message,
      files: files.map((f) => f.name),
    })
    aiInput.value = ''
    aiFiles.value = []
  }
  aiSending.value = true
  try {
    const state = {
      message,
      history: aiMessages.value
        .filter((m) => m.content)
        .map((m) => ({ role: m.role, content: m.content }))
        .slice(-20),
      draft_dsl: aiDraft.value?.dsl || null,
      current_graph: graph.serialize(),
      ai_settings: aiBuilderSettings.value,
      form_values: aiFormValues.value,
    }
    const res = await api.aiDraft(current.value, state, files)
    if (res.message) aiMessages.value.push({ role: 'assistant', content: res.message })
    for (const form of res.forms || []) {
      aiMessages.value.push({ role: 'assistant', content: '', form: hydrateAiForm(form) })
    }
    if (res.draft) {
      aiDraft.value = res.draft
      status.value = t('app.status.aiDraftReady')
    }
  } catch (e) {
    aiMessages.value.push({ role: 'assistant', content: tr('app.aiBuilder.error', { message: e.message }) })
  } finally {
    aiSending.value = false
  }
}

function hydrateAiForm(form) {
  const f = { ...form, submitted: false }
  if (f.kind === 'device') {
    f.values = { type: f.type || f.devices?.[0]?.type || 'device/rdp', properties: {} }
    fillDeviceDefaults(f)
  } else {
    f.values = {}
    for (const field of f.fields || []) f.values[field.name] = field.default ?? ''
  }
  return f
}

function deviceFormProps(form) {
  fillDeviceDefaults(form)
  return form._selectedProps || []
}

function fillDeviceDefaults(form) {
  const spec = (form.devices || []).find((d) => d.type === form.values?.type) || (form.devices || [])[0]
  form._selectedProps = spec?.properties || []
  form.values ||= { type: spec?.type || 'device/rdp', properties: {} }
  form.values.properties ||= {}
  for (const p of form._selectedProps) {
    if (!(p.name in form.values.properties)) form.values.properties[p.name] = p.default ?? ''
  }
}

function formInputType(type) {
  if (type === 'password') return 'password'
  if (type === 'int' || type === 'number') return 'number'
  return 'text'
}

async function submitAiForm(form) {
  if (form.submitted) return
  const values = normalizeAiFormValues(form)
  aiFormValues.value = { ...aiFormValues.value, [form.id]: values }
  form.submitted = true
  aiMessages.value.push({ role: 'user', content: tr('app.aiBuilder.formSubmitted', { title: form.title }) })
  await requestAiDraft('', [], false)
}

function normalizeAiFormValues(form) {
  if (form.kind === 'device') {
    fillDeviceDefaults(form)
    const props = {}
    for (const p of form._selectedProps || []) props[p.name] = normalizeFormValue(form.values.properties[p.name], p.type)
    return { type: form.values.type, properties: props }
  }
  const out = {}
  for (const f of form.fields || []) out[f.name] = normalizeFormValue(form.values[f.name], f.type)
  return out
}

function normalizeFormValue(value, type) {
  if (type === 'bool') return !!value
  if (type === 'int') {
    const n = parseInt(value, 10)
    return Number.isFinite(n) ? n : 0
  }
  if (type === 'number') {
    const n = Number(value)
    return Number.isFinite(n) ? n : 0
  }
  return value ?? ''
}

function stepLabel(step) {
  const action = step.action || ''
  const target = step.text || step.description || step.message || step.keys || ''
  return t(`app.aiBuilder.actions.${action}`, action) + (target ? `: ${target}` : '')
}

function resolveDraftNode(ref, created) {
  if (!ref) return null
  if (String(ref).startsWith('external:')) {
    const id = Number(String(ref).slice('external:'.length))
    return graph.getNodeById(id)
  }
  return created.get(ref) || null
}

function connectByName(src, outName, dst, inName) {
  if (!src || !dst) return false
  const outSlot = src.findOutputSlot(outName)
  const inSlot = dst.findInputSlot(inName)
  if (outSlot < 0 || inSlot < 0) return false
  src.connect(outSlot, dst, inSlot)
  return true
}

function applyAiDraft() {
  if (!aiDraft.value || !graph) return
  const draft = aiDraft.value
  const created = new Map()
  const minX = Math.min(...(draft.nodes || []).map((n) => n.pos?.[0] ?? 0), 0)
  const minY = Math.min(...(draft.nodes || []).map((n) => n.pos?.[1] ?? 0), 0)
  let maxX = 80
  for (const n of graph._nodes || []) maxX = Math.max(maxX, n.pos[0] + (n.size?.[0] || 180))
  const offsetX = maxX + 80 - minX
  const offsetY = 80 - minY

  for (const spec of draft.nodes || []) {
    const node = LiteGraph.createNode(spec.type)
    if (!node) continue
    node.pos = [(spec.pos?.[0] ?? 0) + offsetX, (spec.pos?.[1] ?? 0) + offsetY]
    for (const [key, value] of Object.entries(spec.properties || {})) {
      if (node.setProperty) node.setProperty(key, value)
      else node.properties[key] = value
    }
    graph.add(node)
    created.set(spec.id, node)
  }

  for (const link of draft.links || []) {
    const src = resolveDraftNode(link.from, created)
    const dst = resolveDraftNode(link.to, created)
    connectByName(src, link.out, dst, link.in)
  }

  if (draft.auto_connect_start && draft.entry) {
    const start = graph.getNodeById(Number(draft.auto_connect_start))
    const entry = resolveDraftNode(draft.entry, created)
    const outSlot = start?.findOutputSlot('out')
    const out = outSlot >= 0 ? start.outputs?.[outSlot] : null
    if (start && entry && !(out?.links || []).length) connectByName(start, 'out', entry, 'in')
  }

  refreshGraphI18n()
  lgcanvas && lgcanvas.setDirty(true, true)
  locateGraph()
  scheduleGraphHistory()
  status.value = t('app.status.aiDraftApplied')
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
  installLiteGraphI18n()
  const catalog = await api.catalog()
  registerCatalog(catalog)
  catalogNodes.value = catalog.nodes
  applyNodeTypeTitles()

  graph = new LGraph()
  installGraphHistoryHooks()
  lgcanvas = new LGraphCanvas(canvasEl.value, graph)
  resize()
  window.addEventListener('resize', resize)
  window.addEventListener('keydown', onGlobalKeyDown)

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
  await loadGlobalSettings()
  projects.value = await api.listProjects()
  status.value = t('app.status.ready')
  resetGraphHistory()
})

onUnmounted(() => {
  window.removeEventListener('resize', resize)
  window.removeEventListener('keydown', onGlobalKeyDown)
  clearTimeout(historyTimer)
})

function applyNodeTypeTitles() {
  for (const spec of catalogNodes.value) {
    const cls = LiteGraph.registered_node_types?.[spec.type]
    if (cls) cls.title = nodeTitle(spec)
  }
}

function refreshGraphI18n() {
  for (const node of graph?._nodes || []) node.refreshI18n && node.refreshI18n()
}

function resize() {
  const r = stage.value.getBoundingClientRect()
  canvasEl.value.width = r.width
  canvasEl.value.height = r.height
  lgcanvas && lgcanvas.resize(r.width, r.height)
}

async function newProject() {
  const name = prompt(t('app.prompts.projectName'))
  if (!name) return
  try {
    await api.createProject(name)
    projects.value = await api.listProjects()
    current.value = name
    await openProject()
  } catch (e) { alert(tr('app.alerts.createFailed', { message: e.message })) }
}

async function openProject() {
  if (!current.value) return
  // 关闭所有设备连接与交互画面
  for (const node of graph._nodes.slice()) {
    if (node._conn) {
      try { await node._conn.close() } catch (e) {}
      node.setDeviceConnectionState ? node.setDeviceConnectionState({ conn: null, connecting: false }) : (node._conn = null)
    }
    overlay.detach(node)
  }
  const data = await api.loadFlow(current.value)
  historyRestoring = true
  try {
    graph.configure(data)
  } finally {
    historyRestoring = false
  }
  aiFormValues.value = {}
  aiDraft.value = null
  aiMessages.value = []
  applyRdpTimeoutsToNodes(timeoutSettings.value, { recordHistory: false })
  refreshGraphI18n()
  reloadShots()
  resetGraphHistory()
  status.value = tr('app.status.opened', { name: current.value })
}

async function loadGlobalSettings() {
  let settings = {}
  try {
    settings = await api.loadSettings()
  } catch (_) {
    settings = {}
  }
  timeoutSettings.value = normalizeTimeoutSettings(settings.timeouts)
  aiBuilderSettings.value = normalizeAiBuilderSettings(settings.ai_builder)
}

function normalizeTimeoutSettings(raw = {}) {
  return {
    rdp_connect_timeout: clampTimeout(raw.rdp_connect_timeout, DEFAULT_TIMEOUT_SETTINGS.rdp_connect_timeout),
    rdp_first_update_timeout: clampTimeout(raw.rdp_first_update_timeout, DEFAULT_TIMEOUT_SETTINGS.rdp_first_update_timeout),
  }
}

function clampTimeout(value, fallback) {
  const n = Number(value)
  if (!Number.isFinite(n)) return fallback
  return Math.min(300, Math.max(5, n))
}

async function openSettings() {
  await loadGlobalSettings()
  settingsDraft.value = {
    ...timeoutSettings.value,
    ai_builder: { ...aiBuilderSettings.value },
  }
  showSettings.value = true
}

function closeSettings() {
  showSettings.value = false
}

async function saveSettings() {
  const nextTimeouts = normalizeTimeoutSettings(settingsDraft.value)
  const nextAi = normalizeAiBuilderSettings(settingsDraft.value.ai_builder)
  timeoutSettings.value = nextTimeouts
  aiBuilderSettings.value = nextAi
  await api.saveSettings({ timeouts: nextTimeouts, ai_builder: nextAi })
  applyRdpTimeoutsToNodes(nextTimeouts)
  showSettings.value = false
  status.value = t('app.status.settingsSaved')
}

function normalizeAiBuilderSettings(raw = {}) {
  const provider = ['openai', 'ollama', 'custom'].includes(raw.provider) ? raw.provider : DEFAULT_AI_BUILDER_SETTINGS.provider
  return {
    provider,
    base_url: String(raw.base_url ?? DEFAULT_AI_BUILDER_SETTINGS.base_url),
    model: String(raw.model ?? DEFAULT_AI_BUILDER_SETTINGS.model),
    api_key: String(raw.api_key ?? DEFAULT_AI_BUILDER_SETTINGS.api_key),
    temperature: clampAiTemperature(raw.temperature, DEFAULT_AI_BUILDER_SETTINGS.temperature),
  }
}

function clampAiTemperature(value, fallback) {
  const n = Number(value)
  if (!Number.isFinite(n)) return fallback
  return Math.min(2, Math.max(0, n))
}

function applyRdpTimeoutsToNodes(settings, options = {}) {
  if (!graph) return
  let changed = false
  for (const node of graph._nodes || []) {
    if (node._spec?.type !== 'device/rdp' || node._conn || node._connecting) continue
    const before = JSON.stringify(node.properties || {})
    node.setProperty('connect_timeout', settings.rdp_connect_timeout)
    node.setProperty('first_update_timeout', settings.rdp_first_update_timeout)
    if (JSON.stringify(node.properties || {}) !== before) changed = true
  }
  lgcanvas && lgcanvas.setDirty(true, true)
  if (options.recordHistory !== false && changed) scheduleGraphHistory()
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
  if (!current.value) { alert(t('app.alerts.openProjectFirst')); return }
  try {
    const file = mode === 'paste' ? await readClipboardImage() : await pickLocalImage()
    if (!file) return
    const ext = (file.type.split('/')[1] || 'png').replace('jpeg', 'jpg')
    // 弹框指定名称（上传默认用原文件名，粘贴默认 tpl_<id>）
    const suggested = mode === 'paste'
      ? `tpl_${node.id}` : (file.name ? file.name.replace(/\.[^.]+$/, '') : `tpl_${node.id}`)
    const input = prompt(t('app.prompts.imageName'), suggested)
    if (input === null) return                       // 取消
    let fname = input.trim() || suggested
    if (!/\.[a-z0-9]+$/i.test(fname)) fname += '.' + ext   // 无扩展名则补上
    const r = await api.uploadImage(current.value, file, fname)
    node.properties.name = r.name
    shots.setImage(node, api.imageUrl(current.value, r.name), { fit: true })
    scheduleGraphHistory()
    status.value = tr('app.status.templateSet', { name: r.name })
  } catch (e) {
    alert(tr('app.alerts.setTemplateFailed', { message: e.message }))
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
  scheduleGraphHistory()
  status.value = tr('app.status.renamed', { name: r.name })
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
  if (!navigator.clipboard?.read) throw new Error(t('app.alerts.clipboardUnsupported'))
  const items = await navigator.clipboard.read()
  for (const it of items) {
    const type = it.types.find(t => t.startsWith('image/'))
    if (type) return await it.getType(type)
  }
  throw new Error(t('app.alerts.clipboardNoImage'))
}

async function save() {
  await api.saveFlow(current.value, graph.serialize())
  status.value = tr('app.status.saved', { name: current.value, time: new Date().toLocaleTimeString() })
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
  const ws = new WebSocket(`${proto}://${location.host}/ws/run/${current.value}?lang=${encodeURIComponent(getLocale())}`)
  runWs = ws
  ws.onopen = () => {
    running.value = true
    status.value = t('app.status.running')
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
      const result = r.passed
        ? '✅ ' + t('app.status.runPassed')
        : '❌ ' + tr('app.status.runFailed', { failed: r.failed, total: r.total })
      status.value = tr('app.status.runDone', { result, duration: r.duration })
      if (m.report_url) lastResult.value = { report_url: m.report_url, junit_url: m.junit_url, pdf_url: m.pdf_url }
      finishRun()
    } else if (m.type === 'run' && (m.status === 'error')) {
      status.value = tr('app.status.runError', { error: m.error || '' })
      finishRun()
    }
  }
  ws.onclose = () => finishRun()
  ws.onerror = () => { status.value = t('app.status.runConnectionError'); finishRun() }
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
  if (node._connecting) return
  if (node._conn) {
    const conn = node._conn
    node.setDeviceConnectionState ? node.setDeviceConnectionState({ conn: null, connecting: false }) : (node._conn = null)
    reconcileInteractions()        // 卸载显示此设备的交互画面
    try { await conn.close() } catch (e) {}
    status.value = t('app.status.disconnected')
    return
  }
  const kind = node._spec.type.split('/')[1] // device/local -> local
  const conn = new DeviceConnection()
  const config = { ...node.properties }
  if (kind === 'rdp') {
    config.connect_timeout = timeoutSettings.value.rdp_connect_timeout
    config.first_update_timeout = timeoutSettings.value.rdp_first_update_timeout
  }
  node.setDeviceConnectionState ? node.setDeviceConnectionState({ connecting: true }) : (node._connecting = true)
  status.value = t('app.status.connecting')
  try {
    const dev = await conn.connect(kind, config, current.value, node.id)
    node.setDeviceConnectionState ? node.setDeviceConnectionState({ conn, connecting: false }) : (node._conn = conn)
    reconcileInteractions()        // 挂载到已连线的交互节点
    status.value = tr('app.status.connected', { kind, width: dev.width, height: dev.height })
  } catch (e) {
    try { await conn.close() } catch (_) {}
    node.setDeviceConnectionState ? node.setDeviceConnectionState({ conn: null, connecting: false }) : (node._connecting = false)
    alert(tr('app.alerts.connectFailed', { message: e.message }))
    status.value = t('app.status.connectFailed')
  }
}

// 人机交互节点截图：抓当前帧 → 打开 Cropper 裁剪/命名弹框（交互节点的设备连接即 overlay.connOf）。
async function onCapture(node) {
  if (!current.value) { alert(t('app.alerts.openProjectFirst')); return }
  const conn = overlay.connOf(node)
  if (!conn || !conn.stream) { alert(t('app.alerts.interactionNoDevice')); return }
  try {
    const canvas = await conn.grabFrame()
    openCropper(canvas.toDataURL('image/png'), node)
  } catch (e) {
    alert(tr('app.alerts.captureFailed', { message: e.message }))
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
      canvas.toBlob((b) => b ? res(b) : rej(new Error(t('app.alerts.cropFailed'))), 'image/png'))
    const r = await api.uploadImage(current.value, blob, name)
    // 创建模板图片节点，放在触发截图的交互节点右侧
    const n = LiteGraph.createNode('const/image')
    n.properties.name = r.name
    const a = cropAnchor
    n.pos = a ? [a.pos[0] + a.size[0] + 40, a.pos[1]] : [120, 120]
    graph.add(n)
    shots.setImage(n, api.imageUrl(current.value, r.name), { fit: true })
    scheduleGraphHistory()
    status.value = tr('app.status.templateCreated', { name: r.name })
    closeCropper()
  } catch (e) {
    alert(tr('app.alerts.saveFailed', { message: e.message }))
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
  if (!current.value) { alert(t('app.alerts.openProjectFirst')); return }
  const slot = (node.inputs || []).findIndex(i => i.name === 'picture')
  const src = slot >= 0 ? pictureSource(node.getInputNode(slot)) : null
  if (!src) { alert(t('app.alerts.maskNeedsPicture')); return }
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
      c.toBlob((b) => b ? res(b) : rej(new Error(t('app.alerts.maskGenerateFailed'))), 'image/png'))
    const name = `mask_${maskAnchor.id}_${Date.now()}.png`
    const r = await api.uploadImage(current.value, blob, name)
    maskAnchor.properties.mask = r.name
    shots.setImage(maskAnchor, api.imageUrl(current.value, r.name), { fit: true })
    scheduleGraphHistory()
    status.value = tr('app.status.maskSaved', { name: r.name })
    closeMask()
  } catch (e) {
    alert(tr('app.alerts.maskSaveFailed', { message: e.message }))
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
:root {
  --scrollbar-track: #15171a;
  --scrollbar-thumb: #4e6572;
  --scrollbar-thumb-hover: #6f8795;
}
* {
  scrollbar-width: thin;
  scrollbar-color: var(--scrollbar-thumb) var(--scrollbar-track);
}
*::-webkit-scrollbar {
  width: 9px;
  height: 9px;
}
*::-webkit-scrollbar-track {
  background: var(--scrollbar-track);
  border-radius: 999px;
}
*::-webkit-scrollbar-thumb {
  background: linear-gradient(180deg, #6f8795, #3e505c);
  border: 2px solid var(--scrollbar-track);
  border-radius: 999px;
}
*::-webkit-scrollbar-thumb:hover {
  background: linear-gradient(180deg, var(--scrollbar-thumb-hover), #526b79);
}
*::-webkit-scrollbar-corner {
  background: transparent;
}
textarea, .graphdialog textarea {
  scrollbar-gutter: stable;
}
/* 节点右键菜单需盖过画面区 DOM 覆盖层（脚本编辑器 z-index:45、错误条 60 等），否则会被遮挡 */
.litegraph.litecontextmenu { z-index: 1000 !important; }
.app { display: flex; flex-direction: column; height: 100vh; font-family: sans-serif; }
.toolbar { display: flex; gap: 8px; align-items: center; padding: 6px 10px; background: #2b2b2b; color: #eee; }
.toolbar select, .toolbar button {
  box-sizing: border-box;
  height: 26px;
  padding: 3px 8px;
  line-height: 18px;
  white-space: nowrap;
}
.toolbar .locate-btn {
  min-width: 44px;
}
.toolbar .icon-btn {
  width: 28px;
  min-width: 28px;
  padding: 3px 0;
  font-size: 16px;
}
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

.history-modal { position: absolute; inset: 0; z-index: 310; background: rgba(0,0,0,.58);
  display: flex; align-items: center; justify-content: center; padding: 22px; box-sizing: border-box; }
.history-dialog { width: min(920px, 96vw); height: min(680px, 90vh); background: #1f1f1f; color: #ddd;
  border-radius: 6px; display: flex; flex-direction: column; box-shadow: 0 10px 34px rgba(0,0,0,.62);
  font-size: 13px; overflow: hidden; }
.history-head { display: flex; justify-content: space-between; align-items: center;
  padding: 8px 10px; background: #2b2b2b; border-bottom: 1px solid #151515; }
.history-head button { background: none; color: #ccc; border: none; font-size: 18px; cursor: pointer; }
.history-body { flex: 1; min-height: 0; display: grid; grid-template-columns: 260px 1fr; }
.history-runs { min-width: 0; border-right: 1px solid #333; background: #191919; overflow: hidden;
  display: flex; flex-direction: column; }
.history-runs .runs { flex: 1; max-height: none; border: 0; overflow: auto; }
.history-report { min-width: 0; overflow: auto; padding: 10px; }
.history-empty { height: 100%; min-height: 180px; display: flex; align-items: center; justify-content: center;
  color: #777; border: 1px dashed #3a3a3a; border-radius: 6px; box-sizing: border-box; }

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

.ai-builder { width: 440px; max-width: min(440px, 96vw); }
.ai-builder-body { display: flex; flex-direction: column; min-height: 0; height: 100%; }
.ai-chat { flex: 1; min-height: 0; overflow: auto; padding: 10px; display: flex; flex-direction: column; gap: 8px; }
.ai-msg { border: 1px solid #333; background: #242424; border-radius: 6px; padding: 8px; }
.ai-msg.user { background: #24313a; border-color: #38515f; }
.ai-role { color: #9fd0ff; font-size: 11px; margin-bottom: 4px; }
.ai-text { white-space: pre-wrap; line-height: 1.45; }
.ai-files { display: flex; flex-wrap: wrap; gap: 5px; margin-top: 6px; }
.ai-files span { max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  border: 1px solid #405260; color: #cfe8f6; border-radius: 4px; padding: 2px 6px; font-size: 12px; }
.ai-files.selected { margin: 0; }
.ai-files.selected button { border: none; background: #3a3a3a; color: #ddd; border-radius: 4px; cursor: pointer; }
.ai-form { display: flex; flex-direction: column; gap: 8px; }
.ai-form-title { font-weight: 700; color: #fff; }
.ai-form-desc, .ai-note { color: #aaa; font-size: 12px; line-height: 1.4; }
.ai-form label { display: grid; grid-template-columns: 96px 1fr; gap: 6px; align-items: center; }
.ai-form label small { grid-column: 2; color: #888; line-height: 1.35; }
.ai-form input:not([type="checkbox"]), .ai-form select, .ai-compose textarea {
  box-sizing: border-box; width: 100%; background: #101010; color: #eee; border: 1px solid #444;
  border-radius: 4px; padding: 5px 7px; font: 13px system-ui, sans-serif;
}
.ai-form input[type="checkbox"] { justify-self: start; }
.ai-form button, .ai-draft button, .ai-compose-actions button {
  padding: 5px 12px; border: none; border-radius: 4px; cursor: pointer; background: #3a3a3a; color: #ddd;
}
.ai-form button:disabled, .ai-compose-actions button:disabled { cursor: default; opacity: .55; }
.ai-form .primary, .ai-draft .primary, .ai-compose-actions .primary { background: #2b6cb0; color: #fff; }
.ai-draft { flex: 0 0 auto; max-height: 240px; overflow: auto; border-top: 1px solid #333; border-bottom: 1px solid #333;
  padding: 10px; background: #1a1d20; display: flex; flex-direction: column; gap: 6px; }
.ai-draft-head { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }
.ai-draft-head span { color: #9fb4c0; font-size: 12px; white-space: nowrap; }
.ai-draft-summary { color: #ddd; line-height: 1.4; }
.ai-draft ol { margin: 0; padding-left: 20px; }
.ai-draft li { padding: 2px 0; }
.ai-compose { flex: 0 0 auto; display: flex; flex-direction: column; gap: 8px; padding: 10px; background: #202020; }
.ai-compose textarea { min-height: 86px; resize: vertical; line-height: 1.45; }
.ai-compose-actions { display: flex; justify-content: flex-end; gap: 8px; }

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

/* 工程设置 */
.settings-modal { position: absolute; inset: 0; z-index: 320; background: rgba(0,0,0,.55);
  display: flex; align-items: center; justify-content: center; }
.settings-dialog { width: min(560px, 92vw); background: #1f1f1f; color: #ddd;
  border-radius: 6px; display: flex; flex-direction: column; box-shadow: 0 8px 30px rgba(0,0,0,.6); }
.settings-head { padding: 8px 12px; background: #2b2b2b; font-size: 13px; border-radius: 6px 6px 0 0; }
.settings-body { display: flex; flex-direction: column; gap: 10px; padding: 12px; }
.settings-section { color: #9fd0ff; font-size: 12px; padding-top: 4px; border-top: 1px solid #333; }
.settings-section:first-child { border-top: 0; padding-top: 0; }
.settings-body label { display: grid; grid-template-columns: 170px 1fr; gap: 12px; align-items: center; font-size: 13px; }
.settings-body input, .settings-body select { box-sizing: border-box; width: 100%; background: #111; color: #eee;
  border: 1px solid #444; border-radius: 4px; padding: 4px 6px; }
.settings-foot { display: flex; justify-content: flex-end; gap: 8px; padding: 8px 12px; background: #262626; }
.settings-foot button { padding: 4px 12px; }
.settings-foot .primary { background: #2b6cb0; color: #fff; border: none; border-radius: 4px; cursor: pointer; }

@media (max-width: 720px) {
  .history-dialog { height: min(720px, 94vh); }
  .history-body { grid-template-columns: 1fr; grid-template-rows: minmax(150px, 32%) 1fr; }
  .history-runs { border-right: 0; border-bottom: 1px solid #333; }
}
</style>
