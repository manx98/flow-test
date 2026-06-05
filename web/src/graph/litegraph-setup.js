// 把 /api/nodes 目录注册成 LiteGraph 节点类型，带类型上色与连线校验。
import { LiteGraph, LGraphCanvas } from 'litegraph.js'

const EXEC = 'exec', BUNDLE = 'bundle', ANY = 'any'

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

export function setDeviceActionHandler(fn) { deviceActionHandler = fn }
export function setCaptureHandler(fn) { captureHandler = fn }
export function setImageActionHandler(fn) { imageActionHandler = fn }

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

function registerOne(spec) {
  function NodeClass() {
    for (const p of spec.inputs || []) this.addInput(p.name, p.type)
    for (const p of spec.outputs || []) this.addOutput(p.name, p.type)
    // 属性 → widget
    this.properties = this.properties || {}
    for (const prop of spec.properties || []) {
      this.properties[prop.name] = prop.default
      addWidgetFor(this, prop)
    }
    this._spec = spec
    // Bundle 打包/拆包：动态增减命名字段端口
    if (spec.type === 'bundle/pack') addFieldButtons(this, 'input')
    if (spec.type === 'bundle/unpack') addFieldButtons(this, 'output')
    // 设备节点：仅连接/断开按钮（不内嵌画面、不接管控制——交给「人机交互」节点）
    if (spec.category === '设备') {
      this.addWidget('button', '▶ 连接 / 断开', null, () => {
        deviceActionHandler && deviceActionHandler(this)
      })
    }
    // 人机交互节点：预留画面区，显示上游设备视频并把鼠标键盘转发回设备
    if (spec.type === 'io/interaction') {
      this._showVideo = true
    }
    // 视频截图节点：截图按钮 + 清除裁剪按钮（帧回显与框选裁剪由 ShotOverlay 处理）
    if (spec.type === 'vision/screenshot') {
      this.addWidget('button', '📷 截图', null, () => {
        captureHandler && captureHandler(this)
      })
      this.addWidget('button', '清除裁剪', null, () => {
        this.properties.crop = null; this.setDirtyCanvas(true, true)
      })
      this._showShot = true
    }
    // 模板图片节点：本地上传 / 剪贴板粘贴 两种方式选图（回显由 ShotOverlay 处理）
    if (spec.type === 'const/image') {
      this.addWidget('button', '📁 上传图片', null, () => {
        imageActionHandler && imageActionHandler(this, 'upload')
      })
      this.addWidget('button', '📋 粘贴图片', null, () => {
        imageActionHandler && imageActionHandler(this, 'paste')
      })
      this._showShot = true
    }
    // 脚本节点：嵌多行代码编辑器（CodeOverlay 渲染），预留较大尺寸
    if (spec.type === 'script/python') this._showCode = true
    this.size = this.computeSize()
    if (this._showVideo || this._showShot) this.size[1] = Math.max(this.size[1], 220)
    if (this._showCode) { this.size[0] = Math.max(this.size[0], 300); this.size[1] = Math.max(this.size[1], 200) }
  }
  NodeClass.title = spec.title
  NodeClass.desc = spec.type
  // 连线类型校验：拒绝不兼容
  NodeClass.prototype.onConnectInput = function (targetSlot, type, output) {
    const dst = this.inputs[targetSlot]
    if (!dst) return false
    return compatible(type, dst.type)
  }
  // 运行出错时在节点下方显示红色错误条（_error 由运行状态设置）
  NodeClass.prototype.onDrawForeground = function (ctx) {
    if (!this._error || (this.flags && this.flags.collapsed)) return
    ctx.font = '11px monospace'
    const pad = 6, w = this.size[0]
    const lines = wrapText(ctx, '⚠ ' + this._error, w - pad * 2)
    const h = lines.length * 14 + pad * 2
    const y = this.size[1] + 4
    ctx.fillStyle = 'rgba(120,20,20,0.96)'
    ctx.fillRect(0, y, w, h)
    ctx.fillStyle = '#ffd7d7'
    lines.forEach((ln, i) => ctx.fillText(ln, pad, y + pad + 10 + i * 14))
  }
  LiteGraph.registerNodeType(spec.type, NodeClass)
}

// 给 pack/unpack 节点加「+字段 / -字段」按钮，动态增减命名端口（端口名即 Bundle 字段名）
function addFieldButtons(node, side) {
  node.addWidget('button', '+ 字段', null, () => {
    const name = prompt('字段名（Bundle 键）')
    if (!name) return
    if (side === 'input') node.addInput(name, ANY)
    else node.addOutput(name, ANY)
    node.setDirtyCanvas(true, true)
  })
  node.addWidget('button', '- 字段', null, () => {
    if (side === 'input' && node.inputs.length > 0) node.removeInput(node.inputs.length - 1)
    else if (side === 'output' && node.outputs.length > 0) node.removeOutput(node.outputs.length - 1)
    node.setDirtyCanvas(true, true)
  })
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
      const dialog = canvas.prompt('密码', cur, (v) => {
        this.value = v
        node.properties[this.name] = v
        node.setDirtyCanvas(true, true)
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

function addWidgetFor(node, prop) {
  const set = (v) => { node.properties[prop.name] = v }
  const name = prop.name
  // 绑定到 properties[name]：反序列化后 LiteGraph 会据此把保存值回填到 widget（回显）
  const opt = (extra) => ({ property: name, ...(extra || {}) })
  switch (prop.type) {
    case 'number':
      node.addWidget('number', name, prop.default ?? 0, set, opt()); break
    case 'int':
      // LiteGraph 箭头/拖动步进 = delta * 0.1 * step，故 step:10 → 每次 ±1
      node.addWidget('number', name, prop.default ?? 0,
        (v) => { node.properties[name] = Math.round(v) },
        opt({ precision: 0, step: 10 })); break
    case 'bool':
      node.addWidget('toggle', name, !!prop.default, set, opt()); break
    case 'enum':
      node.addWidget('combo', name, prop.default, set, opt({ values: prop.options || [] })); break
    case 'password':
      addPasswordWidget(node, prop); break
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

// 按节点宽度逐字符折行（兼容无空格长串），最多 6 行
function wrapText(ctx, text, maxW) {
  const lines = []
  let cur = ''
  for (const ch of text) {
    if (ch === '\n') { lines.push(cur); cur = ''; continue }
    if (cur && ctx.measureText(cur + ch).width > maxW) { lines.push(cur); cur = ch }
    else cur += ch
  }
  if (cur) lines.push(cur)
  return lines.slice(0, 6)
}

export function nodeSpec(type) {
  return CATALOG?.nodes.find(n => n.type === type)
}
