// 把 /api/nodes 目录注册成 LiteGraph 节点类型，带类型上色与连线校验。
import { LiteGraph, LGraphCanvas } from 'litegraph.js'
import { showNodeHelp } from './help-dialog.js'
import { openPortEditor, EDITABLE_TYPES } from './port-editor.js'
import { t } from '../i18n.js'

const EXEC = 'exec', BUNDLE = 'bundle', ANY = 'any', DEVICE = 'device'

// 类型兼容（与服务端 flow/types.py 一致）
function compatible(src, dst) {
  if (src === EXEC || dst === EXEC) return src === EXEC && dst === EXEC
  if (src === BUNDLE || dst === BUNDLE) return src === BUNDLE && dst === BUNDLE
  if (src === ANY || dst === ANY) return true
  return src === dst
}

let CATALOG = null
let deviceActionHandler = null
let captureHandler = null
let imageActionHandler = null
let maskActionHandler = null

function requestGraphHistory(node) {
  node?.graph?._requestHistory && node.graph._requestHistory()
}

export function setDeviceActionHandler(fn) { deviceActionHandler = fn }
export function setCaptureHandler(fn) { captureHandler = fn }
export function setImageActionHandler(fn) { imageActionHandler = fn }
export function setMaskActionHandler(fn) { maskActionHandler = fn }

export function registerCatalog(catalog) {
  CATALOG = catalog
  // 屏蔽 LiteGraph 内置节点（math/const/events…），只保留项目目录里的节点
  LiteGraph.clearRegisteredTypes()
  // 连线按类型上色
  LGraphCanvas.link_type_colors = LGraphCanvas.link_type_colors || {}
  for (const [t, color] of Object.entries(catalog.types)) {
    LGraphCanvas.link_type_colors[t] = color
  }

  for (const spec of catalog.nodes) {
    registerOne(spec)
  }
}

function markI18nWidget(widget, key, prefix = '') {
  widget._i18nKey = key
  widget._i18nPrefix = prefix
  refreshI18nWidget(widget)
}

function refreshI18nWidget(widget) {
  if (!widget?._i18nKey) return
  const label = (widget._i18nPrefix || '') + t(widget._i18nKey)
  widget.name = label
  widget.label = label
}

