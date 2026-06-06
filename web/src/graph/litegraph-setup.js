// 把 /api/nodes 目录注册成 LiteGraph 节点类型，带类型上色与连线校验。
import { LiteGraph, LGraphCanvas } from 'litegraph.js'
import { showNodeHelp } from './help-dialog.js'

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
let maskActionHandler = null

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
    // 设备节点：仅连接/断开按钮（不内嵌画面、不接管控制——交给「人机交互」节点）
    if (spec.category === '设备') {
      this.addWidget('button', '▶ 连接 / 断开', null, () => {
        deviceActionHandler && deviceActionHandler(this)
      })
    }
    // 人机交互节点：截图按钮 + 画面区（显示上游设备视频并把鼠标键盘转发回设备）
    if (spec.type === 'io/interaction') {
      this.addWidget('button', '📷 截图', null, () => {
        captureHandler && captureHandler(this)
      })
      this._showVideo = true
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
    // 图片预览节点：显示上游 PICTURE（ShotOverlay 渲染）
    if (spec.type === 'vision/preview') this._showShot = true
    // 创建遮罩节点：编辑遮罩按钮 + 回显遮罩（ShotOverlay 渲染）
    if (spec.type === 'mask/create') {
      this.addWidget('button', '✏ 编辑遮罩', null, () => {
        maskActionHandler && maskActionHandler(this)
      })
      this._showShot = true
    }
    // 设变量：动态端口（每个端口=一个变量），一次可设多个；类型取自 type 下拉
    if (spec.type === 'var/set') {
      this.addWidget('button', '+ 变量', null, () => {
        const name = (prompt('变量名') || '').trim()
        if (!name) return
        if ((this.inputs || []).some((i) => i.name === name)) { alert('变量名重复'); return }
        this.addInput(name, this.properties.type)
        this.setDirtyCanvas(true, true)
      })
      this.addWidget('button', '- 变量', null, (w, canvas, node, pos, event) => {
        const names = (this.inputs || []).filter((i) => i.type !== 'exec').map((i) => i.name)
        if (!names.length) return
        new LiteGraph.ContextMenu(names, {
          event, title: '删除变量',
          callback: (name) => {
            const slot = this.findInputSlot(name)
            if (slot >= 0) { this.removeInput(slot); this.setDirtyCanvas(true, true) }
          },
        })
      })
    }
    // 顺序：动态增减 exec 出口（出口按槽位顺序依次执行）
    if (spec.type === 'flow/sequence') {
      const execOuts = () => (this.outputs || []).filter((o) => o.type === EXEC)
      this.addWidget('button', '+ 出口', null, () => {
        const nums = execOuts().map((o) => parseInt(o.name, 10)).filter((n) => !isNaN(n))
        this.addOutput(String((nums.length ? Math.max(...nums) : 0) + 1), EXEC)
        this.setDirtyCanvas(true, true)
      })
      this.addWidget('button', '- 出口', null, (w, canvas, node, pos, event) => {
        const names = execOuts().map((o) => o.name)
        if (names.length <= 1) return   // 至少保留一个出口
        new LiteGraph.ContextMenu(names, {
          event, title: '删除出口',
          callback: (name) => {
            const slot = this.findOutputSlot(name)
            if (slot >= 0) { this.removeOutput(slot); this.setDirtyCanvas(true, true) }
          },
        })
      })
    }
    // 取变量：value 连接点类型随 type 属性切换（自定义连接点类型）
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
    // 脚本节点：嵌多行代码编辑器（CodeOverlay 渲染），预留较大尺寸
    if (spec.type === 'script/python') this._showCode = true
    this.size = this.computeSize()
    if (this._showVideo || this._showShot) this.size[1] = Math.max(this.size[1], 220)
    if (this._showCode) { this.size[0] = Math.max(this.size[0], 300); this.size[1] = Math.max(this.size[1], 200) }
  }
  NodeClass.title = spec.title
  NodeClass.desc = spec.type
  // 右键菜单顶部加「📖 组件说明」：弹窗展示描述 + 出入参 + 属性
  NodeClass.prototype.getExtraMenuOptions = function () {
    return [
      { content: '📖 组件说明', callback: () => showNodeHelp(this._spec, CATALOG && CATALOG.types) },
      null,
    ]
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

export function nodeSpec(type) {
  return CATALOG?.nodes.find(n => n.type === type)
}
