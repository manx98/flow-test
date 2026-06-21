import { LiteGraph } from 'litegraph.js'
import { t } from '../i18n.js'

const LH = 1.45
const RESIZE_PAD = 12
const GUTTER_WIDTH = 44

const esc = (s) => String(s).replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))

function errorPosition(err, text) {
  const msg = String(err?.message || '')
  const posMatch = msg.match(/position\s+(\d+)/i)
  if (posMatch) return Math.max(0, Math.min(Number(posMatch[1]), String(text ?? '').length))
  const lcMatch = msg.match(/line\s+(\d+)\s+column\s+(\d+)/i)
  if (lcMatch) {
    const line = Math.max(1, Number(lcMatch[1]))
    const col = Math.max(1, Number(lcMatch[2]))
    let idx = 0
    const lines = String(text ?? '').split('\n')
    for (let i = 0; i < line - 1 && i < lines.length; i++) idx += lines[i].length + 1
    return Math.max(0, Math.min(idx + col - 1, String(text ?? '').length))
  }
  return -1
}

function lineColumn(text, pos) {
  if (pos < 0) return { line: 0, col: 0 }
  const lines = String(text ?? '').slice(0, pos).split('\n')
  return { line: lines.length, col: lines[lines.length - 1].length + 1 }
}

function renderPart(part, base, errorPos, color = null) {
  const src = String(part ?? '')
  const rel = errorPos - base
  if (rel < 0 || rel > src.length) {
    const html = esc(src)
    return color ? `<span style="color:${color}">${html}</span>` : html
  }
  const ch = rel < src.length ? src[rel] : ' '
  const before = esc(src.slice(0, rel))
  const markStyle = 'display:inline-block;min-width:0.62em;background:rgba(255,70,70,0.32);border-bottom:2px solid rgba(255,90,90,0.95);color:#ffd7d7'
  const markedText = ch === '\n' || ch === '\r' ? ' ' : (ch === ' ' ? '&nbsp;' : esc(ch))
  const marked = `<span style="${markStyle}">${markedText}</span>${ch === '\n' ? '\n' : ''}`
  const after = rel < src.length ? esc(src.slice(rel + 1)) : ''
  const html = before + marked + after
  return color ? `<span style="color:${color}">${html}</span>` : html
}

function highlightJson(text, errorPos = -1) {
  const src = String(text ?? '')
  const re = /("(?:\\.|[^"\\])*"\s*:)|("(?:\\.|[^"\\])*")|(-?\b\d+(?:\.\d+)?(?:[eE][+-]?\d+)?\b)|\b(true|false)\b|\bnull\b/g
  let out = ''
  let last = 0
  let m
  while ((m = re.exec(src))) {
    out += renderPart(src.slice(last, m.index), last, errorPos)
    const token = m[0]
    let color = '#d4d4d4'
    if (m[1]) color = '#9cdcfe'
    else if (m[2]) color = '#ce9178'
    else if (m[3]) color = '#b5cea8'
    else if (m[4]) color = '#569cd6'
    else color = '#569cd6'
    out += renderPart(token, m.index, errorPos, color)
    last = m.index + token.length
  }
  out += renderPart(src.slice(last), last, errorPos)
  return out
}

function checkJson(text) {
  const raw = String(text ?? '').trim()
  if (!raw) return null
  try {
    JSON.parse(raw)
    return null
  } catch (err) {
    return {
      message: `${t('graph.json.invalid')}: ${err.message}`,
      pos: errorPosition(err, text),
    }
  }
}

export class JsonOverlay {
  constructor(lgcanvas, container) {
    this.canvas = lgcanvas
    this.container = container
    this.entries = new Map()
  }