function registerOne(spec) {
  function NodeClass() {
    const isDeviceSource = (spec.outputs || []).some((o) => o.type === DEVICE)
    for (const p of spec.inputs || []) this.addInput(p.name, p.type)
    for (const p of spec.outputs || []) this.addOutput(p.name, p.type)
    // 属性 → widget
    this.properties = this.properties || {}
    for (const prop of spec.properties || []) {
      this.properties[prop.name] = prop.default
      addWidgetFor(this, prop)
    }
    this._spec = spec
    // 设备源节点（输出 device 句柄）：仅连接/断开按钮。「设备属性」无 device 输出 → 不加按钮
    if (isDeviceSource) {
      this._devicePropertyWidgets = (this.widgets || []).slice()
      this._deviceActionWidget = this.addWidget('button', t('graph.widgets.connect'), null, () => {
        deviceActionHandler && deviceActionHandler(this)
      })
      this._refreshDeviceState && this._refreshDeviceState()
    }
    // 人机交互节点：截图按钮 + 画面区（显示上游设备视频并把鼠标键盘转发回设备）
    if (spec.type === 'io/interaction') {
      const w = this.addWidget('button', '', null, () => {
        captureHandler && captureHandler(this)
      })
      markI18nWidget(w, 'graph.widgets.capture', '📷 ')
      this._showVideo = true
    }
    // 模板图片节点：本地上传 / 剪贴板粘贴 两种方式选图（回显由 ShotOverlay 处理）
    if (spec.type === 'const/image') {
      let w = this.addWidget('button', '', null, () => {
        imageActionHandler && imageActionHandler(this, 'upload')
      })
      markI18nWidget(w, 'graph.widgets.uploadImage', '📁 ')
      w = this.addWidget('button', '', null, () => {
        imageActionHandler && imageActionHandler(this, 'paste')
      })
      markI18nWidget(w, 'graph.widgets.pasteImage', '📋 ')
      this._showShot = true
    }
    // 图片预览节点：显示上游 PICTURE（ShotOverlay 渲染）
    if (spec.type === 'vision/preview') this._showShot = true
    // 创建遮罩节点：编辑遮罩按钮 + 回显遮罩（ShotOverlay 渲染）
    if (spec.type === 'mask/create') {
      const w = this.addWidget('button', '', null, () => {
        maskActionHandler && maskActionHandler(this)
      })
      markI18nWidget(w, 'graph.widgets.editMask', '✏ ')
      this._showShot = true
    }
    // 动态端口节点：卡片上只放一个「编辑」按钮，点开用弹窗批量增删改端口/描述
    if (EDITABLE_TYPES.has(spec.type)) {
      const w = this.addWidget('button', '', null, () => openPortEditor(this))
      markI18nWidget(w, 'graph.widgets.edit', '✎ ')
    }
    // 取变量：value 连接点类型随 type 属性切换（自定义连接点类型）
    // 取变量：value 输出连接点类型随 type 属性切换
    if (spec.type === 'var/get') {
      const isSet = false
      this._applyVarType = () => {
        const t = this.properties.type
        if (!t) return
        const ports = isSet ? this.inputs : this.outputs
        const p = (ports || []).find((x) => x.name === 'value')
        if (!p || p.type === t) return
        p.type = t
        this._dropIncompatibleVarLinks()   // 类型变了，断开不兼容的旧连线
        this.setDirtyCanvas && this.setDirtyCanvas(true, true)
      }
      this._dropIncompatibleVarLinks = () => {
        const g = this.graph
        if (!g) return
        const t = this.properties.type
        if (isSet) {
          const slot = this.findInputSlot('value')
          const link = slot >= 0 ? this.inputs[slot].link : null
          if (link == null) return
          const li = g.links[link]
          const srcType = g.getNodeById(li.origin_id)?.outputs?.[li.origin_slot]?.type
          if (!compatible(srcType, t)) this.disconnectInput(slot)
        } else {
          const slot = this.findOutputSlot('value')
          const links = slot >= 0 ? (this.outputs[slot].links || []).slice() : []
          for (const link of links) {
            const li = g.links[link]
            const dst = g.getNodeById(li.target_id)
            const dstType = dst?.inputs?.[li.target_slot]?.type
            if (!compatible(t, dstType)) this.disconnectOutput(slot, dst)
          }
        }
      }
      this.onPropertyChanged = function (name) { if (name === 'type') this._applyVarType() }
      this._applyVarType()
    }
    // 脚本定义节点：仅嵌多行代码编辑器（入参经 get_arg 取，无设备/参数输入口）
    if (spec.type === 'script/python') this._showCode = true
    this.size = this.computeSize()
    if (this._showVideo || this._showShot) this.size[1] = Math.max(this.size[1], 220)
    if (this._showCode) { this.size[0] = Math.max(this.size[0], 300); this.size[1] = Math.max(this.size[1], 200) }
  }
  NodeClass.title = spec.title
  NodeClass.desc = spec.type
  NodeClass.prototype._isDeviceLocked = function () {
    return !!(this._conn || this._connecting)
  }
  NodeClass.prototype._refreshDeviceState = function () {
    const locked = this._isDeviceLocked()
    for (const w of this._devicePropertyWidgets || []) {
      if (w) w.disabled = locked
    }
    if (this._deviceActionWidget) {
      const label = this._connecting
        ? t('graph.widgets.connecting')
        : this._conn ? t('graph.widgets.disconnect') : t('graph.widgets.connect')
      this._deviceActionWidget.name = label
      this._deviceActionWidget.label = label
      this._deviceActionWidget.disabled = !!this._connecting
    }
    this.setDirtyCanvas && this.setDirtyCanvas(true, true)
  }
  NodeClass.prototype.setDeviceConnectionState = function (state = {}) {
    if ('conn' in state) this._conn = state.conn || null
    if ('connecting' in state) this._connecting = !!state.connecting
    this._refreshDeviceState()
  }
  NodeClass.prototype.refreshI18n = function () {
    for (const w of this.widgets || []) refreshI18nWidget(w)
    this._refreshDeviceState()
    this.setDirtyCanvas && this.setDirtyCanvas(true, true)
  }
  NodeClass.prototype.setProperty = function (name, value) {
    if (this._devicePropertyWidgets?.some((w) => w?.options?.property === name) && this._isDeviceLocked()) {
      return
    }
    if (!this.properties) this.properties = {}
    if (value === this.properties[name]) return
    const prevValue = this.properties[name]
    this.properties[name] = value
    let changed = true
    if (this.onPropertyChanged && this.onPropertyChanged(name, value, prevValue) === false) {
      this.properties[name] = prevValue
      changed = false
    }
    if (this.widgets) {
      for (const w of this.widgets) {
        if (!w) continue
        if (w.options?.property === name) {
          w.value = this.properties[name]
          break
        }
      }
    }
    if (changed) requestGraphHistory(this)
  }
  // 右键菜单顶部加「📖 组件说明」：弹窗展示描述 + 出入参 + 属性
  NodeClass.prototype.getExtraMenuOptions = function () {
    const opts = [
      { content: '📖 ' + t('graph.menu.help'), callback: () => showNodeHelp(this._spec, CATALOG && CATALOG.types) },
    ]
    opts.push(null)
    return opts
  }
  // 连线类型校验：拒绝不兼容
  NodeClass.prototype.onConnectInput = function (targetSlot, type, output) {
    const dst = this.inputs[targetSlot]
    if (!dst) return false
    return compatible(type, dst.type)
  }
  // 运行错误：_error 由运行状态设置，由 ErrorOverlay 以可选中/可复制的 DOM 显示
  LiteGraph.registerNodeType(spec.type, NodeClass)
}

