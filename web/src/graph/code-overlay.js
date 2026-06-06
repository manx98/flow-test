// 脚本节点：节点画面区嵌「透明 textarea + 底层高亮 <pre>」做多行编辑 + 语法高亮 + 补全。
import { LiteGraph } from 'litegraph.js'
import { api } from '../api.js'
import { attachCompletion } from './code-complete.js'
import { highlightPython } from './code-highlight.js'

const LH = 1.4          // 行高（pre 与 textarea 必须一致才能对齐）
const RESIZE_PAD = 12   // 底部留白(节点单位)，露出 LiteGraph 右下角原生缩放手柄

// 等宽字体单字符宽度 = 比例 × 字号(px)；测一次缓存（用于按列精确定位错误标注）
let _charRatio = 0
function charWidthRatio() {
  if (_charRatio) return _charRatio
  const s = document.createElement('span')
  Object.assign(s.style, {
    position: 'fixed', visibility: 'hidden', whiteSpace: 'pre',
    fontFamily: 'monospace', fontSize: '100px',
  })
  s.textContent = '0'.repeat(50)
  document.body.appendChild(s)
  _charRatio = s.offsetWidth / 50 / 100
  s.remove()
  return _charRatio
}

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

    // 语法错误条：编辑器内按行号定位的高亮带（波浪底线），随 textarea 滚动/缩放在 _place 中定位
    const strip = document.createElement('div')
    Object.assign(strip.style, {
      position: 'absolute', display: 'none', pointerEvents: 'none', boxSizing: 'border-box',
      background: 'rgba(255,70,70,0.22)', borderBottom: '2px solid rgba(255,70,70,0.95)',
    })
    box.appendChild(strip)
    // 错误消息 tooltip：悬停错误行时显示（textarea 在最上层，靠 mousemove 算行号触发）
    const tip = document.createElement('div')
    Object.assign(tip.style, {
      position: 'fixed', zIndex: 1001, display: 'none', maxWidth: '360px', pointerEvents: 'none',
      background: '#3a1d1d', color: '#ffd7d7', border: '1px solid #a55', borderRadius: '4px',
      padding: '3px 7px', font: '12px monospace', boxShadow: '0 4px 12px rgba(0,0,0,.5)',
      whiteSpace: 'pre-wrap', wordBreak: 'break-all',
    })
    document.body.appendChild(tip)
    const hideTip = () => { tip.style.display = 'none' }

    // 语法检查：停止输入 ~500ms 后查一次；失焦再查一次（最终态）。过期响应用 seq 丢弃。
    let checkTimer = null, checkSeq = 0
    const runCheck = async () => {
      const seq = ++checkSeq
      try {
        const errs = await api.check(ta.value)
        if (seq !== checkSeq) return                  // 已有更新的检查，丢弃过期结果
        node._syntaxError = (errs && errs[0]) || null
      } catch (_) { return }                          // 网络失败：保留上次状态
      hideTip()   // 错误已变化/已修复：先收起旧悬浮框，避免显示过期消息（下次悬停会按新状态重算）
      node.setDirtyCanvas && node.setDirtyCanvas(true, true)   // 触发重绘以更新错误条位置
    }
    const scheduleCheck = () => { clearTimeout(checkTimer); hideTip(); checkTimer = setTimeout(runCheck, 500) }
    ta.addEventListener('input', scheduleCheck)
    ta.addEventListener('blur', () => { clearTimeout(checkTimer); runCheck() })
    runCheck()                                        // 挂载即查一次（打开工程时坏脚本立刻显形）

    // 悬停错误行 → 显示消息 tooltip
    const onMove = (ev) => {
      const err = node._syntaxError
      if (!err) { tip.style.display = 'none'; return }
      const cs = getComputedStyle(ta)
      const fs = parseFloat(cs.fontSize) || 12
      const lh = fs * LH, padTop = parseFloat(cs.paddingTop) || 0
      const line = Math.floor((ev.offsetY + ta.scrollTop - padTop) / lh) + 1
      if (line === err.line) {
        tip.textContent = '语法错误：' + err.message
        tip.style.left = (ev.clientX + 12) + 'px'
        tip.style.top = (ev.clientY + 16) + 'px'
        tip.style.display = 'block'
      } else {
        tip.style.display = 'none'
      }
    }
    ta.addEventListener('mousemove', onMove)
    ta.addEventListener('mouseleave', hideTip)
    ta.addEventListener('scroll', hideTip)
    const destroyCheck = () => { clearTimeout(checkTimer); try { tip.remove() } catch (_) {} }

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
    e = { box, pre, ta, strip, destroyCompletion, destroyCheck }
    this.entries.set(node, e)
    sync()
    return e
  }

  remove(node) {
    const e = this.entries.get(node)
    if (!e) return
    this.entries.delete(node)
    try { e.destroyCompletion && e.destroyCompletion() } catch (_) {}
    try { e.destroyCheck && e.destroyCheck() } catch (_) {}
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
    // 语法错误标注：仅高亮出错的「列范围」(err.col..end_col)，跟随字号缩放与 textarea 滚动；
    // box 已 overflow:hidden 自动裁切。跨行错误则标到该行末尾(整条编辑器宽)。
    const err = node._syntaxError
    if (err) {
      const lhPx = 12 * scale * LH, pad = 4 * scale
      const cw = charWidthRatio() * 12 * scale
      const sameLine = (err.end_line || err.line) === err.line
      const left = pad + (err.col - 1) * cw - e.ta.scrollLeft
      const width = sameLine
        ? Math.max(cw, (err.end_col - err.col) * cw)
        : Math.max(cw, e.box.clientWidth - left)
      e.strip.style.left = left + 'px'
      e.strip.style.width = width + 'px'
      e.strip.style.top = (pad + (err.line - 1) * lhPx - e.ta.scrollTop) + 'px'
      e.strip.style.height = lhPx + 'px'
      e.strip.style.display = 'block'
    } else {
      e.strip.style.display = 'none'
    }
  }
}
