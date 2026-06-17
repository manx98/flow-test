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
      <button class="locate-btn" @click="autoLayoutCanvas" :disabled="!current" :title="t('app.toolbar.layoutTitle')">{{ t('app.toolbar.layout') }}</button>
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

      <div v-if="aiConfirmCall" class="ai-confirm-modal">
        <div class="ai-confirm-dialog">
          <div class="ai-confirm-head">{{ t('app.aiBuilder.confirmTitle') }}</div>
          <div class="ai-confirm-body">
            <div>{{ aiConfirmCall.tool }}</div>
            <pre>{{ JSON.stringify(aiConfirmCall.args || {}, null, 2) }}</pre>
          </div>
          <div class="ai-confirm-foot">
            <button @click="resolveAiConfirm('rejected')">{{ t('app.aiBuilder.reject') }}</button>
            <button @click="resolveAiConfirm('approved')">{{ t('app.aiBuilder.approve') }}</button>
            <button class="primary" @click="resolveAiConfirm('remember')">{{ t('app.aiBuilder.rememberApprove') }}</button>
          </div>
        </div>
      </div>

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
            <label>
              <span>{{ t('app.settings.aiReasoningEffort') }}</span>
              <select v-model="settingsDraft.ai_builder.reasoning_effort">
                <option value="">{{ t('app.settings.aiReasoningDefault') }}</option>
                <option value="low">low</option>
                <option value="medium">medium</option>
                <option value="high">high</option>
              </select>
            </label>
            <label>
              <span>{{ t('app.settings.aiConfirmMode') }}</span>
              <select v-model="settingsDraft.ai_builder.confirm_mode">
                <option value="manual">{{ t('app.settings.aiConfirmManual') }}</option>
                <option value="auto">{{ t('app.settings.aiConfirmAuto') }}</option>
              </select>
            </label>
            <label>
              <span>{{ t('app.settings.aiMaxToolCalls') }}</span>
              <input type="number" min="1" max="200" step="1" v-model.number="settingsDraft.ai_builder.max_tool_calls" />
            </label>
            <label>
              <span>{{ t('app.settings.aiMaxRepairRounds') }}</span>
              <input type="number" min="0" max="50" step="1" v-model.number="settingsDraft.ai_builder.max_repair_rounds" />
            </label>
            <label>
              <span>{{ t('app.settings.aiTimeoutSeconds') }}</span>
              <input type="number" min="5" max="600" step="5" v-model.number="settingsDraft.ai_builder.timeout_seconds" />
            </label>
            <label>
              <span>{{ t('app.settings.aiRetryAttempts') }}</span>
              <input type="number" min="1" max="10" step="1" v-model.number="settingsDraft.ai_builder.retry_attempts" />
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
          <div class="ai-session-bar">
            <select :value="currentAiSessionId" @change="selectAiSession($event.target.value)" :disabled="aiSending">
              <option v-if="!aiSessions.length" value="">{{ t('app.aiBuilder.noSessions') }}</option>
              <option v-for="s in aiSessions" :key="s.id" :value="s.id">{{ aiSessionTitle(s) }}</option>
            </select>
            <button @click="newAiSession" :disabled="aiSending">{{ t('app.aiBuilder.newSession') }}</button>
            <button @click="deleteCurrentAiSession" :disabled="aiSending || !currentAiSessionId">{{ t('app.aiBuilder.deleteSession') }}</button>
            <button @click="clearAiSessions" :disabled="aiSending || !aiSessions.length">{{ t('app.aiBuilder.clearSessions') }}</button>
          </div>
          <div class="ai-chat">
            <div v-for="(m, idx) in aiMessages" :key="idx" class="ai-msg" :class="m.role">
              <div class="ai-role">{{ m.role === 'user' ? t('app.aiBuilder.user') : t('app.aiBuilder.assistant') }}</div>
              <div v-if="m.content" class="ai-text" v-html="renderMarkdown(m.content)"></div>
              <div v-if="m.thoughts && m.thoughts.length" class="ai-thoughts" :class="{ collapsed: m.thoughtsCollapsed }">
                <button class="ai-thoughts-head" @click="toggleAiThoughts(idx)">
                  <span>{{ t('app.aiBuilder.thoughtTimeline') }}</span>
                  <span>{{ m.thoughtsCollapsed ? '▸' : '▾' }}</span>
                </button>
                <ol v-if="!m.thoughtsCollapsed" class="ai-thought-list">
                  <li v-for="item in m.thoughts" :key="item.node" :class="['ai-thought-item', item.status]">
                    <span class="ai-thought-dot"></span>
                    <div>
                      <div class="ai-thought-title">{{ item.title }}</div>
                      <div v-if="item.detail" class="ai-thought-detail">{{ item.detail }}</div>
                    </div>
                  </li>
                </ol>
              </div>
              <div v-if="m.toolGroup" class="ai-tool-group" :class="{ collapsed: m.toolGroup.collapsed }">
                <button class="ai-tool-group-head" @click="toggleAiToolGroup(idx)">
                  <span>{{ t('app.aiBuilder.toolCalls') }} · {{ aiToolGroupLatest(m.toolGroup) }}</span>
                  <span>{{ m.toolGroup.collapsed ? '▸' : '▾' }}</span>
                </button>
                <ol v-if="!m.toolGroup.collapsed" class="ai-tool-list">
                  <li v-for="item in m.toolGroup.steps" :key="item.call_id" :class="['ai-tool-item', item.status]">
                    <div class="ai-tool-main">
                      <strong>{{ item.tool }}</strong>
                      <span>{{ item.status }}</span>
                    </div>
                    <small v-if="item.result?.error">{{ item.result.error.message || item.result.error.code }}</small>
                  </li>
                </ol>
              </div>
              <div v-if="m.tokens" class="ai-usage">{{ tokenUsageLabel(m.tokens) }}</div>
              <div v-if="m.files && m.files.length" class="ai-files">
                <span v-for="f in m.files" :key="fileLabel(f)">{{ fileLabel(f) }}</span>
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
                <template v-else-if="m.form.kind === 'graph_nodes'">
                  <div class="ai-node-pickers">
                    <button type="button" :class="{ active: isAiPickingNode(m.form, 'image') }"
                            :disabled="m.form.submitted"
                            @click="toggleAiNodePick(m.form, 'image')">
                      {{ isAiPickingNode(m.form, 'image') ? t('app.aiBuilder.selectingImageNode') : t('app.aiBuilder.selectImageNode') }}
                    </button>
                    <button type="button" :class="{ active: isAiPickingNode(m.form, 'mask') }"
                            :disabled="m.form.submitted"
                            @click="toggleAiNodePick(m.form, 'mask')">
                      {{ isAiPickingNode(m.form, 'mask') ? t('app.aiBuilder.selectingMaskNode') : t('app.aiBuilder.selectMaskNode') }}
                    </button>
                  </div>
                  <div class="ai-selection-result">
                    <div>{{ t('app.aiBuilder.selectedImageNode') }}: {{ graphNodeSelectionLabel(m.form, 'image') }}</div>
                    <div>{{ t('app.aiBuilder.selectedMaskNode') }}: {{ graphNodeSelectionLabel(m.form, 'mask') }}</div>
                    <div v-if="m.form.error" class="ai-form-error">{{ m.form.error }}</div>
                  </div>
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
                <button class="primary" @click="submitAiForm(m.form)" :disabled="m.form.submitted || aiSending || !canSubmitAiForm(m.form)">
                  {{ m.form.submitted ? t('app.aiBuilder.submitted') : (m.form.submit_label || t('app.aiBuilder.continue')) }}
                </button>
              </div>
            </div>
          </div>

          <div v-if="false && aiBuildSteps.length" class="ai-build-steps">
            <div class="ai-build-title">{{ t('app.aiBuilder.buildSteps') }} · {{ aiBuildStatus }}</div>
            <ol>
              <li v-for="(s, i) in aiBuildSteps" :key="i" :class="s.status">
                <strong>{{ s.tool }}</strong>
                <span>{{ s.status }}</span>
                <small v-if="s.result?.error">{{ s.result.error.message || s.result.error.code }}</small>
              </li>
            </ol>
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
              <button class="primary" @click="stopAiBuild" :disabled="!aiSending">{{ t('app.aiBuilder.stop') }}</button>
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
import MarkdownIt from 'markdown-it'
import DOMPurify from 'dompurify'
import { api } from './api.js'
import { registerCatalog, setDeviceActionHandler, setCaptureHandler, setImageActionHandler, setMaskActionHandler } from './graph/litegraph-setup.js'
import { installLiteGraphI18n } from './graph/litegraph-i18n.js'
import { getLocale, languages, locale, setLocale, t, tr } from './i18n.js'
import { VideoOverlay } from './graph/video-overlay.js'
import { ShotOverlay } from './graph/shot-overlay.js'
import { CodeOverlay } from './graph/code-overlay.js'
import { ErrorOverlay } from './graph/error-overlay.js'
import { DeviceConnection } from './webrtc/device.js'