// 密码属性：自定义 widget。真实值存 properties[name]（options.property 保证刷新回显）；
// 右侧眼睛图标可动态切换明文/圆点；点其余区域弹框编辑。
const EYE_W = 26   // 右侧眼睛热区宽度（节点单位）

function addPasswordWidget(node, prop) {
  const name = prop.name
  const w = {
    name, type: 'password', value: prop.default ?? '',
    options: { property: name }, reveal: false,
    draw(ctx, node, width, y, H) {
      if (node.flags && node.flags.collapsed) return
      const m = 15
      ctx.strokeStyle = LiteGraph.WIDGET_OUTLINE_COLOR
      ctx.fillStyle = LiteGraph.WIDGET_BGCOLOR
      ctx.beginPath(); ctx.roundRect(m, y, width - m * 2, H, [H * 0.5]); ctx.fill(); ctx.stroke()
      ctx.save(); ctx.beginPath(); ctx.rect(m, y, width - m * 2, H); ctx.clip()
      // 标签
      ctx.fillStyle = LiteGraph.WIDGET_SECONDARY_TEXT_COLOR
      ctx.textAlign = 'left'
      ctx.fillText(this.label || this.name, m * 2, y + H * 0.7)
      // 值：直接取 properties（保存/恢复的真源，确保刷新回显）；明文或圆点
      const raw = String((node.properties && node.properties[this.name]) ?? this.value ?? '')
      const shown = this.reveal ? raw : '•'.repeat(raw.length)
      ctx.fillStyle = LiteGraph.WIDGET_TEXT_COLOR
      ctx.textAlign = 'right'
      ctx.fillText(shown.substr(0, 30), width - EYE_W - m, y + H * 0.7)
      // 眼睛图标
      ctx.textAlign = 'center'
      ctx.fillText(this.reveal ? '🙈' : '👁', width - m - EYE_W / 2, y + H * 0.7)
      ctx.restore()
    },
    mouse(event, pos, node) {
      if (event.type !== LiteGraph.pointerevents_method + 'down') return false
      // 点右侧眼睛热区 → 切换显隐
      if (pos[0] >= node.size[0] - 15 - EYE_W) {
        this.reveal = !this.reveal
        node.setDirtyCanvas(true, true)
        return true
      }
      const canvas = LGraphCanvas.active_canvas || node.graph?.list_of_graphcanvas?.[0]
      if (!canvas) return false
      const cur = (node.properties && node.properties[this.name]) ?? this.value ?? ''
      const dialog = canvas.prompt(t('graph.dialog.password'), cur, (v) => {
        this.value = v
        node.properties[this.name] = v
        node.setDirtyCanvas(true, true)
        requestGraphHistory(node)
      }, event, false)
      // 编辑框按当前显隐决定是否用密码类型遮罩
      const input = dialog && dialog.querySelector && dialog.querySelector('input')
      if (input && !this.reveal) input.type = 'password'
      return true
    },
  }
  node.addCustomWidget(w)
  return w
}

