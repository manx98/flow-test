// 运行错误：在节点下方用 DOM 显示 _error，文字可选中，并带「复制」按钮。
import { LiteGraph } from 'litegraph.js'

async function copyText(t) {
  try { await navigator.clipboard.writeText(t); return true } catch (_) {}
  try {
    const ta = document.createElement('textarea')
    ta.value = t; ta.style.position = 'fixed'; ta.style.opacity = '0'
    document.body.appendChild(ta); ta.select()
    const ok = document.execCommand('copy'); ta.remove(); return ok
  } catch (_) { return false }
}

export class ErrorOverlay {
  constructor(lgcanvas, container) {
    this.canvas = lgcanvas
    this.container = container
    this.entries = new Map()   // node -> { box, txt, btn }
  }

  ensure(node) {
    let e = this.entries.get(node)
    if (e) return e
    const box = document.createElement('div')
    Object.assign(box.style, {
      position: 'absolute', zIndex: 60, pointerEvents: 'auto', boxSizing: 'border-box',
      background: 'rgba(120,20,20,0.96)', color: '#ffd7d7', borderRadius: '0 0 4px 4px',
      fontFamily: 'monospace', display: 'flex', alignItems: 'flex-start',
    })
    const txt = document.createElement('div')
    Object.assign(txt.style, {
      flex: '1', whiteSpace: 'pre-wrap', wordBreak: 'break-all',
      userSelect: 'text', cursor: 'text',
    })
    const btn = document.createElement('button')
    btn.textContent = '⧉'; btn.title = '复制错误信息'
    Object.assign(btn.style, {
      flex: '0 0 auto', cursor: 'pointer', border: 'none', borderRadius: '3px',
      background: 'rgba(0,0,0,0.3)', color: '#fff', lineHeight: '1',
    })
    // 不让选字/点按钮触发画布拖动
    box.addEventListener('mousedown', (ev) => ev.stopPropagation())
    box.addEventListener('wheel', (ev) => ev.stopPropagation())
    btn.addEventListener('click', async (ev) => {
      ev.stopPropagation()
      if (await copyText(node._error || '')) {
        btn.textContent = '✓'; setTimeout(() => { btn.textContent = '⧉' }, 1000)
      }
    })
    box.appendChild(txt); box.appendChild(btn)
    this.container.appendChild(box)
    e = { box, txt, btn }
    this.entries.set(node, e)
    return e
  }

  remove(node) {
    const e = this.entries.get(node)
    if (!e) return
    this.entries.delete(node)
    try { e.box.remove() } catch (_) {}
  }

  update(nodes) {
    for (const node of [...this.entries.keys()]) {
      if (!nodes.includes(node) || !node._error) this.remove(node)
    }
    for (const node of nodes) {
      if (node._error && !(node.flags && node.flags.collapsed)) this._place(node, this.ensure(node))
    }
  }

  _place(node, e) {
    const ds = this.canvas.ds
    const rect = this.canvas.canvas.getBoundingClientRect()
    const crect = this.container.getBoundingClientRect()
    const scale = ds.scale
    const x = rect.left - crect.left + (node.pos[0] + ds.offset[0]) * scale
    const y = rect.top - crect.top + (node.pos[1] + node.size[1] + 4 + ds.offset[1]) * scale
    if (e.shown !== node._error) {   // 仅在内容变化时写，避免每帧清掉用户选区
      e.shown = node._error
      e.txt.textContent = '⚠ ' + node._error
    }
    Object.assign(e.box.style, {
      left: x + 'px', top: y + 'px',
      width: Math.max(0, node.size[0] * scale) + 'px',
      fontSize: (11 * scale) + 'px',
      padding: (4 * scale) + 'px',
      gap: (4 * scale) + 'px',
    })
    e.btn.style.fontSize = (12 * scale) + 'px'
    e.btn.style.padding = (1 * scale) + 'px ' + (4 * scale) + 'px'
  }
}