const md = new MarkdownIt({
  html: false,
  linkify: true,
  breaks: true,
})
const defaultLinkOpen = md.renderer.rules.link_open || ((tokens, idx, options, env, self) => self.renderToken(tokens, idx, options))
md.renderer.rules.link_open = (tokens, idx, options, env, self) => {
  const token = tokens[idx]
  const href = token.attrGet('href') || ''
  if (!/^(https?:|mailto:|#|\/)/i.test(href)) token.attrSet('href', '#')
  token.attrSet('target', '_blank')
  token.attrSet('rel', 'noopener noreferrer')
  return defaultLinkOpen(tokens, idx, options, env, self)
}

function renderMarkdown(text) {
  const html = md.render(String(text || ''))
  return DOMPurify.sanitize(html, {
    ADD_ATTR: ['target', 'rel'],
  })
}

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
  reasoning_effort: '',
  confirm_mode: 'manual',
  max_tool_calls: 40,
  max_repair_rounds: 5,
  timeout_seconds: 120,
  retry_attempts: 10,
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

function locateNodes(nodes) {
  if (!graph || !lgcanvas) return
  const list = (nodes || []).filter(Boolean)
  if (!list.length) return locateGraph()
  const ds = lgcanvas.ds
  const r = stage.value.getBoundingClientRect()
  let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity
  const th = LiteGraph.NODE_TITLE_HEIGHT || 20
  for (const n of list) {
    const w = n.size?.[0] || 180
    const h = n.size?.[1] || 80
    minX = Math.min(minX, n.pos[0])
    minY = Math.min(minY, n.pos[1] - th)
    maxX = Math.max(maxX, n.pos[0] + w)
    maxY = Math.max(maxY, n.pos[1] + h)
  }
  const pad = 56
  const bw = Math.max(1, maxX - minX)
  const bh = Math.max(1, maxY - minY)
  const scale = Math.max(0.1, Math.min((r.width - pad * 2) / bw, (r.height - pad * 2) / bh, 1.2))
  ds.scale = scale
  ds.offset[0] = (r.width / 2) / scale - (minX + maxX) / 2
  ds.offset[1] = (r.height / 2) / scale - (minY + maxY) / 2
  lgcanvas.setDirty(true, true)
}

function selectedGraphNodes() {
  return Object.values(lgcanvas?.selected_nodes || {}).filter(Boolean)
}

function installMultiSelectDrag(canvas) {
  if (!canvas || canvas._flowMultiSelectDragInstalled) return
  canvas._flowMultiSelectDragInstalled = true
  const prevProcessNodeSelected = canvas.processNodeSelected
  canvas.processNodeSelected = function (node, ev) {
    const selected = this.selected_nodes || {}
    const keepGroup =
      node &&
      node.is_selected &&
      selected[node.id] &&
      Object.keys(selected).length > 1 &&
      ev?.which === 1 &&
      !ev.shiftKey &&
      !ev.ctrlKey &&
      !ev.metaKey
    if (keepGroup) {
      this.onNodeSelected && this.onNodeSelected(node)
      this.setDirty && this.setDirty(true)
      return
    }
    return prevProcessNodeSelected.call(this, node, ev)
  }
}

function linkRecords() {
  const raw = graph?.links || {}
  return Object.values(raw).map((link) => {
    if (Array.isArray(link)) {
      return {
        id: link[0],
        origin_id: link[1],
        origin_slot: link[2],
        target_id: link[3],
        target_slot: link[4],
        type: link[5],
      }
    }
    return {
      id: link.id,
      origin_id: link.origin_id,
      origin_slot: link.origin_slot,
      target_id: link.target_id,
      target_slot: link.target_slot,
      type: link.type,
    }
  }).filter((link) => link.origin_id != null && link.target_id != null)
}

function nodeOutputType(node, slot) {
  return node?.outputs?.[slot]?.type || ''
}

function nodeInputType(node, slot) {
  return node?.inputs?.[slot]?.type || ''
}

function layoutAnchor(nodes, mode) {
  const moving = new Set((nodes || []).map((n) => n.id))
  let minX = Infinity, minY = Infinity, maxX = -Infinity
  for (const n of graph?._nodes || []) {
    if (mode === 'right' && moving.has(n.id)) continue
    const w = n.size?.[0] || 180
    minX = Math.min(minX, n.pos[0])
    minY = Math.min(minY, n.pos[1])
    maxX = Math.max(maxX, n.pos[0] + w)
  }
  if (!Number.isFinite(minX)) return { x: 120, y: 120 }
  if (mode === 'right') return { x: maxX + 100, y: 120 }
  const selected = nodes || []
  const sx = Math.min(...selected.map((n) => n.pos?.[0] ?? minX))
  const sy = Math.min(...selected.map((n) => n.pos?.[1] ?? minY))
  return { x: Number.isFinite(sx) ? sx : minX, y: Number.isFinite(sy) ? sy : minY }
}

function layoutComponents(nodes, edges) {
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const neighbors = new Map(nodes.map((n) => [n.id, new Set()]))
  for (const edge of edges) {
    if (!byId.has(edge.from) || !byId.has(edge.to)) continue
    neighbors.get(edge.from)?.add(edge.to)
    neighbors.get(edge.to)?.add(edge.from)
  }
  const seen = new Set()
  const components = []
  const sorted = [...nodes].sort((a, b) => (a.pos?.[1] || 0) - (b.pos?.[1] || 0) || (a.pos?.[0] || 0) - (b.pos?.[0] || 0))
  for (const start of sorted) {
    if (seen.has(start.id)) continue
    const ids = []
    const queue = [start.id]
    seen.add(start.id)
    while (queue.length) {
      const id = queue.shift()
      ids.push(id)
      for (const next of neighbors.get(id) || []) {
        if (seen.has(next)) continue
        seen.add(next)
        queue.push(next)
      }
    }
    components.push(ids.map((id) => byId.get(id)).filter(Boolean))
  }
  return components
}

function computeNodeDepths(nodes, edges) {
  const ids = new Set(nodes.map((n) => n.id))
  const depth = new Map(nodes.map((n) => [n.id, 0]))
  const relevantEdges = edges.filter((e) => ids.has(e.from) && ids.has(e.to))
  const outgoing = new Map(nodes.map((n) => [n.id, []]))
  const indeg = new Map(nodes.map((n) => [n.id, 0]))
  for (const edge of relevantEdges) {
    if (!ids.has(edge.from) || !ids.has(edge.to)) continue
    outgoing.get(edge.from)?.push(edge)
    indeg.set(edge.to, (indeg.get(edge.to) || 0) + 1)
  }
  const inputCount = new Map(indeg)
  const byPosition = [...nodes].sort((a, b) => (a.pos?.[1] || 0) - (b.pos?.[1] || 0) || (a.pos?.[0] || 0) - (b.pos?.[0] || 0))
  const byId = new Map(nodes.map((n) => [n.id, n]))
  const queue = byPosition.filter((n) => (indeg.get(n.id) || 0) === 0).map((n) => n.id)
  const visited = new Set()
  while (queue.length) {
    const id = queue.shift()
    visited.add(id)
    for (const edge of outgoing.get(id) || []) {
      depth.set(edge.to, Math.max(depth.get(edge.to) || 0, (depth.get(id) || 0) + 1))
      indeg.set(edge.to, (indeg.get(edge.to) || 0) - 1)
      if ((indeg.get(edge.to) || 0) === 0) {
        queue.push(edge.to)
        queue.sort((a, b) => {
          const na = byId.get(a)
          const nb = byId.get(b)
          return (na?.pos?.[1] || 0) - (nb?.pos?.[1] || 0) || (na?.pos?.[0] || 0) - (nb?.pos?.[0] || 0)
        })
      }
    }
  }
  if (visited.size < nodes.length) {
    for (const node of byPosition) {
      if (!visited.has(node.id)) {
        const inbound = relevantEdges.filter((e) => e.to === node.id && visited.has(e.from))
        const nextDepth = inbound.length ? Math.max(...inbound.map((e) => (depth.get(e.from) || 0) + 1)) : 0
        depth.set(node.id, Math.max(depth.get(node.id) || 0, nextDepth))
      }
    }
  }
  for (let i = 0; i < Math.max(1, nodes.length); i += 1) {
    let changed = false
    for (const edge of relevantEdges) {
      const nextDepth = (depth.get(edge.from) || 0) + 1
      if ((depth.get(edge.to) || 0) < nextDepth) {
        depth.set(edge.to, nextDepth)
        changed = true
      }
    }
    if (!changed) break
  }
  for (const node of nodes) {
    if ((inputCount.get(node.id) || 0) !== 0) continue
    const targets = (outgoing.get(node.id) || []).map((edge) => depth.get(edge.to) ?? 0).filter((value) => value > 0)
    if (!targets.length) continue
    depth.set(node.id, Math.max(0, Math.min(...targets) - 1))
  }
  return depth
}

function nodeLayoutHeight(node) {
  return node?.size?.[1] || 80
}

function nodeLayoutCenterY(node, yById) {
  const top = yById.get(node.id)
  if (top == null) return null
  return top + nodeLayoutHeight(node) / 2
}

function autoLayoutNodes(nodes, opts = {}) {
  if (!graph || !lgcanvas) return false
  const list = [...new Set((nodes || []).filter(Boolean))]
  if (!list.length) return false
  const byId = new Map(list.map((n) => [n.id, n]))
  const edges = linkRecords()
    .filter((link) => byId.has(link.origin_id) && byId.has(link.target_id))
    .map((link) => {
      const src = byId.get(link.origin_id)
      const dst = byId.get(link.target_id)
      const outType = nodeOutputType(src, link.origin_slot)
      const inType = nodeInputType(dst, link.target_slot)
      return {
        from: link.origin_id,
        to: link.target_id,
        outSlot: Number(link.origin_slot || 0),
        inSlot: Number(link.target_slot || 0),
        kind: outType === 'exec' || inType === 'exec' || link.type === 'exec' ? 'exec' : 'data',
      }
    })
  const anchor = layoutAnchor(list, opts.anchor || 'current')
  let componentY = anchor.y
  for (const component of layoutComponents(list, edges)) {
    const componentIds = new Set(component.map((n) => n.id))
    const componentEdges = edges.filter((e) => componentIds.has(e.from) && componentIds.has(e.to))
    const depth = computeNodeDepths(component, componentEdges)
    const incoming = new Map(component.map((n) => [n.id, []]))
    const related = new Map(component.map((n) => [n.id, []]))
    for (const edge of componentEdges) incoming.get(edge.to)?.push(edge)
    for (const edge of componentEdges) {
      related.get(edge.from)?.push({ edge, other: edge.to })
      related.get(edge.to)?.push({ edge, other: edge.from })
    }
    const columns = new Map()
    for (const node of component) {
      const col = depth.get(node.id) || 0
      if (!columns.has(col)) columns.set(col, [])
      columns.get(col).push(node)
    }
    const sortedCols = [...columns.keys()].sort((a, b) => a - b)
    const colWidths = new Map(sortedCols.map((col) => [col, Math.max(...columns.get(col).map((n) => n.size?.[0] || 180), 180)]))
    let x = anchor.x
    const colX = new Map()
    for (const col of sortedCols) {
      colX.set(col, x)
      x += (colWidths.get(col) || 180) + 140
    }
    let componentHeight = 0
    const yById = new Map()
    const originalScore = (node) => {
      const nodeIn = incoming.get(node.id) || []
      const execIn = nodeIn.filter((e) => e.kind === 'exec')
      const dataIn = nodeIn.filter((e) => e.kind !== 'exec')
      if (execIn.length) return Math.min(...execIn.map((e) => e.outSlot))
      if (dataIn.length) return 50 + Math.min(...dataIn.map((e) => e.inSlot))
      return 100
    }
    const neighborCenter = (node) => {
      let total = 0
      let weight = 0
      for (const item of related.get(node.id) || []) {
        const other = component.find((n) => n.id === item.other)
        if (!other) continue
        if (Math.abs((depth.get(other.id) || 0) - (depth.get(node.id) || 0)) !== 1) continue
        const center = nodeLayoutCenterY(other, yById)
        if (center == null) continue
        const w = item.edge.kind === 'exec' ? 2 : 1
        total += center * w
        weight += w
      }
      return weight ? total / weight : null
    }
    const connectedInputs = (node) => componentEdges.filter((edge) => edge.to === node.id && (depth.get(edge.from) || 0) < (depth.get(node.id) || 0))
    const connectedOutputs = (node) => componentEdges.filter((edge) => edge.from === node.id && (depth.get(edge.to) || 0) > (depth.get(node.id) || 0))
    const alignmentConflicts = (node, top) => {
      const center = top + nodeLayoutHeight(node) / 2
      const conflicts = []
      const inputs = connectedInputs(node)
      if (inputs.length > 1) {
        for (const edge of inputs) {
          const other = component.find((n) => n.id === edge.from)
          const otherCenter = other ? nodeLayoutCenterY(other, yById) : null
          if (otherCenter != null) conflicts.push(otherCenter)
        }
      }
      const outputs = connectedOutputs(node)
      if (outputs.length > 1) {
        for (const edge of outputs) {
          const other = component.find((n) => n.id === edge.to)
          const otherCenter = other ? nodeLayoutCenterY(other, yById) : null
          if (otherCenter != null) conflicts.push(otherCenter)
        }
      }
      return conflicts.filter((otherCenter) => Math.abs(center - otherCenter) < 36)
    }
    const avoidAlignedTop = (node, top, minTop) => {
      let nextTop = top
      for (let i = 0; i < 6; i += 1) {
        const conflicts = alignmentConflicts(node, nextTop)
        if (!conflicts.length) break
        const center = nextTop + nodeLayoutHeight(node) / 2
        const nearest = conflicts.sort((a, b) => Math.abs(center - a) - Math.abs(center - b))[0]
        nextTop = Math.max(minTop, nearest + 36 - nodeLayoutHeight(node) / 2)
      }
      return nextTop
    }
    const placeColumn = (col) => {
      const colNodes = columns.get(col)
      colNodes.sort((a, b) => {
        const aCenter = neighborCenter(a)
        const bCenter = neighborCenter(b)
        if (aCenter != null || bCenter != null) return (aCenter ?? Infinity) - (bCenter ?? Infinity)
        return originalScore(a) - originalScore(b) || (a.pos?.[1] || 0) - (b.pos?.[1] || 0) || (a.pos?.[0] || 0) - (b.pos?.[0] || 0)
      })
      let y = componentY
      for (const node of colNodes) {
        node.pos[0] = colX.get(col)
        const center = neighborCenter(node)
        const preferredTop = center == null ? y : center - nodeLayoutHeight(node) / 2
        node.pos[1] = avoidAlignedTop(node, Math.max(y, preferredTop), y)
        yById.set(node.id, node.pos[1])
        y = node.pos[1] + nodeLayoutHeight(node) + 80
      }
      componentHeight = Math.max(componentHeight, y - componentY)
    }
    for (const col of sortedCols) placeColumn(col)
    for (let i = 0; i < 3; i += 1) {
      componentHeight = 0
      for (const col of sortedCols) placeColumn(col)
      for (const col of [...sortedCols].reverse()) placeColumn(col)
    }
    componentY += Math.max(componentHeight, 120) + 140
  }
  lgcanvas.setDirty(true, true)
  if (opts.locate !== false) locateNodes(list)
  if (opts.history !== false) scheduleGraphHistory()
  return true
}

function autoLayoutCanvas() {
  const selected = selectedGraphNodes()
  const nodes = selected.length ? selected : (graph?._nodes || [])
  if (!autoLayoutNodes(nodes, { anchor: 'current' })) return
  status.value = t('app.status.layoutApplied')
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
  const key = (ev.key || '').toLowerCase()
  const isZ = ev.code === 'KeyZ' || key === 'z'
  const isY = ev.code === 'KeyY' || key === 'y'
  const isUndo = isZ && !ev.shiftKey
  const isRedo = isY || (isZ && ev.shiftKey)
  if (isUndo) {
    ev.preventDefault()
    ev.stopPropagation()
    ev.stopImmediatePropagation && ev.stopImmediatePropagation()
    undoGraph()
  } else if (isRedo) {
    ev.preventDefault()
    ev.stopPropagation()
    ev.stopImmediatePropagation && ev.stopImmediatePropagation()
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
const aiSessions = ref([])
const currentAiSessionId = ref('')
const aiMessages = ref([])
const aiInput = ref('')
const aiFiles = ref([])
const aiFileInput = ref(null)
const aiSending = ref(false)
const aiDraft = ref(null)
const aiFormValues = ref({})
const aiNodePick = ref(null)
const aiBuildSteps = ref([])
const aiBuildStatus = ref('idle')
const aiToolPermissions = ref({ auto_approved_tools: [] })
const aiConfirmCall = ref(null)
let aiConfirmResolver = null
let aiBuildWs = null
let aiBuildHandles = new Map()
let aiBuildHandleSeq = 0
const aiDraftSteps = computed(() => aiDraft.value?.graph_patch?.nodes || aiDraft.value?.dsl?.nodes || aiDraft.value?.dsl?.steps || [])

async function openAiBuilder() {
  if (!current.value) { alert(t('app.alerts.openProjectFirst')); return }
  showAiBuilder.value = true
  await loadAiSessions({ selectFirst: true })
  if (!currentAiSessionId.value) await newAiSession()
}

function fileLabel(file) {
  return typeof file === 'string' ? file : (file?.name || '')
}

function clearAiState() {
  currentAiSessionId.value = ''
  aiMessages.value = []
  aiDraft.value = null
  aiFormValues.value = {}
  aiNodePick.value = null
  aiBuildSteps.value = []
  aiBuildStatus.value = 'idle'
  aiToolPermissions.value = { auto_approved_tools: [] }
}

function aiSessionTitle(session) {
  return session?.title || t('app.aiBuilder.defaultSession')
}

function inferAiSessionTitle() {
  if (aiDraft.value?.title) return aiDraft.value.title
  const firstUser = aiMessages.value.find((m) => m.role === 'user' && m.content)
  const text = (firstUser?.content || '').trim()
  return text ? text.slice(0, 28) : t('app.aiBuilder.defaultSession')
}

async function loadAiSessions(options = {}) {
  if (!current.value) return
  aiSessions.value = await api.listAiSessions(current.value)
  if (options.selectFirst && !currentAiSessionId.value && aiSessions.value.length) {
    await selectAiSession(aiSessions.value[0].id)
  }
}

async function newAiSession() {
  if (!current.value) return
  const session = await api.createAiSession(current.value, { title: t('app.aiBuilder.defaultSession') })
  aiSessions.value = [sessionSummary(session), ...aiSessions.value.filter((s) => s.id !== session.id)]
  applyAiSession({
    ...session,
    messages: [{ role: 'assistant', content: t('app.aiBuilder.welcome') }],
  })
  await saveCurrentAiSession()
}

function sessionSummary(session) {
  return {
    id: session.id,
    title: session.title || t('app.aiBuilder.defaultSession'),
    created_at: session.created_at || 0,
    updated_at: session.updated_at || 0,
  }
}

function applyAiSession(session) {
  currentAiSessionId.value = session.id || ''
  aiMessages.value = Array.isArray(session.messages) ? session.messages : []
  aiDraft.value = session.draft || null
  aiFormValues.value = session.form_values || {}
  aiToolPermissions.value = session.tool_permissions || { auto_approved_tools: [] }
  aiBuildSteps.value = session.build_state?.steps || []
  aiBuildStatus.value = session.build_state?.status || 'idle'
  aiNodePick.value = null
  if (!aiMessages.value.length) aiMessages.value = [{ role: 'assistant', content: t('app.aiBuilder.welcome') }]
}

async function selectAiSession(id) {
  if (!id || !current.value || aiSending.value) return
  const session = await api.loadAiSession(current.value, id)
  applyAiSession(session)
}

function currentAiSessionPayload() {
  const summary = aiSessions.value.find((s) => s.id === currentAiSessionId.value) || {}
  return {
    id: currentAiSessionId.value,
    title: inferAiSessionTitle(),
    created_at: summary.created_at,
    messages: aiMessages.value,
    documents: aiMessages.value.flatMap((m) =>
      (m.files || []).filter((f) => f && typeof f === 'object' && f.text).map((f) => ({ name: f.name, text: f.text }))),
    form_values: aiFormValues.value,
    tool_permissions: aiToolPermissions.value,
    build_state: {
      status: aiBuildStatus.value || 'idle',
      last_error: '',
      stop_reason: '',
      steps: aiBuildSteps.value,
      rejected_operations: [],
    },
  }
}

async function saveCurrentAiSession() {
  if (!current.value || !currentAiSessionId.value) return
  const session = await api.saveAiSession(current.value, currentAiSessionId.value, currentAiSessionPayload())
  const summary = sessionSummary(session)
  aiSessions.value = [summary, ...aiSessions.value.filter((s) => s.id !== summary.id)]
}

async function deleteCurrentAiSession() {
  if (!current.value || !currentAiSessionId.value) return
  if (!confirm(t('app.prompts.deleteAiSession'))) return
  const deleted = currentAiSessionId.value
  await api.deleteAiSession(current.value, deleted)
  aiSessions.value = aiSessions.value.filter((s) => s.id !== deleted)
  if (aiSessions.value.length) await selectAiSession(aiSessions.value[0].id)
  else clearAiState()
}

async function clearAiSessions() {
  if (!current.value || !aiSessions.value.length) return
  if (!confirm(t('app.prompts.clearAiSessions'))) return
  const { deleted } = await api.clearAiSessions(current.value)
  aiSessions.value = []
  clearAiState()
  status.value = tr('app.status.clearedAiSessions', { count: deleted })
}

function onAiFiles(ev) {
  aiFiles.value = Array.from(ev.target.files || [])
  ev.target.value = ''
}

async function sendAiMessage() {
  await startAiBuild(aiInput.value.trim(), aiFiles.value, true)
}

async function startAiBuild(message, files = [], pushUser = false) {
  if (!current.value || aiSending.value) return
  if (pushUser && !message && !files.length) return
  if (!currentAiSessionId.value) await newAiSession()
  const userMsg = pushUser
    ? { role: 'user', content: message, files: files.map((f) => ({ name: f.name })) }
    : null
  if (pushUser) {
    aiMessages.value.push(userMsg)
    aiInput.value = ''
    aiFiles.value = []
  }
  aiSending.value = true
  aiBuildStatus.value = 'running'
  aiBuildSteps.value = []
  aiBuildHandles = new Map()
  aiBuildHandleSeq = 0
  pushGraphHistoryNow()
  const assistantIdx = aiMessages.value.push({ role: 'assistant', content: '', tokens: null }) - 1
  let activeToolGroupIdx = -1
  let cumulativeTokens = {}
  const ws = new WebSocket(api.aiBuildWsUrl(current.value, currentAiSessionId.value))
  aiBuildWs = ws
  try {
    await new Promise((resolve, reject) => {
      ws.onopen = resolve
      ws.onerror = () => reject(new Error(t('app.aiBuilder.wsError')))
    })
    ws.send(JSON.stringify({
      type: 'init',
      message,
      history: aiMessages.value.filter((m) => m.content).map((m) => ({ role: m.role, content: m.content })).slice(-20),
      documents: aiMessages.value.flatMap((m) =>
        (m.files || []).filter((f) => f && typeof f === 'object' && f.text).map((f) => ({ name: f.name, text: f.text }))),
      current_graph: graph.serialize(),
      form_values: aiFormValues.value,
      ai_settings: aiBuilderSettings.value,
      limits: {
        max_tool_calls: aiBuilderSettings.value.max_tool_calls,
        max_repair_rounds: aiBuilderSettings.value.max_repair_rounds,
        timeout_seconds: aiBuilderSettings.value.timeout_seconds,
        retry_attempts: aiBuilderSettings.value.retry_attempts,
      },
    }))
    let finished = false
    const addAssistantText = (text) => {
      if (!text) return
      activeToolGroupIdx = -1
      const lastIdx = aiMessages.value.length - 1
      const last = aiMessages.value[lastIdx]
      if (last?.role === 'assistant' && !last.toolGroup && !last.form) {
        appendAssistantLine(lastIdx, text)
      } else {
        aiMessages.value.push({ role: 'assistant', content: text })
      }
    }
    const addOrUpdateToolStep = (step) => {
      upsertAiBuildStep(step)
      const last = aiMessages.value[aiMessages.value.length - 1]
      let idx = activeToolGroupIdx
      if (idx < 0 || !last?.toolGroup || aiMessages.value[idx] !== last) {
        idx = aiMessages.value.push({ role: 'assistant', toolGroup: { collapsed: true, steps: [] } }) - 1
        activeToolGroupIdx = idx
      }
      updateAiMessage(idx, (msg) => {
        const group = { ...(msg.toolGroup || { collapsed: true, steps: [] }) }
        const steps = [...(group.steps || [])]
        const key = step.call_id || step.id || `${step.tool}:${steps.length}`
        const pos = steps.findIndex((s) => (s.call_id || s.id) === key)
        const next = { ...step, call_id: key }
        if (pos >= 0) steps[pos] = { ...steps[pos], ...next }
        else steps.push(next)
        return { ...msg, toolGroup: { ...group, collapsed: group.collapsed ?? true, steps } }
      })
    }
    await new Promise((resolve) => {
      ws.onerror = () => {
        addAssistantText(t('app.aiBuilder.wsError'))
      }
      ws.onmessage = async (ev) => {
        let data
        try { data = JSON.parse(ev.data) } catch (_) { return }
        if (data.type === 'status') {
          aiBuildStatus.value = data.status || aiBuildStatus.value
          addAssistantText(data.message)
        } else if (data.type === 'message') {
          addAssistantText(data.content)
        } else if (data.type === 'usage') {
          cumulativeTokens = { ...cumulativeTokens, ...(data.usage || {}) }
          updateCurrentAiTokens({ ...cumulativeTokens, estimated: false })
        } else if (data.type === 'tokens') {
          cumulativeTokens = { ...cumulativeTokens, ...data }
          updateCurrentAiTokens({ ...cumulativeTokens })
        } else if (data.type === 'tool_step') {
          addOrUpdateToolStep(data.step)
        } else if (data.type === 'tool_call') {
          addOrUpdateToolStep({ call_id: data.id, tool: data.tool, args: data.args || {}, status: 'pending', result: null })
          const result = await executeAiToolCall(data)
          addOrUpdateToolStep({ call_id: data.id, tool: data.tool, args: data.args || {}, status: result.status, result: result.result })
          if (ws.readyState === WebSocket.OPEN) ws.send(JSON.stringify(result))
          else appendAssistantLine(assistantIdx, t('app.aiBuilder.wsClosedBeforeResult'))
        } else if (data.type === 'error') {
          aiBuildStatus.value = 'failed'
          addAssistantText(tr('app.aiBuilder.error', { message: data.message }))
        } else if (data.type === 'done') {
          finished = true
          aiBuildStatus.value = data.status || 'completed'
          if (data.message) addAssistantText(data.message)
          if (data.summary) addAssistantText(data.summary)
          if (data.status === 'completed') {
            autoLayoutNodes([...aiBuildHandles.values()], { anchor: 'right' })
          }
          status.value = data.status === 'completed' ? t('app.aiBuilder.completed') : t('app.aiBuilder.stopped')
          resolve()
        }
      }
      ws.onclose = (ev) => {
        if (!finished && aiBuildStatus.value === 'running') {
          aiBuildStatus.value = 'stopped'
          const reason = ev.reason || `code ${ev.code}`
          addAssistantText(tr('app.aiBuilder.disconnected', { reason }))
          status.value = t('app.aiBuilder.stopped')
        }
        resolve()
      }
    })
  } catch (e) {
    aiBuildStatus.value = 'failed'
    appendAssistantLine(assistantIdx, tr('app.aiBuilder.error', { message: e.message }))
  } finally {
    if (aiBuildWs === ws) aiBuildWs = null
    try { if (ws.readyState === WebSocket.OPEN) ws.close() } catch (_) {}
    aiSending.value = false
    await saveCurrentAiSession()
  }
}

function stopAiBuild() {
  if (aiBuildWs && aiBuildWs.readyState === WebSocket.OPEN) {
    aiBuildWs.send(JSON.stringify({ type: 'stop', reason: 'user_stop' }))
  }
  aiBuildStatus.value = 'stopped'
}

async function executeAiToolCall(call) {
  const permission = await decideAiToolPermission(call)
  if (permission.decision === 'rejected') {
    return aiToolResult(call, 'rejected', permission, { ok: false, error: { code: 'USER_REJECTED', message: t('app.aiBuilder.userRejected') } })
  }
  try {
    const result = await runAiCanvasTool(call.tool, call.args || {})
    const status = result.ok === false ? 'error' : 'ok'
    return aiToolResult(call, status, permission, result)
  } catch (e) {
    return aiToolResult(call, 'error', permission, { ok: false, error: { code: 'TOOL_ERROR', message: e.message } })
  }
}

async function decideAiToolPermission(call) {
  const autoTools = aiToolPermissions.value.auto_approved_tools || []
  if (call.risk !== 'write' || aiBuilderSettings.value.confirm_mode === 'auto' || autoTools.includes(call.tool)) {
    return { mode: aiBuilderSettings.value.confirm_mode || 'manual', decision: 'approved', remember_tool_type: false }
  }
  const decision = await askAiToolConfirm(call)
  if (decision === 'remember') {
    aiToolPermissions.value = { auto_approved_tools: [...new Set([...autoTools, call.tool])] }
    await saveCurrentAiSession()
    return { mode: 'manual', decision: 'approved', remember_tool_type: true }
  }
  return { mode: 'manual', decision: decision === 'approved' ? 'approved' : 'rejected', remember_tool_type: false }
}

function askAiToolConfirm(call) {
  aiConfirmCall.value = call
  return new Promise((resolve) => { aiConfirmResolver = resolve })
}

function resolveAiConfirm(decision) {
  const resolve = aiConfirmResolver
  aiConfirmCall.value = null
  aiConfirmResolver = null
  resolve && resolve(decision)
}

function aiToolResult(call, status, permission, result) {
  return {
    type: 'tool_result',
    tool_call_id: call.id,
    tool: call.tool,
    status,
    permission,
    result,
    log: { tool: call.tool, args: call.args || {}, result, status },
  }
}

function upsertAiBuildStep(step) {
  const key = step.call_id || step.id || `${step.tool}:${aiBuildSteps.value.length}`
  const idx = aiBuildSteps.value.findIndex((s) => (s.call_id || s.id) === key)
  const next = { ...step, call_id: key }
  if (idx >= 0) aiBuildSteps.value[idx] = { ...aiBuildSteps.value[idx], ...next }
  else aiBuildSteps.value.push(next)
}

async function runAiCanvasTool(tool, args) {
  if (tool === 'inspect_canvas') return inspectAiCanvas(args)
  if (tool === 'list_node_types') return listAiNodeTypes(args)
  if (tool === 'read_node_spec') return readAiNodeSpec(args)
  if (tool === 'create_node') return createAiNode(args)
  if (tool === 'set_node_property') return setAiNodeProperty(args)
  if (tool === 'set_node_ports') return setAiNodePorts(args)
  if (tool === 'connect_nodes') return connectAiNodes(args)
  if (tool === 'delete_node') return deleteAiNode(args)
  if (tool === 'delete_link') return deleteAiLink(args)
  if (tool === 'validate_canvas') return validateAiCanvas()
  if (tool === 'finish_build') return validateAiCanvas()
  return { ok: false, error: { code: 'UNKNOWN_TOOL', message: tool } }
}

function specSummary(spec) {
  return {
    type: spec.type,
    title: spec.title,
    category: spec.category,
    description: spec.description || '',
    inputs: spec.inputs || [],
    outputs: spec.outputs || [],
    properties: spec.properties || [],
  }
}

function nodeSpecByType(type) {
  return catalogNodes.value.find((n) => n.type === type)
}

function inspectAiCanvas() {
  const nodes = (graph?._nodes || []).map((n) => ({
    id: n.id,
    ref: `external:${n.id}`,
    type: nodeTypeOf(n),
    title: n.title || '',
    inputs: (n.inputs || []).map((p) => ({ name: p.name, type: p.type, link: p.link })),
    outputs: (n.outputs || []).map((p) => ({ name: p.name, type: p.type, links: p.links || [] })),
    properties: n.properties || {},
  }))
  return { ok: true, nodes, links: graph?.links || {}, handles: Object.fromEntries([...aiBuildHandles.entries()].map(([h, n]) => [h, n.id])) }
}

function listAiNodeTypes(args) {
  const category = String(args?.category || '').trim()
  const nodes = catalogNodes.value
    .filter((n) => !category || n.category === category || n.type.startsWith(category + '/'))
    .map((n) => ({ type: n.type, title: n.title, category: n.category, description: n.description || '' }))
  return { ok: true, nodes }
}

async function readAiNodeSpec(args) {
  const type = String(args?.type || '')
  try {
    const data = await api.nodeSpec(type)
    return { ok: true, spec: data.spec, doc: data.doc || data.spec?.description || '' }
  } catch (e) {
    const spec = nodeSpecByType(type)
    if (!spec) return { ok: false, error: { code: 'NODE_TYPE_NOT_FOUND', message: type } }
    return { ok: true, spec: specSummary(spec), doc: spec.description || '' }
  }
}

function resolveAiNodeRef(ref) {
  const text = String(ref || '')
  if (aiBuildHandles.has(text)) return aiBuildHandles.get(text)
  if (text.startsWith('external:')) return graph.getNodeById(Number(text.slice('external:'.length)))
  return null
}

function createAiNode(args) {
  const type = String(args.type || '')
  const spec = nodeSpecByType(type)
  if (!spec) return { ok: false, error: { code: 'NODE_TYPE_NOT_FOUND', message: type } }
  const node = LiteGraph.createNode(type)
  if (!node) return { ok: false, error: { code: 'CREATE_NODE_FAILED', message: type } }
  if (args.title) node.title = String(args.title).slice(0, 120)
  const pos = Array.isArray(args.pos) ? args.pos : []
  node.pos = [Number(pos[0] ?? 120), Number(pos[1] ?? 330)]
  for (const [key, value] of Object.entries(args.properties || {})) {
    if (node.setProperty) node.setProperty(key, value)
    else node.properties[key] = value
  }
  graph.add(node)
  const handle = `n${++aiBuildHandleSeq}`
  aiBuildHandles.set(handle, node)
  markAiGraphChanged()
  return { ok: true, handle, canvas_id: node.id, inputs: node.inputs || [], outputs: node.outputs || [], properties: node.properties || {} }
}

function setAiNodeProperty(args) {
  const node = resolveAiNodeRef(args.ref)
  if (!node) return { ok: false, error: { code: 'NODE_NOT_FOUND', message: String(args.ref || '') } }
  const spec = node._spec || nodeSpecByType(nodeTypeOf(node))
  const prop = (spec?.properties || []).find((p) => p.name === args.name)
  if (!prop) return { ok: false, error: { code: 'PROPERTY_NOT_FOUND', message: String(args.name || '') } }
  const value = normalizeFormValue(args.value, prop.type)
  if (node.setProperty) node.setProperty(args.name, value)
  else node.properties[args.name] = value
  markAiGraphChanged()
  return { ok: true }
}

const AI_SCRIPT_PORT_TYPES = new Set(['match', 'point', 'text', 'number', 'bool', 'picture', 'mask', 'ocr', 'device', 'script'])

function normalizeAiPortRows(rows) {
  const out = []
  const seen = new Set()
  for (const row of Array.isArray(rows) ? rows : []) {
    const name = String(row?.name || '').trim()
    const type = String(row?.type || '').trim()
    if (!name || !type) return { ok: false, error: { code: 'BAD_PORT', message: `${name}:${type}` } }
    if (seen.has(name)) return { ok: false, error: { code: 'DUPLICATE_PORT', message: name } }
    if (!AI_SCRIPT_PORT_TYPES.has(type)) return { ok: false, error: { code: 'BAD_PORT_TYPE', message: type } }
    seen.add(name)
    out.push({ name, type })
  }
  return { ok: true, ports: out }
}

function setDynamicPorts(node, dir, rows) {
  const fixed = dir === 'in' ? new Set(['in', 'script']) : new Set(['out'])
  const list = () => (dir === 'in' ? node.inputs : node.outputs) || []
  const find = (name) => (dir === 'in' ? node.findInputSlot(name) : node.findOutputSlot(name))
  const del = (slot) => (dir === 'in' ? node.removeInput(slot) : node.removeOutput(slot))
  const add = (name, type) => (dir === 'in' ? node.addInput(name, type) : node.addOutput(name, type))
  for (const row of rows) {
    if (fixed.has(row.name)) return { ok: false, error: { code: 'FIXED_PORT', message: row.name } }
  }
  const keep = new Set(rows.map((r) => r.name))
  for (const port of [...list()]) {
    if (!fixed.has(port.name) && !keep.has(port.name)) {
      const slot = find(port.name)
      if (slot >= 0) del(slot)
    }
  }
  for (const row of rows) {
    const slot = find(row.name)
    if (slot >= 0) {
      const port = list()[slot]
      if (port.type !== row.type) {
        port.type = row.type
        if (dir === 'in') node.disconnectInput(slot)
        else node.disconnectOutput(slot)
      }
    } else {
      add(row.name, row.type)
    }
  }
  return { ok: true }
}

function setAiNodePorts(args) {
  const node = resolveAiNodeRef(args.ref)
  if (!node) return { ok: false, error: { code: 'NODE_NOT_FOUND', message: String(args.ref || '') } }
  if (nodeTypeOf(node) !== 'script/exec') return { ok: false, error: { code: 'PORTS_NOT_EDITABLE', message: nodeTypeOf(node) } }
  if (Object.prototype.hasOwnProperty.call(args || {}, 'inputs')) {
    const inputs = normalizeAiPortRows(args.inputs)
    if (!inputs.ok) return inputs
    const result = setDynamicPorts(node, 'in', inputs.ports)
    if (!result.ok) return result
  }
  if (Object.prototype.hasOwnProperty.call(args || {}, 'outputs')) {
    const outputs = normalizeAiPortRows(args.outputs)
    if (!outputs.ok) return outputs
    const result = setDynamicPorts(node, 'out', outputs.ports)
    if (!result.ok) return result
  }
  markAiGraphChanged()
  return { ok: true, inputs: node.inputs || [], outputs: node.outputs || [] }
}

function connectAiNodes(args) {
  const src = resolveAiNodeRef(args.from)
  const dst = resolveAiNodeRef(args.to)
  if (!src || !dst) return { ok: false, error: { code: 'NODE_NOT_FOUND', message: `${args.from} -> ${args.to}` } }
  const outSlot = src.findOutputSlot(args.out)
  const inSlot = dst.findInputSlot(args.in)
  if (outSlot < 0 || inSlot < 0) return { ok: false, error: { code: 'PORT_NOT_FOUND', message: `${args.out} -> ${args.in}` } }
  const before = JSON.stringify(dst.inputs?.[inSlot]?.link ?? null)
  src.connect(outSlot, dst, inSlot)
  const after = JSON.stringify(dst.inputs?.[inSlot]?.link ?? null)
  if (before === after) return { ok: false, error: { code: 'CONNECT_FAILED', message: `${args.out} -> ${args.in}` } }
  markAiGraphChanged()
  return { ok: true }
}

function deleteAiNode(args) {
  const node = resolveAiNodeRef(args.ref)
  if (!node) return { ok: false, error: { code: 'NODE_NOT_FOUND', message: String(args.ref || '') } }
  graph.remove(node)
  markAiGraphChanged()
  return { ok: true }
}

function deleteAiLink(args) {
  const src = resolveAiNodeRef(args.from)
  const dst = resolveAiNodeRef(args.to)
  if (!src || !dst) return { ok: false, error: { code: 'NODE_NOT_FOUND', message: `${args.from} -> ${args.to}` } }
  const outSlot = src.findOutputSlot(args.out)
  const inSlot = dst.findInputSlot(args.in)
  const input = dst.inputs?.[inSlot]
  if (outSlot < 0 || inSlot < 0 || input?.link == null) return { ok: false, error: { code: 'LINK_NOT_FOUND', message: `${args.out} -> ${args.in}` } }
  dst.disconnectInput(inSlot)
  markAiGraphChanged()
  return { ok: true }
}

function validateAiCanvas() {
  const errors = []
  const nodes = graph?._nodes || []
  if (!nodes.length) errors.push({ code: 'EMPTY_GRAPH', message: 'canvas has no nodes' })
  if (!nodes.some((n) => nodeTypeOf(n) === 'flow/start')) errors.push({ code: 'NO_START_NODE', message: 'missing flow/start' })
  for (const n of nodes) {
    const spec = n._spec || nodeSpecByType(nodeTypeOf(n))
    if (!spec) errors.push({ code: 'UNKNOWN_NODE_TYPE', message: nodeTypeOf(n), node: n.id })
    for (const input of n.inputs || []) {
      if (input.type === 'exec') continue
      const specInput = (spec?.inputs || []).find((p) => p.name === input.name)
      if (specInput?.required && input.link == null && !requiredInputSatisfiedByProperty(n, specInput)) {
        errors.push({ code: 'MISSING_REQUIRED_INPUT', message: input.name, node: n.id })
      }
    }
    for (const prop of spec?.properties || []) {
      if (prop.required && !requiredPropertySatisfied(n, prop)) {
        errors.push({ code: 'MISSING_REQUIRED_PROPERTY', message: prop.name, node: n.id })
      }
    }
  }
  return { ok: !errors.length, errors, warnings: [] }
}

function requiredInputSatisfiedByProperty(node, input) {
  const value = node.properties?.[input.name]
  return value !== undefined && value !== null && String(value).trim() !== ''
}

function requiredPropertySatisfied(node, prop) {
  const inputSlot = node.findInputSlot ? node.findInputSlot(prop.name) : -1
  if (inputSlot >= 0 && node.inputs?.[inputSlot]?.link != null) return true
  const value = node.properties?.[prop.name]
  if (prop.type === 'bool') return value !== undefined && value !== null
  return value !== undefined && value !== null && String(value).trim() !== ''
}

function markAiGraphChanged() {
  refreshGraphI18n()
  lgcanvas && lgcanvas.setDirty(true, true)
  scheduleGraphHistory()
}

async function requestAiDraft(message, files = [], pushUser = false) {
  if (!current.value || aiSending.value) return
  if (pushUser && !message && !files.length) return
  if (!currentAiSessionId.value) await newAiSession()
  const userMsg = pushUser
    ? { role: 'user', content: message, files: files.map((f) => ({ name: f.name })) }
    : null
  if (pushUser) {
    aiMessages.value.push(userMsg)
    aiInput.value = ''
    aiFiles.value = []
  }
  aiSending.value = true
  const assistantMsg = { role: 'assistant', content: '', thoughts: [], thoughtsCollapsed: false, tokens: { completion_tokens: 0, estimated: true } }
  const assistantIdx = aiMessages.value.push(assistantMsg) - 1
  try {
    const state = {
      message,
      history: aiMessages.value
        .filter((m) => m.content)
        .map((m) => ({ role: m.role, content: m.content }))
        .slice(-20),
      documents: aiMessages.value.flatMap((m) =>
        (m.files || []).filter((f) => f && typeof f === 'object' && f.text).map((f) => ({ name: f.name, text: f.text }))),
      draft_patch: aiDraft.value?.graph_patch || aiDraft.value?.dsl || null,
      draft_dsl: aiDraft.value?.graph_patch || aiDraft.value?.dsl || null,
      current_graph: graph.serialize(),
      ai_settings: aiBuilderSettings.value,
      form_values: aiFormValues.value,
    }
    const res = await api.aiDraftStream(current.value, currentAiSessionId.value, state, files)
    await readSse(res, (event, data) => {
      if (event === 'status') appendAssistantLine(assistantIdx, data.message)
      else if (event === 'docs' && userMsg) {
        userMsg.files = (data.docs || []).map((d) => ({ name: d.name, text: d.text }))
        const userIdx = aiMessages.value.indexOf(userMsg)
        if (userIdx >= 0) aiMessages.value[userIdx] = { ...userMsg }
      }
      else if (event === 'message') appendAssistantLine(assistantIdx, data.content)
      else if (event === 'thought') updateAiThought(assistantIdx, data)
      else if (event === 'form') aiMessages.value.push({ role: 'assistant', content: '', form: hydrateAiForm(data.form) })
      else if (event === 'delta') updateAiMessage(assistantIdx, (m) => ({ ...m, stream: (m.stream || '') + (data.text || '') }))
      else if (event === 'tokens') updateAiMessage(assistantIdx, (m) => ({ ...m, tokens: { ...(m.tokens || {}), ...data } }))
      else if (event === 'usage') updateAiMessage(assistantIdx, (m) => ({ ...m, tokens: { ...(data.usage || {}), estimated: false } }))
      else if (event === 'draft') {
        aiDraft.value = data.draft
        status.value = t('app.status.aiDraftReady')
      } else if (event === 'error') {
        appendAssistantLine(assistantIdx, tr('app.aiBuilder.error', { message: data.message }))
      }
    })
  } catch (e) {
    appendAssistantLine(assistantIdx, tr('app.aiBuilder.error', { message: e.message }))
  } finally {
    aiSending.value = false
    await saveCurrentAiSession()
  }
}

function tokenUsageLabel(tokens) {
  const prompt = tokens.prompt_tokens
  const completion = tokens.completion_tokens || 0
  const total = tokens.total_tokens
  if (Number.isFinite(total)) {
    return tr('app.aiBuilder.usageFull', { prompt, completion, total })
  }
  return tr('app.aiBuilder.usageCompletion', { completion }) + (tokens.estimated ? t('app.aiBuilder.usageEstimated') : '')
}

function updateAiMessage(index, updater) {
  const currentMsg = aiMessages.value[index]
  if (!currentMsg) return
  aiMessages.value[index] = updater(currentMsg)
}

function appendAssistantLine(index, line) {
  if (!line) return
  updateAiMessage(index, (msg) => ({
    ...msg,
    content: msg.content ? `${msg.content}\n${line}` : line,
  }))
}

function updateCurrentAiTokens(tokens) {
  const lastIdx = aiMessages.value.length - 1
  const last = aiMessages.value[lastIdx]
  if (last?.role === 'assistant' && !last.toolGroup && !last.form) {
    updateAiMessage(lastIdx, (m) => ({ ...m, tokens }))
  } else {
    updateAiMessage(0, (m) => m)
    aiMessages.value.push({ role: 'assistant', content: '', tokens })
  }
}

function updateAiThought(index, item) {
  if (!item?.node) return
  updateAiMessage(index, (msg) => {
    const thoughts = [...(msg.thoughts || [])]
    const next = {
      node: item.node,
      title: item.title || item.node,
      detail: item.detail || '',
      status: item.status || 'active',
      time: Date.now(),
    }
    const existing = thoughts.findIndex((t) => t.node === next.node)
    if (existing >= 0) thoughts[existing] = { ...thoughts[existing], ...next }
    else thoughts.push(next)
    return { ...msg, thoughts, thoughtsCollapsed: msg.thoughtsCollapsed ?? false }
  })
}

function toggleAiThoughts(index) {
  updateAiMessage(index, (msg) => ({ ...msg, thoughtsCollapsed: !msg.thoughtsCollapsed }))
}

function toggleAiToolGroup(index) {
  updateAiMessage(index, (msg) => ({
    ...msg,
    toolGroup: { ...(msg.toolGroup || {}), collapsed: !msg.toolGroup?.collapsed },
  }))
}

function aiToolGroupLatest(group) {
  const latest = (group?.steps || [])[Math.max(0, (group?.steps || []).length - 1)]
  if (!latest) return ''
  return `${latest.tool} ${latest.status || ''}`.trim()
}

async function readSse(response, onEvent) {
  if (!response.body) return
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  while (true) {
    const { value, done } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buffer.indexOf('\n\n')) >= 0) {
      const raw = buffer.slice(0, idx)
      buffer = buffer.slice(idx + 2)
      const evt = parseSseEvent(raw)
      if (evt) onEvent(evt.event, evt.data)
    }
  }
  buffer += decoder.decode()
  if (buffer.trim()) {
    const evt = parseSseEvent(buffer)
    if (evt) onEvent(evt.event, evt.data)
  }
}

function parseSseEvent(raw) {
  let event = 'message'
  const dataLines = []
  for (const line of raw.split(/\r?\n/)) {
    if (line.startsWith('event:')) event = line.slice(6).trim()
    else if (line.startsWith('data:')) dataLines.push(line.slice(5).trimStart())
  }
  if (!dataLines.length) return null
  try {
    return { event, data: JSON.parse(dataLines.join('\n')) }
  } catch (_) {
    return null
  }
}

function hydrateAiForm(form) {
  const f = { ...form, submitted: false }
  if (f.kind === 'device') {
    f.values = { type: f.type || f.devices?.[0]?.type || 'device/rdp', properties: {} }
    fillDeviceDefaults(f)
  } else if (f.kind === 'graph_nodes') {
    f.values = { ...(f.values || {}) }
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
  if (!canSubmitAiForm(form)) {
    form.error = t('app.aiBuilder.imageNodeRequired')
    refreshAiMessages()
    return
  }
  const values = normalizeAiFormValues(form)
  aiFormValues.value = { ...aiFormValues.value, [form.id]: values }
  if (aiNodePick.value?.form === form) aiNodePick.value = null
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
  if (form.kind === 'graph_nodes') return { ...(form.values || {}) }
  const out = {}
  for (const f of form.fields || []) out[f.name] = normalizeFormValue(form.values[f.name], f.type)
  return out
}

function canSubmitAiForm(form) {
  return form.kind !== 'graph_nodes' || !!form.values?.image_node_id
}

function toggleAiNodePick(form, kind) {
  if (form.submitted) return
  if (aiNodePick.value?.form === form && aiNodePick.value?.kind === kind) {
    aiNodePick.value = null
    form.error = ''
    refreshAiMessages()
    return
  }
  aiNodePick.value = { form, kind }
  form.error = ''
  refreshAiMessages()
}

function isAiPickingNode(form, kind) {
  return aiNodePick.value?.form === form && aiNodePick.value?.kind === kind
}

function graphNodeSelectionLabel(form, kind) {
  const values = form.values || {}
  if (kind === 'image') return values.image_label || t('app.aiBuilder.notSelected')
  return values.mask_label || t('app.aiBuilder.notSelected')
}

function refreshAiMessages() {
  aiMessages.value = [...aiMessages.value]
}

function nodeTypeOf(node) {
  return node?._spec?.type || node?.type || ''
}

function graphNodeLabel(node, kind) {
  const props = node?.properties || {}
  const file = kind === 'image' ? props.name : props.mask
  const title = node?.title || nodeTypeOf(node)
  return file ? `${title} #${node.id} (${file})` : `${title} #${node.id}`
}

function onGraphSelectionForAi(selected) {
  const pick = aiNodePick.value
  if (!pick?.form || pick.form.submitted) return
  const nodes = Array.isArray(selected) ? selected : Object.values(selected || {})
  const node = nodes.find(Boolean)
  if (!node) return
  const expected = pick.kind === 'image' ? 'const/image' : 'mask/create'
  const actual = nodeTypeOf(node)
  if (actual !== expected) {
    pick.form.error = pick.kind === 'image'
      ? t('app.aiBuilder.invalidImageNode')
      : t('app.aiBuilder.invalidMaskNode')
    refreshAiMessages()
    return
  }
  pick.form.values ||= {}
  if (pick.kind === 'image') {
    pick.form.values.image_node_id = node.id
    pick.form.values.image_node_type = actual
    pick.form.values.image_name = node.properties?.name || ''
    pick.form.values.image_title = node.title || ''
    pick.form.values.image_label = graphNodeLabel(node, 'image')
  } else {
    pick.form.values.mask_node_id = node.id
    pick.form.values.mask_node_type = actual
    pick.form.values.mask_name = node.properties?.mask || ''
    pick.form.values.mask_title = node.title || ''
    pick.form.values.mask_label = graphNodeLabel(node, 'mask')
  }
  pick.form.error = ''
  aiNodePick.value = null
  refreshAiMessages()
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
  if (step.type) {
    const spec = catalogNodes.value.find((n) => n.type === step.type)
    const title = spec ? nodeTitle(spec) : step.type
    return `${step.id || ''} ${title}`.trim()
  }
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

function addDraftPorts(node, spec) {
  if (nodeTypeOf(node) !== 'script/exec') return
  const addOne = (dir, port) => {
    const name = String(port?.name || '').trim()
    const type = String(port?.type || '').trim()
    if (!name || !AI_SCRIPT_PORT_TYPES.has(type)) return
    if (dir === 'in') {
      if (name === 'in' || name === 'script' || node.findInputSlot(name) >= 0) return
      node.addInput(name, type)
    } else {
      if (name === 'out' || node.findOutputSlot(name) >= 0) return
      node.addOutput(name, type)
    }
  }
  for (const port of spec.inputs || []) addOne('in', port)
  for (const port of spec.outputs || []) addOne('out', port)
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
    addDraftPorts(node, spec)
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
  if (!autoLayoutNodes([...created.values()], { anchor: 'right' })) locateGraph()
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

onMounted(async () => {
  installLiteGraphI18n()
  const catalog = await api.catalog()
  registerCatalog(catalog)
  catalogNodes.value = catalog.nodes
  applyNodeTypeTitles()

  graph = new LGraph()
  installGraphHistoryHooks()
  lgcanvas = new LGraphCanvas(canvasEl.value, graph)
  installMultiSelectDrag(lgcanvas)
  const prevSelectionChange = lgcanvas.onSelectionChange
  lgcanvas.onSelectionChange = function (selectedNodes) {
    prevSelectionChange && prevSelectionChange.call(this, selectedNodes)
    onGraphSelectionForAi(selectedNodes)
  }
  resize()
  window.addEventListener('resize', resize)
  window.addEventListener('keydown', onGlobalKeyDown, true)

  overlay = new VideoOverlay(lgcanvas, overlayEl.value)
  shots = new ShotOverlay(lgcanvas, overlayEl.value)
  shots.setRenameHandler(onRenameImage)
  codes = new CodeOverlay(lgcanvas, overlayEl.value)
  errors = new ErrorOverlay(lgcanvas, overlayEl.value)
  const prevForeground = lgcanvas.onDrawForeground
  lgcanvas.onDrawForeground = function (ctx) {
    prevForeground && prevForeground.call(this, ctx)
    reconcileInteractions()   // 连线/连接状态变化时挂载/卸载交互画面
    reconcilePreviews()       // 图片预览节点跟随上游图片
    overlay.update()
    shots.update(graph._nodes)   // 截图/模板/预览节点画面 + 裁剪框定位
    codes.update(graph._nodes)   // 脚本节点多行代码编辑器
    errors.update(graph._nodes)  // 运行错误（可选中/可复制）
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
  window.removeEventListener('keydown', onGlobalKeyDown, true)
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
  aiSessions.value = []
  currentAiSessionId.value = ''
  await loadAiSessions({ selectFirst: true })
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
    reasoning_effort: normalizeReasoningEffort(raw.reasoning_effort),
    confirm_mode: raw.confirm_mode === 'auto' ? 'auto' : 'manual',
    max_tool_calls: clampInt(raw.max_tool_calls, DEFAULT_AI_BUILDER_SETTINGS.max_tool_calls, 1, 200),
    max_repair_rounds: clampInt(raw.max_repair_rounds, DEFAULT_AI_BUILDER_SETTINGS.max_repair_rounds, 0, 50),
    timeout_seconds: clampInt(raw.timeout_seconds, DEFAULT_AI_BUILDER_SETTINGS.timeout_seconds, 5, 600),
    retry_attempts: clampInt(raw.retry_attempts, DEFAULT_AI_BUILDER_SETTINGS.retry_attempts, 1, 10),
  }
}

function normalizeReasoningEffort(value) {
  const text = String(value ?? '')
  return ['', 'low', 'medium', 'high'].includes(text) ? text : ''
}

function clampAiTemperature(value, fallback) {
  const n = Number(value)
  if (!Number.isFinite(n)) return fallback
  return Math.min(2, Math.max(0, n))
}

function clampInt(value, fallback, min, max) {
  const n = parseInt(value, 10)
  if (!Number.isFinite(n)) return fallback
  return Math.min(max, Math.max(min, n))
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
.ai-session-bar { flex: 0 0 auto; display: grid; grid-template-columns: 1fr auto auto auto; gap: 6px;
  padding: 8px; background: #202020; border-bottom: 1px solid #333; }
.ai-session-bar select, .ai-session-bar button {
  min-width: 0; box-sizing: border-box; background: #111; color: #eee; border: 1px solid #444;
  border-radius: 4px; padding: 4px 6px; font: 12px system-ui, sans-serif;
}
.ai-session-bar button { cursor: pointer; background: #333; }
.ai-session-bar button:disabled { opacity: .55; cursor: default; }
.ai-chat { flex: 1; min-height: 0; overflow: auto; padding: 10px; display: flex; flex-direction: column; gap: 8px; }
.ai-msg { border: 1px solid #333; background: #242424; border-radius: 6px; padding: 8px; }
.ai-msg.user { background: #24313a; border-color: #38515f; }
.ai-role { color: #9fd0ff; font-size: 11px; margin-bottom: 4px; }
.ai-text { line-height: 1.45; overflow-wrap: anywhere; }
.ai-text :first-child { margin-top: 0; }
.ai-text :last-child { margin-bottom: 0; }
.ai-text p { margin: 0 0 8px; }
.ai-text h1, .ai-text h2, .ai-text h3 { margin: 10px 0 6px; line-height: 1.25; color: #f4f7fb; }
.ai-text h1 { font-size: 18px; }
.ai-text h2 { font-size: 16px; }
.ai-text h3 { font-size: 14px; }
.ai-text ul, .ai-text ol { margin: 6px 0 8px; padding-left: 20px; }
.ai-text li { margin: 2px 0; }
.ai-text blockquote { margin: 8px 0; padding: 5px 8px; border-left: 3px solid #557086;
  background: #1b252b; color: #cbd5df; }
.ai-text code { background: #111; border: 1px solid #333; border-radius: 3px; padding: 1px 4px;
  color: #e8edf2; font: 12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; }
.ai-text pre { margin: 8px 0; padding: 8px; overflow: auto; background: #111; border: 1px solid #333;
  border-radius: 4px; color: #e8edf2; }
.ai-text pre code { background: transparent; border: none; padding: 0; }
.ai-text a { color: #8cc8ff; text-decoration: underline; }
.ai-text table { width: 100%; border-collapse: collapse; margin: 8px 0; font-size: 12px; }
.ai-text th, .ai-text td { border: 1px solid #3a4650; padding: 4px 6px; }
.ai-text th { background: #1f2a30; }
.ai-thoughts { margin-top: 6px; border: 1px solid #34424a; border-radius: 4px; background: #171d21; overflow: hidden; }
.ai-thoughts-head { width: 100%; display: flex; justify-content: space-between; align-items: center;
  background: #202b31; color: #d9edf7; border: none; padding: 5px 8px; cursor: pointer; font-size: 12px; }
.ai-thought-list { list-style: none; margin: 0; padding: 8px 8px 8px 18px; }
.ai-thought-item { position: relative; display: grid; grid-template-columns: 14px 1fr; gap: 6px;
  padding: 0 0 8px; color: #cbd5df; font-size: 12px; line-height: 1.35; }
.ai-thought-item:not(:last-child)::after { content: ""; position: absolute; left: 6px; top: 14px; bottom: 0;
  border-left: 1px solid #41525b; }
.ai-thought-dot { width: 9px; height: 9px; margin-top: 3px; border-radius: 50%; background: #64748b; z-index: 1; }
.ai-thought-item.active .ai-thought-dot { background: #f6ad55; animation: thoughtPulse 1s ease-in-out infinite; }
.ai-thought-item.done .ai-thought-dot { background: #68d391; }
.ai-thought-item.error .ai-thought-dot { background: #fc8181; }
.ai-thought-title { font-weight: 700; }
.ai-thought-detail { margin-top: 2px; color: #9fb4c0; }
.ai-tool-group { margin-top: 6px; border: 1px solid #3a4650; border-radius: 4px; background: #151b20; overflow: hidden; }
.ai-tool-group-head { width: 100%; display: flex; justify-content: space-between; align-items: center;
  background: #1f2930; color: #d9edf7; border: none; padding: 5px 8px; cursor: pointer; font-size: 12px; }
.ai-tool-list { list-style: none; margin: 0; padding: 6px 8px; }
.ai-tool-item { padding: 4px 0; border-bottom: 1px solid #26323a; font-size: 12px; }
.ai-tool-item:last-child { border-bottom: 0; }
.ai-tool-main { display: flex; justify-content: space-between; gap: 8px; }
.ai-tool-item.pending .ai-tool-main span { color: #f6ad55; }
.ai-tool-item.ok .ai-tool-main span { color: #68d391; }
.ai-tool-item.error .ai-tool-main span, .ai-tool-item.rejected .ai-tool-main span { color: #fc8181; }
.ai-tool-item small { display: block; margin-top: 2px; color: #ff9b9b; word-break: break-word; }
@keyframes thoughtPulse {
  0%, 100% { box-shadow: 0 0 0 0 rgba(246, 173, 85, .55); transform: scale(1); }
  50% { box-shadow: 0 0 0 5px rgba(246, 173, 85, 0); transform: scale(1.18); }
}
.ai-stream { margin: 6px 0 0; max-height: 160px; overflow: auto; white-space: pre-wrap; word-break: break-word;
  background: #111; border: 1px solid #333; border-radius: 4px; padding: 6px; color: #cbd5df;
  font: 11px/1.45 monospace; }
.ai-usage { margin-top: 6px; color: #9fb4c0; font-size: 11px; font-family: monospace; }
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
.ai-node-pickers { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
.ai-node-pickers button.active { background: #b7791f; color: #fff; }
.ai-selection-result { border: 1px solid #333; border-radius: 4px; background: #171717; padding: 6px 8px;
  color: #cbd5df; font-size: 12px; line-height: 1.55; word-break: break-word; }
.ai-form-error { color: #ff9b9b; margin-top: 4px; }
.ai-draft { flex: 0 0 auto; max-height: 240px; overflow: auto; border-top: 1px solid #333; border-bottom: 1px solid #333;
  padding: 10px; background: #1a1d20; display: flex; flex-direction: column; gap: 6px; }
.ai-draft-head { display: flex; justify-content: space-between; gap: 10px; align-items: baseline; }
.ai-draft-head span { color: #9fb4c0; font-size: 12px; white-space: nowrap; }
.ai-draft-summary { color: #ddd; line-height: 1.4; }
.ai-draft ol { margin: 0; padding-left: 20px; }
.ai-draft li { padding: 2px 0; }
.ai-build-steps { flex: 0 0 auto; max-height: 180px; overflow: auto; border-top: 1px solid #333;
  padding: 8px 10px; background: #171d21; }
.ai-build-title { color: #9fd0ff; font-weight: 700; margin-bottom: 4px; }
.ai-build-steps ol { margin: 0; padding-left: 20px; }
.ai-build-steps li { display: grid; grid-template-columns: 1fr auto; gap: 6px; padding: 2px 0; font-size: 12px; }
.ai-build-steps li small { grid-column: 1 / -1; color: #ff9b9b; }
.ai-build-steps li.ok span { color: #68d391; }
.ai-build-steps li.error span, .ai-build-steps li.rejected span { color: #fc8181; }
.ai-confirm-modal { position: absolute; inset: 0; z-index: 340; background: rgba(0,0,0,.55);
  display: flex; align-items: center; justify-content: center; }
.ai-confirm-dialog { width: min(520px, 92vw); background: #1f1f1f; color: #ddd; border-radius: 6px;
  box-shadow: 0 8px 30px rgba(0,0,0,.6); overflow: hidden; }
.ai-confirm-head { padding: 8px 12px; background: #2b2b2b; }
.ai-confirm-body { padding: 10px; }
.ai-confirm-body pre { max-height: 260px; overflow: auto; background: #111; border: 1px solid #333; padding: 8px; }
.ai-confirm-foot { display: flex; justify-content: flex-end; gap: 8px; padding: 8px 12px; background: #262626; }
.ai-confirm-foot button { padding: 5px 12px; border: none; border-radius: 4px; cursor: pointer; background: #3a3a3a; color: #ddd; }
.ai-confirm-foot .primary { background: #2b6cb0; color: #fff; }
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