// 多行文本属性：节点上显示单行预览（多行/超长加 ⏎…），点开弹出多行编辑框。
function openMultilineEditor(title, initial, onSave) {
  const mask = document.createElement('div')
  Object.assign(mask.style, {
    position: 'fixed', inset: '0', zIndex: 9999, background: 'rgba(0,0,0,0.5)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  })
  const onKey = (e) => { if (e.key === 'Escape') close() }
  const close = () => { try { mask.remove() } catch (_) {} document.removeEventListener('keydown', onKey) }
  document.addEventListener('keydown', onKey)
  mask.addEventListener('mousedown', (e) => { if (e.target === mask) close() })
  const panel = document.createElement('div')
  Object.assign(panel.style, {
    width: 'min(560px, 92vw)', background: '#23262b', color: '#e6e6e6', borderRadius: '8px',
    padding: '14px 16px', boxShadow: '0 8px 32px rgba(0,0,0,0.5)',
    display: 'flex', flexDirection: 'column', gap: '10px',
    fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
  })
  panel.addEventListener('mousedown', (e) => e.stopPropagation())
  const head = document.createElement('div')
  head.textContent = title; Object.assign(head.style, { fontWeight: '600', color: '#fff' })
  const ta = document.createElement('textarea')
  ta.value = initial
  Object.assign(ta.style, {
    width: '100%', minHeight: '160px', resize: 'vertical', boxSizing: 'border-box',
    background: '#0d0d0d', color: '#d4d4d4', border: '1px solid #333', borderRadius: '4px',
    padding: '8px', font: '13px monospace', outline: 'none', whiteSpace: 'pre-wrap',
  })
  const foot = document.createElement('div')
  Object.assign(foot.style, { display: 'flex', justifyContent: 'flex-end', gap: '8px', alignItems: 'center' })
  const hint = document.createElement('span')
  hint.textContent = t('graph.dialog.saveShortcut'); Object.assign(hint.style, { marginRight: 'auto', color: '#889', fontSize: '11px' })
  const cancel = document.createElement('button'); cancel.textContent = t('app.common.cancel')
  const save = document.createElement('button'); save.textContent = t('app.common.save')
  for (const b of [cancel, save]) Object.assign(b.style, { padding: '4px 12px', cursor: 'pointer', borderRadius: '4px', border: 'none' })
  Object.assign(save.style, { background: '#2b6cb0', color: '#fff' })
  Object.assign(cancel.style, { background: '#3a3a3a', color: '#ddd' })
  cancel.addEventListener('click', close)
  save.addEventListener('click', () => { onSave(ta.value); close() })
  ta.addEventListener('keydown', (e) => {
    if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') { e.preventDefault(); onSave(ta.value); close() }
  })
  foot.appendChild(hint); foot.appendChild(cancel); foot.appendChild(save)
  panel.appendChild(head); panel.appendChild(ta); panel.appendChild(foot)
  mask.appendChild(panel); document.body.appendChild(mask)
  ta.focus()
}

function addMultilineWidget(node, prop) {
  const name = prop.name
  const w = {
    name, type: 'multiline', value: prop.default ?? '',
    options: { property: name },   // 绑定 properties[name]，保证刷新/反序列化回显
    draw(ctx, node, width, y, H) {
      if (node.flags && node.flags.collapsed) return
      const m = 15
      ctx.strokeStyle = LiteGraph.WIDGET_OUTLINE_COLOR
      ctx.fillStyle = LiteGraph.WIDGET_BGCOLOR
      ctx.beginPath(); ctx.roundRect(m, y, width - m * 2, H, [H * 0.5]); ctx.fill(); ctx.stroke()
      ctx.save(); ctx.beginPath(); ctx.rect(m, y, width - m * 2, H); ctx.clip()
      ctx.fillStyle = LiteGraph.WIDGET_SECONDARY_TEXT_COLOR
      ctx.textAlign = 'left'
      ctx.fillText(this.label || this.name, m * 2, y + H * 0.7)
      const raw = String((node.properties && node.properties[this.name]) ?? this.value ?? '')
      const first = raw.split('\n')[0]
      const shown = raw.includes('\n') ? first + ' ⏎…' : first
      ctx.fillStyle = LiteGraph.WIDGET_TEXT_COLOR
      ctx.textAlign = 'right'
      ctx.fillText(shown.substr(0, 30), width - m * 2, y + H * 0.7)
      ctx.restore()
    },
    mouse(event, pos, node) {
      if (event.type !== LiteGraph.pointerevents_method + 'down') return false
      const cur = (node.properties && node.properties[this.name]) ?? this.value ?? ''
      openMultilineEditor(this.label || this.name, cur, (v) => {
        this.value = v
        node.properties[this.name] = v
        node.setDirtyCanvas(true, true)
        requestGraphHistory(node)
      })
      return true
    },
  }
  node.addCustomWidget(w)
  return w
}

const HOTKEY_MODIFIERS = [
  ['ctrl', 'Ctrl'], ['alt', 'Alt'], ['shift', 'Shift'], ['cmd', 'Cmd/Win'],
]
const HOTKEY_ROWS = [
  'A B C D E F G H I J K L M'.split(' '),
  'N O P Q R S T U V W X Y Z'.split(' '),
  '1 2 3 4 5 6 7 8 9 0'.split(' '),
  ['Space', '-', '=', '[', ']', ';', "'", '`', '\\', ',', '.', '/'],
  ['Enter', 'Tab', 'Esc', 'Backspace', 'Delete', 'Insert'],
  ['Home', 'End', 'PageUp', 'PageDown', 'Up', 'Down', 'Left', 'Right'],
  'F1 F2 F3 F4 F5 F6 F7 F8 F9 F10 F11 F12'.split(' '),
]

function normalizeHotkeyKey(label) {
  return label === 'Space' ? 'space' : String(label).toLowerCase()
}

function formatHotkey(value) {
  return String(value || '').split('+').filter(Boolean).map((part) => {
    const p = part.toLowerCase()
    if (p === 'ctrl') return 'Ctrl'
    if (p === 'alt') return 'Alt'
    if (p === 'shift') return 'Shift'
    if (p === 'cmd') return 'Cmd/Win'
    if (p === 'space') return 'Space'
    if (/^f\d+$/.test(p)) return p.toUpperCase()
    if (p.length === 1) return p.toUpperCase()
    return p[0]?.toUpperCase() + p.slice(1)
  }).join('+')
}

function parseHotkey(value) {
  const parts = String(value || '').replace(/\s+/g, '').toLowerCase().split('+').filter(Boolean)
  const mods = []
  const rest = []
  for (const p of parts) {
    const key = p === 'control' ? 'ctrl' : (p === 'meta' || p === 'win' || p === 'super') ? 'cmd' : p
    if (HOTKEY_MODIFIERS.some(([m]) => m === key)) mods.push(key)
    else rest.push(key)
  }
  return { mods: [...new Set(mods)], key: rest[rest.length - 1] || '' }
}

function openHotkeyPicker(title, initial, onSave) {
  const state = parseHotkey(initial)
  const mask = document.createElement('div')
  Object.assign(mask.style, {
    position: 'fixed', inset: '0', zIndex: 9999, background: 'rgba(0,0,0,0.5)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  })
  const onKey = (e) => { if (e.key === 'Escape') close() }
  const close = () => { try { mask.remove() } catch (_) {} document.removeEventListener('keydown', onKey) }
  const combo = (key = state.key) => [...state.mods, key].filter(Boolean).join('+')
  const save = (key = state.key) => { onSave(combo(key)); close() }
  document.addEventListener('keydown', onKey)
  mask.addEventListener('mousedown', (e) => { if (e.target === mask) close() })

  const panel = document.createElement('div')
  Object.assign(panel.style, {
    width: 'min(680px, 94vw)', background: '#23262b', color: '#e6e6e6', borderRadius: '8px',
    padding: '14px 16px', boxShadow: '0 8px 32px rgba(0,0,0,0.5)', boxSizing: 'border-box',
    fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
  })
  panel.addEventListener('mousedown', (e) => e.stopPropagation())
  const head = document.createElement('div')
  head.textContent = title || t('graph.hotkey.title')
  Object.assign(head.style, { fontWeight: '600', color: '#fff', marginBottom: '10px' })
  const preview = document.createElement('div')
  Object.assign(preview.style, {
    padding: '6px 8px', marginBottom: '10px', border: '1px solid rgba(255,255,255,0.14)',
    borderRadius: '4px', color: '#dcdcaa', fontFamily: 'monospace', minHeight: '20px',
  })
  const updatePreview = () => { preview.textContent = formatHotkey(combo()) || t('graph.hotkey.placeholder') }
  const keyButton = (label, onClick, active = false) => {
    const b = document.createElement('button')
    b.textContent = label
    Object.assign(b.style, {
      minWidth: '44px', padding: '6px 8px', border: '1px solid rgba(255,255,255,0.16)',
      borderRadius: '4px', background: active ? '#2b6cb0' : '#343840', color: '#f4f4f4',
      cursor: 'pointer', fontSize: '12px',
    })
    b.addEventListener('click', onClick)
    return b
  }
  const label = (text) => {
    const el = document.createElement('div')
    el.textContent = text
    Object.assign(el.style, { color: '#9fd0ff', fontSize: '12px', margin: '8px 0 4px' })
    return el
  }
  const modWrap = document.createElement('div')
  Object.assign(modWrap.style, { display: 'flex', flexWrap: 'wrap', gap: '6px' })
  const renderMods = () => {
    modWrap.replaceChildren()
    for (const [key, name] of HOTKEY_MODIFIERS) {
      const active = state.mods.includes(key)
      modWrap.appendChild(keyButton(name, () => {
        state.mods = active ? state.mods.filter((m) => m !== key) : [...state.mods, key]
        renderMods(); updatePreview()
      }, active))
    }
  }
  const keyWrap = document.createElement('div')
  Object.assign(keyWrap.style, { display: 'flex', flexDirection: 'column', gap: '6px' })
  for (const row of HOTKEY_ROWS) {
    const r = document.createElement('div')
    Object.assign(r.style, { display: 'flex', flexWrap: 'wrap', gap: '6px' })
    for (const k of row) r.appendChild(keyButton(k, () => save(normalizeHotkeyKey(k))))
    keyWrap.appendChild(r)
  }
  const foot = document.createElement('div')
  Object.assign(foot.style, { display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '12px' })
  const clear = keyButton(t('graph.hotkey.clear'), () => { onSave(''); close() })
  const cancel = keyButton(t('graph.hotkey.close'), close)
  const apply = keyButton(t('graph.hotkey.apply'), () => save())
  Object.assign(apply.style, { background: '#2b6cb0' })
  foot.appendChild(clear); foot.appendChild(cancel); foot.appendChild(apply)
  panel.appendChild(head); panel.appendChild(preview); panel.appendChild(label(t('graph.hotkey.modifiers')))
  panel.appendChild(modWrap); panel.appendChild(label(t('graph.hotkey.keys'))); panel.appendChild(keyWrap); panel.appendChild(foot)
  mask.appendChild(panel); document.body.appendChild(mask)
  renderMods(); updatePreview()
}

function addHotkeyWidget(node, prop) {
  const name = prop.name
  const w = {
    name, type: 'hotkey', value: prop.default ?? '', options: { property: name },
    draw(ctx, node, width, y, H) {
      if (node.flags && node.flags.collapsed) return
      const m = 15
      ctx.strokeStyle = LiteGraph.WIDGET_OUTLINE_COLOR
      ctx.fillStyle = LiteGraph.WIDGET_BGCOLOR
      ctx.beginPath(); ctx.roundRect(m, y, width - m * 2, H, [H * 0.5]); ctx.fill(); ctx.stroke()
      ctx.save(); ctx.beginPath(); ctx.rect(m, y, width - m * 2, H); ctx.clip()
      ctx.fillStyle = LiteGraph.WIDGET_SECONDARY_TEXT_COLOR
      ctx.textAlign = 'left'
      ctx.fillText(this.label || this.name, m * 2, y + H * 0.7)
      const raw = String((node.properties && node.properties[this.name]) ?? this.value ?? '')
      ctx.fillStyle = LiteGraph.WIDGET_TEXT_COLOR
      ctx.textAlign = 'right'
      ctx.fillText((formatHotkey(raw) || t('graph.hotkey.placeholder')).substr(0, 34), width - m * 2, y + H * 0.7)
      ctx.restore()
    },
    mouse(event, pos, node) {
      if (event.type !== LiteGraph.pointerevents_method + 'down') return false
      const cur = (node.properties && node.properties[this.name]) ?? this.value ?? ''
      openHotkeyPicker(t('graph.hotkey.title'), cur, (v) => {
        this.value = v
        node.properties[this.name] = v
        node.setDirtyCanvas(true, true)
        requestGraphHistory(node)
      })
      return true
    },
  }
  node.addCustomWidget(w)
  return w
}

function addWidgetFor(node, prop) {
  const set = (v) => {
    if (node.properties[prop.name] === v) return
    node.properties[prop.name] = v
    requestGraphHistory(node)
  }
  const name = prop.name
  // 绑定到 properties[name]：反序列化后 LiteGraph 会据此把保存值回填到 widget（回显）
  const opt = (extra) => ({ property: name, ...(extra || {}) })
  switch (prop.type) {
    case 'number':
      node.addWidget('number', name, prop.default ?? 0, set, opt()); break
    case 'int':
      // LiteGraph 箭头/拖动步进 = delta * 0.1 * step，故 step:10 → 每次 ±1
      node.addWidget('number', name, prop.default ?? 0,
        (v) => {
          const next = Math.round(v)
          if (node.properties[name] === next) return
          node.properties[name] = next
          requestGraphHistory(node)
        },
        opt({ precision: 0, step: 10 })); break
    case 'bool':
      node.addWidget('toggle', name, !!prop.default, set, opt()); break
    case 'enum':
      node.addWidget('combo', name, prop.default, set, opt({ values: prop.options || [] })); break
    case 'password':
      addPasswordWidget(node, prop); break
    case 'multiline':
      addMultilineWidget(node, prop); break
    case 'hotkey':
      addHotkeyWidget(node, prop); break
    case 'image':
      break   // 模板图片：无文本框，由上传/粘贴按钮写入
    case 'string':
      node.addWidget('text', name, prop.default ?? '', set, opt()); break
    case 'code':
      break   // 代码：无单行文本框，由脚本节点的多行编辑器(CodeOverlay)处理
    case 'rect':
      break   // 裁剪框：无输入框，由截图节点的框选交互写入
    default:
      node.addWidget('text', name, prop.default == null ? '' : String(prop.default), set, opt())
  }
}

export function nodeSpec(type) {
  return CATALOG?.nodes.find(n => n.type === type)
}
