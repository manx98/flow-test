// 脚本节点：节点画面区嵌「透明 textarea + 底层高亮 <pre>」做多行编辑 + 语法高亮 + 补全。
import { LiteGraph } from 'litegraph.js'
import { attachCompletion } from './code-complete.js'
import { highlightPython } from './code-highlight.js'

const LH = 1.4          // 行高（pre 与 textarea 必须一致才能对齐）
const RESIZE_PAD = 12   // 底部留白(节点单位)，露出 LiteGraph 右下角原生缩放手柄

export class CodeOverlay {
  constructor(lgcanvas, container) {
    this.canvas = lgcanvas
    this.container = container
    this.entries = new Map()   // 脚本节点 -> { box, pre, ta, destroyCompletion }
  }

  ensure(node) {
    let e = this.entries.get(node)
    if (e) return e
    const box = document.createElement('div')
    Object.assign(box.style, {
      position: 'absolute', zIndex: 45, overflow: 'hidden', background: '#0d0d0d',
      border: '1px solid #333', boxSizing: 'border-box',
    })
    const common = {
      position: 'absolute', inset: '0', margin: '0', boxSizing: 'border-box',
      fontFamily: 'monospace', lineHeight: String(LH), whiteSpace: 'pre',
      tabSize: '2', border: 'none',
    }
    const pre = document.createElement('pre')   // 底层高亮
    Object.assign(pre.style, { ...common, overflow: 'hidden', pointerEvents: 'none', color: '#d4d4d4' })
    const ta = document.createElement('textarea')   // 上层编辑（文字透明，仅显示光标/选区）
    ta.spellcheck = false
    ta.value = node.properties?.code ?? ''
    Object.assign(ta.style, {
      ...common, resize: 'none', outline: 'none', overflow: 'auto',
      background: 'transparent', color: 'transparent', caretColor: '#d4d4d4',
      pointerEvents: 'auto',   // .overlay 为 none 且该属性可继承，必须显式开启才能输入
    })

    const sync = () => {
      pre.innerHTML = highlightPython(ta.value)
      pre.scrollTop = ta.scrollTop; pre.scrollLeft = ta.scrollLeft
    }
    const commit = () => { node.properties.code = ta.value; sync() }
    ta.addEventListener('input', commit)
    ta.addEventListener('scroll', () => { pre.scrollTop = ta.scrollTop; pre.scrollLeft = ta.scrollLeft })
    const destroyCompletion = attachCompletion(ta, commit)
    // 不让事件冒泡到画布（避免拖动/删除/缩放/框选）
    for (const ev of ['wheel', 'keydown', 'contextmenu'])
      ta.addEventListener(ev, (x) => x.stopPropagation())
    // mousedown 同样不冒泡到画布；但 stopPropagation 会挡住 LiteGraph 的「点外部关菜单」，
    // 故手动关掉已打开的右键菜单（否则点编辑器时菜单不消失）
    ta.addEventListener('mousedown', (x) => {
      x.stopPropagation()
      LiteGraph.closeAllContextMenus(window)
    })
    // Tab 插入两个空格
    ta.addEventListener('keydown', (x) => {
      if (x.key === 'Tab') {
        x.preventDefault()
        const s = ta.selectionStart, end = ta.selectionEnd
        ta.value = ta.value.slice(0, s) + '  ' + ta.value.slice(end)
        ta.selectionStart = ta.selectionEnd = s + 2
        commit()
      }
    })

    box.appendChild(pre)
    box.appendChild(ta)
    this.container.appendChild(box)
    e = { box, pre, ta, destroyCompletion }
    this.entries.set(node, e)
    sync()
    return e
  }

  remove(node) {
    const e = this.entries.get(node)
    if (!e) return
    this.entries.delete(node)
    try { e.destroyCompletion && e.destroyCompletion() } catch (_) {}
    try { e.box.remove() } catch (_) {}
  }

  update(nodes) {
    for (const node of [...this.entries.keys()]) {
      if (!nodes.includes(node)) this.remove(node)
    }
    for (const node of nodes) {
      if (node._spec?.type === 'script/python') this._place(node, this.ensure(node))
    }
  }

  // 画面区顶端（节点单位）：让过端口行与按钮 widgets
  _bodyTop(node) {
    const slotH = LiteGraph.NODE_SLOT_HEIGHT || 20
    const wh = LiteGraph.NODE_WIDGET_HEIGHT || 20
    const rows = Math.max(node.inputs?.length || 0, node.outputs?.length || 0)
    const widgets = node.widgets ? node.widgets.length : 0
    return rows * slotH + widgets * (wh + 4) + 8
  }

  _place(node, e) {
    const ds = this.canvas.ds
    const rect = this.canvas.canvas.getBoundingClientRect()
    const crect = this.container.getBoundingClientRect()
    const scale = ds.scale
    const head = this._bodyTop(node)
    const x = rect.left - crect.left + (node.pos[0] + ds.offset[0]) * scale
    const y = rect.top - crect.top + (node.pos[1] + ds.offset[1] + head) * scale
    Object.assign(e.box.style, {
      left: x + 'px', top: y + 'px',
      width: Math.max(0, node.size[0] * scale) + 'px',
      height: Math.max(0, (node.size[1] - head - RESIZE_PAD) * scale) + 'px',
    })
    const fs = (12 * scale) + 'px', pad = (4 * scale) + 'px'
    e.pre.style.fontSize = fs; e.pre.style.padding = pad
    e.ta.style.fontSize = fs; e.ta.style.padding = pad
    // 外部改了 properties.code（如打开工程恢复）时回填，但不打断正在编辑
    const code = node.properties?.code ?? ''
    if (document.activeElement !== e.ta && e.ta.value !== code) {
      e.ta.value = code
      e.pre.innerHTML = highlightPython(code)
    }
  }
}