  ensure(node) {
    let e = this.entries.get(node)
    if (e) return e
    const prop = node._jsonPropertyName || 'value'
    const box = document.createElement('div')
    Object.assign(box.style, {
      position: 'absolute', zIndex: 44, overflow: 'hidden', background: '#0d0d0d',
      border: '1px solid #333', boxSizing: 'border-box',
    })
    const gutter = document.createElement('pre')
    Object.assign(gutter.style, {
      position: 'absolute', left: '0', top: '0', bottom: '0', width: `${GUTTER_WIDTH}px`, margin: '0',
      boxSizing: 'border-box', padding: '4px 8px', overflow: 'hidden', userSelect: 'none',
      textAlign: 'right', color: '#6e7681', background: '#111318', borderRight: '1px solid #252a31',
      fontFamily: 'monospace', lineHeight: String(LH), whiteSpace: 'pre',
    })
    const common = {
      position: 'absolute', inset: `0 0 0 ${GUTTER_WIDTH}px`, margin: '0', boxSizing: 'border-box',
      fontFamily: 'monospace', lineHeight: String(LH), whiteSpace: 'pre',
      tabSize: '2', border: 'none',
    }
    const pre = document.createElement('pre')
    Object.assign(pre.style, { ...common, overflow: 'hidden', pointerEvents: 'none', color: '#d4d4d4' })
    const tip = document.createElement('div')
    Object.assign(tip.style, {
      position: 'absolute', display: 'none', zIndex: '2', maxWidth: '320px',
      padding: '3px 7px', borderRadius: '4px', border: '1px solid #a55',
      background: '#3a1d1d', color: '#ffd7d7', boxShadow: '0 4px 12px rgba(0,0,0,.5)',
      font: '12px/1.35 monospace', whiteSpace: 'pre-wrap', pointerEvents: 'none',
    })
    const ta = document.createElement('textarea')
    ta.value = node.properties?.[prop] ?? ''
    ta.spellcheck = false
    Object.assign(ta.style, {
      ...common, resize: 'none', outline: 'none', overflow: 'auto',
      background: 'transparent', color: 'transparent', caretColor: '#d4d4d4',
      pointerEvents: 'auto',
    })
    const state = { error: null }
    const placeTip = () => {
      if (!state.error || state.error.pos < 0) {
        tip.style.display = 'none'
        return
      }
      const cs = getComputedStyle(ta)
      const fs = parseFloat(cs.fontSize) || 12
      const lh = parseFloat(cs.lineHeight) || fs * LH
      const padLeft = parseFloat(cs.paddingLeft) || 0
      const padTop = parseFloat(cs.paddingTop) || 0
      const charW = fs * 0.62
      const { line, col } = lineColumn(ta.value, state.error.pos)
      const left = GUTTER_WIDTH + padLeft + (col - 1) * charW - ta.scrollLeft + 10
      const top = padTop + (line - 1) * lh - ta.scrollTop + lh
      tip.textContent = state.error.message
      tip.style.left = `${Math.max(GUTTER_WIDTH + 6, Math.min(left, box.clientWidth - 80))}px`
      tip.style.top = `${Math.max(6, Math.min(top, box.clientHeight - 34))}px`
      tip.style.display = 'block'
    }
    const sync = () => {
      state.error = checkJson(ta.value)
      pre.innerHTML = highlightJson(ta.value, state.error?.pos ?? -1)
      pre.scrollTop = ta.scrollTop; pre.scrollLeft = ta.scrollLeft
      gutter.textContent = Array.from({ length: Math.max(1, ta.value.split('\n').length) }, (_, i) => String(i + 1)).join('\n')
      gutter.scrollTop = ta.scrollTop
      box.style.borderColor = state.error ? '#b75050' : '#333'
      placeTip()
    }
    const commit = () => {
      node.properties[prop] = ta.value
      sync()
      node.graph?._requestHistory && node.graph._requestHistory()
    }
    ta.addEventListener('input', commit)
    ta.addEventListener('scroll', () => {
      pre.scrollTop = ta.scrollTop; pre.scrollLeft = ta.scrollLeft
      gutter.scrollTop = ta.scrollTop
      placeTip()
    })
    for (const ev of ['wheel', 'keydown', 'contextmenu']) ta.addEventListener(ev, (x) => x.stopPropagation())
    ta.addEventListener('mousedown', (x) => {
      x.stopPropagation()
      LiteGraph.closeAllContextMenus(window)
    })
    ta.addEventListener('keydown', (ev) => {
      if ((ev.key === '}' || ev.key === ']') && ta.selectionStart === ta.selectionEnd && ta.value[ta.selectionStart] === ev.key) {
        ev.preventDefault()
        ta.selectionStart = ta.selectionEnd = ta.selectionStart + 1
        return
      }
      const pair = { '{': '}', '[': ']' }[ev.key]
      if (pair && !ev.ctrlKey && !ev.metaKey && !ev.altKey) {
        ev.preventDefault()
        const s = ta.selectionStart, end = ta.selectionEnd
        const selected = ta.value.slice(s, end)
        ta.value = ta.value.slice(0, s) + ev.key + selected + pair + ta.value.slice(end)
        ta.selectionStart = s + 1
        ta.selectionEnd = selected ? s + 1 + selected.length : s + 1
        commit()
        return
      }
      if (ev.key === 'Backspace' && ta.selectionStart === ta.selectionEnd && ta.selectionStart > 0) {
        const s = ta.selectionStart
        const left = ta.value[s - 1], right = ta.value[s]
        if ((left === '{' && right === '}') || (left === '[' && right === ']')) {
          ev.preventDefault()
          ta.value = ta.value.slice(0, s - 1) + ta.value.slice(s + 1)
          ta.selectionStart = ta.selectionEnd = s - 1
          commit()
          return
        }
      }
      if (ev.key === 'Tab') {
        ev.preventDefault()
        const s = ta.selectionStart, end = ta.selectionEnd
        ta.value = ta.value.slice(0, s) + '  ' + ta.value.slice(end)
        ta.selectionStart = ta.selectionEnd = s + 2
        commit()
      }
    })
    box.appendChild(gutter)
    box.appendChild(pre)
    box.appendChild(tip)
    box.appendChild(ta)
    this.container.appendChild(box)
    e = { box, gutter, pre, tip, ta, prop, sync }
    this.entries.set(node, e)
    sync()
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
      if (!nodes.includes(node)) this.remove(node)
    }
    for (const node of nodes) {
      if (node._showJson) this._place(node, this.ensure(node))
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
      left: x + 'px', top: y + 'px',
      width: Math.max(0, node.size[0] * scale) + 'px',
      height: Math.max(0, (node.size[1] - head - RESIZE_PAD) * scale) + 'px',
    })
    const fs = (12 * scale) + 'px', pad = (4 * scale) + 'px'
    e.gutter.style.fontSize = fs; e.gutter.style.padding = `${pad} ${Math.max(2 * scale, 2)}px`
    e.pre.style.fontSize = fs; e.pre.style.padding = pad
    e.ta.style.fontSize = fs; e.ta.style.padding = pad
    const value = node.properties?.[e.prop] ?? ''
    if (document.activeElement !== e.ta && e.ta.value !== value) {
      e.ta.value = value
      e.sync()
    } else {
      e.sync()
    }
  }
}
