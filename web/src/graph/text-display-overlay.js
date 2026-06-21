import { LiteGraph } from 'litegraph.js'

const RESIZE_PAD = 12

async function copyText(text) {
  try { await navigator.clipboard.writeText(text); return true } catch (_) {}
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.style.position = 'fixed'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    ta.remove()
    return ok
  } catch (_) {
    return false
  }
}

export class TextDisplayOverlay {
  constructor(lgcanvas, container) {
    this.canvas = lgcanvas
    this.container = container
    this.entries = new Map()
  }

  ensure(node) {
    let e = this.entries.get(node)
    if (e) return e
    const box = document.createElement('div')
    Object.assign(box.style, {
      position: 'absolute', zIndex: 43, overflow: 'hidden', boxSizing: 'border-box',
      background: '#111318', border: '1px solid #333', color: '#d4d4d4',
      display: 'flex', flexDirection: 'column', pointerEvents: 'auto',
    })
    const text = document.createElement('pre')
    Object.assign(text.style, {
      flex: '1 1 auto', margin: '0', padding: '8px', overflow: 'auto',
      whiteSpace: 'pre', wordBreak: 'normal', userSelect: 'text',
      fontFamily: 'monospace', lineHeight: '1.45',
    })
    const copy = document.createElement('button')
    copy.textContent = '⧉'
    copy.title = '复制文本'
    Object.assign(copy.style, {
      position: 'absolute', top: '4px', right: '4px', border: 'none', borderRadius: '3px',
      background: 'rgba(0,0,0,0.45)', color: '#fff', cursor: 'pointer', lineHeight: '1',
      padding: '2px 5px',
    })
    for (const ev of ['mousedown', 'wheel', 'keydown', 'contextmenu']) box.addEventListener(ev, (event) => event.stopPropagation())
    copy.addEventListener('click', async (event) => {
      event.stopPropagation()
      if (await copyText(node._displayText || node.properties?.placeholder || '')) {
        copy.textContent = '✓'
        setTimeout(() => { copy.textContent = '⧉' }, 1000)
      }
    })
    box.appendChild(text)
    box.appendChild(copy)
    this.container.appendChild(box)
    e = { box, text, copy }
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
      if (!nodes.includes(node) || node._spec?.type !== 'data/text_display') this.remove(node)
    }
    for (const node of nodes) {
      if (node._spec?.type === 'data/text_display' && !(node.flags && node.flags.collapsed)) {
        this._place(node, this.ensure(node))
      }
    }
  }

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
      left: `${x}px`,
      top: `${y}px`,
      width: `${Math.max(0, node.size[0] * scale)}px`,
      height: `${Math.max(0, (node.size[1] - head - RESIZE_PAD) * scale)}px`,
    })
    e.text.style.fontSize = `${12 * scale}px`
    e.text.style.padding = `${8 * scale}px`
    e.copy.style.transform = `scale(${Math.max(0.6, scale)})`
    e.copy.style.transformOrigin = 'top right'
    const value = node._displayText ?? node.properties?.placeholder ?? ''
    if (e.shown !== value) {
      e.shown = value
      e.text.textContent = value || ' '
    }
  }
}
