// 截图节点：用 DOM <img> 覆盖在节点画面区回显截取帧，支持滚轮缩放查看与框选裁剪。
// 裁剪框以图片像素坐标存 node.properties.crop = {x,y,w,h}。
import { LiteGraph } from 'litegraph.js'

const ZOOM_MAX = 8
const RESIZE_PAD = 12   // 底部留白(节点单位)，露出 LiteGraph 右下角原生缩放手柄

// 节点当前图片文件名（模板图片 name / 截图 image）
function nameOf(node) {
  return node.properties?.name || node.properties?.image || ''
}

// 复制文本到剪贴板（带 execCommand 兜底）
async function copyText(t) {
  try { await navigator.clipboard.writeText(t); return true } catch (_) {}
  try {
    const ta = document.createElement('textarea')
    ta.value = t; ta.style.position = 'fixed'; ta.style.opacity = '0'
    document.body.appendChild(ta); ta.select()
    const ok = document.execCommand('copy'); ta.remove(); return ok
  } catch (_) { return false }
}

export class ShotOverlay {
  constructor(lgcanvas, container) {
    this.canvas = lgcanvas
    this.container = container
    this.entries = new Map()   // 截图节点 -> { wrap, img, sel, view, dragging }
    this.onRename = null       // async (node, newName) => void
  }

  setRenameHandler(fn) { this.onRename = fn }

  ensure(node) {
    let e = this.entries.get(node)
    if (e) return e
    const wrap = document.createElement('div')
    Object.assign(wrap.style, {
      position: 'absolute', zIndex: 40, background: '#111', overflow: 'hidden',
      pointerEvents: 'auto', cursor: 'crosshair', boxSizing: 'border-box',
      border: '1px solid #333',
    })
    const img = document.createElement('img')
    img.draggable = false
    Object.assign(img.style, {
      position: 'absolute', display: 'none', userSelect: 'none', pointerEvents: 'none',
    })
    const sel = document.createElement('div')
    Object.assign(sel.style, {
      position: 'absolute', border: '1.5px solid #6cf', display: 'none',
      boxShadow: '0 0 0 9999px rgba(0,0,0,0.45)', pointerEvents: 'none',
    })
    const cap = document.createElement('div')   // 文件名标签（底部页脚，点击复制）
    cap.title = '点击复制文件名'
    Object.assign(cap.style, {
      position: 'absolute', left: '0', bottom: '0', right: '0', display: 'none',
      padding: '2px 6px', font: '11px monospace', color: '#cde',
      background: 'rgba(0,0,0,0.55)', pointerEvents: 'auto', cursor: 'pointer',
      whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
    })
    const ren = document.createElement('div')   // 重命名按钮（页脚右侧）
    ren.textContent = '✎'; ren.title = '重命名'
    Object.assign(ren.style, {
      position: 'absolute', right: '0', bottom: '0', display: 'none',
      padding: '2px 6px', color: '#cde', background: 'rgba(0,0,0,0.55)',
      cursor: 'pointer', pointerEvents: 'auto', font: '11px monospace',
    })
    wrap.appendChild(img)
    wrap.appendChild(sel)
    wrap.appendChild(cap)
    wrap.appendChild(ren)
    this.container.appendChild(wrap)
    e = { wrap, img, sel, cap, ren, view: { zoom: 1, panX: null, panY: null }, dragging: null }
    this.entries.set(node, e)
    this._bindWheel(node, e)
    if (node._spec?.type === 'vision/screenshot') this._bindCrop(node, e)  // 仅截图节点支持裁剪
    cap.addEventListener('mousedown', (ev) => ev.stopPropagation())   // 不触发框选/拖拽
    cap.addEventListener('click', async (ev) => {
      ev.stopPropagation()
      const name = nameOf(node)
      if (name && await copyText(name)) e._copiedUntil = Date.now() + 1200
    })
    ren.addEventListener('mousedown', (ev) => ev.stopPropagation())
    ren.addEventListener('click', async (ev) => {
      ev.stopPropagation()
      const cur = nameOf(node)
      if (!cur || !this.onRename) return
      const nn = (prompt('重命名为', cur) || '').trim()
      if (!nn || nn === cur) return
      try { await this.onRename(node, nn) } catch (err) { alert('重命名失败: ' + err.message) }
    })
    return e
  }

  // fit:true → 加载后按图片宽高比立即调整卡片尺寸
  setImage(node, url, opts = {}) {
    const e = this.ensure(node)
    e.view = { zoom: 1, panX: null, panY: null }
    e.img.onload = () => {
      if (opts.fit) this._fitNode(node, e)
      this._layout(node, e)
      this.canvas.setDirty(true, true)
    }
    e.img.src = url
  }

  remove(node) {
    const e = this.entries.get(node)
    if (!e) return
    this.entries.delete(node)
    try { e.wrap.remove() } catch (_) {}
  }

  // 每帧：同步带图节点（截图 / 模板图片）+ 重定位 + 画面/裁剪布局
  update(nodes) {
    for (const node of [...this.entries.keys()]) {
      if (!nodes.includes(node)) this.remove(node)
    }
    for (const node of nodes) {
      const t = node._spec?.type
      if (t === 'vision/screenshot' || t === 'const/image') this._place(node, this.ensure(node))
    }
  }

  // 画面区顶端（节点单位）：让过顶部端口行与按钮 widgets
  _bodyTop(node) {
    const slotH = LiteGraph.NODE_SLOT_HEIGHT || 20
    const wh = LiteGraph.NODE_WIDGET_HEIGHT || 20
    const rows = Math.max(node.inputs?.length || 0, node.outputs?.length || 0)
    const widgets = node.widgets ? node.widgets.length : 0
    return rows * slotH + widgets * (wh + 4) + 8
  }

  // 按图片宽高比把卡片高度调到刚好展示画面（宽度给个下限）
  _fitNode(node, e) {
    const iw = e.img.naturalWidth, ih = e.img.naturalHeight
    if (!iw || !ih) return
    node.size[0] = Math.max(node.size[0], 240)
    node.size[1] = this._bodyTop(node) + node.size[0] * ih / iw + RESIZE_PAD
  }

  // 定位 wrap（节点画面区），再布局内部图片与裁剪框
  _place(node, e) {
    const ds = this.canvas.ds
    const rect = this.canvas.canvas.getBoundingClientRect()
    const crect = this.container.getBoundingClientRect()
    const scale = ds.scale
    const head = this._bodyTop(node)
    const x = rect.left - crect.left + (node.pos[0] + ds.offset[0]) * scale
    const y = rect.top - crect.top + (node.pos[1] + ds.offset[1] + head) * scale
    Object.assign(e.wrap.style, {
      left: x + 'px', top: y + 'px',
      width: Math.max(0, node.size[0] * scale) + 'px',
      height: Math.max(0, (node.size[1] - head - RESIZE_PAD) * scale) + 'px',
    })
    // 文件名回显（点击复制）+ 重命名按钮；字号/内边距随画布缩放保持同比例
    const fname = nameOf(node)
    const fs = (11 * scale) + 'px', pad = (2 * scale) + 'px ' + (6 * scale) + 'px'
    if (fname) {
      e.cap.style.display = 'block'
      e.cap.textContent = (e._copiedUntil && Date.now() < e._copiedUntil) ? '已复制 ✓' : fname
      e.cap.style.fontSize = fs; e.cap.style.padding = pad
      e.ren.style.display = 'block'
      e.ren.style.fontSize = fs; e.ren.style.padding = pad
      e.cap.style.paddingRight = (24 * scale) + 'px'   // 给右侧 ✎ 让位
    } else {
      e.cap.style.display = 'none'
      e.ren.style.display = 'none'
    }
    this._layout(node, e)
  }

  // 由视图状态（fit×zoom + 平移锚点）算图片在 wrap 内的实际矩形（wrap 像素 + 图片像素比例）
  _placement(e) {
    const r = e.wrap.getBoundingClientRect()
    const iw = e.img.naturalWidth, ih = e.img.naturalHeight
    if (!iw || !ih || !r.width || !r.height) return null
    const fit = Math.min(r.width / iw, r.height / ih)
    const scale = fit * (e.view.zoom || 1)
    const panX = e.view.panX == null ? iw / 2 : e.view.panX
    const panY = e.view.panY == null ? ih / 2 : e.view.panY
    const x = r.width / 2 - panX * scale
    const y = r.height / 2 - panY * scale
    return { x, y, scale, fit, iw, ih, w: r.width, h: r.height }
  }

  _layout(node, e) {
    const p = this._placement(e)
    if (!p) { e.img.style.display = 'none'; e.sel.style.display = 'none'; return }
    Object.assign(e.img.style, {
      display: 'block', left: p.x + 'px', top: p.y + 'px',
      width: p.iw * p.scale + 'px', height: p.ih * p.scale + 'px',
    })
    if (e.dragging) return
    const c = node.properties?.crop
    if (!c) { e.sel.style.display = 'none'; return }
    Object.assign(e.sel.style, {
      display: 'block',
      left: (p.x + c.x * p.scale) + 'px', top: (p.y + c.y * p.scale) + 'px',
      width: (c.w * p.scale) + 'px', height: (c.h * p.scale) + 'px',
    })
  }

  // 滚轮以光标为锚点缩放（不冒泡给画布，避免连带缩放整个图）
  _bindWheel(node, e) {
    e.wrap.addEventListener('wheel', (ev) => {
      const p = this._placement(e)
      if (!p) return
      ev.preventDefault(); ev.stopPropagation()
      const r = e.wrap.getBoundingClientRect()
      const cx = ev.clientX - r.left, cy = ev.clientY - r.top
      const imgX = (cx - p.x) / p.scale, imgY = (cy - p.y) / p.scale
      const zoom = Math.min(ZOOM_MAX, Math.max(1, (e.view.zoom || 1) * (ev.deltaY < 0 ? 1.15 : 1 / 1.15)))
      e.view.zoom = zoom
      if (zoom <= 1) { e.view.panX = e.view.panY = null }
      else {
        const newScale = p.fit * zoom
        e.view.panX = Math.min(p.iw, Math.max(0, imgX + (r.width / 2 - cx) / newScale))
        e.view.panY = Math.min(p.ih, Math.max(0, imgY + (r.height / 2 - cy) / newScale))
      }
      this._layout(node, e)
      this.canvas.setDirty(true, true)
    }, { passive: false })
  }

  _bindCrop(node, e) {
    // 把光标位置夹到当前可见的图片范围内（wrap 像素）
    const clampToImg = (ev, p) => {
      const r = e.wrap.getBoundingClientRect()
      const left = Math.max(0, p.x), right = Math.min(r.width, p.x + p.iw * p.scale)
      const top = Math.max(0, p.y), bot = Math.min(r.height, p.y + p.ih * p.scale)
      return {
        x: Math.min(Math.max(ev.clientX - r.left, left), right),
        y: Math.min(Math.max(ev.clientY - r.top, top), bot),
      }
    }
    e.wrap.addEventListener('mousedown', (ev) => {
      const p = this._placement(e)
      if (!p || ev.button !== 0) return
      ev.preventDefault(); ev.stopPropagation()
      const s = clampToImg(ev, p)
      e.dragging = { ox: s.x, oy: s.y }
      const onMove = (m) => {
        const q = clampToImg(m, p)
        Object.assign(e.sel.style, {
          display: 'block',
          left: Math.min(q.x, e.dragging.ox) + 'px', top: Math.min(q.y, e.dragging.oy) + 'px',
          width: Math.abs(q.x - e.dragging.ox) + 'px', height: Math.abs(q.y - e.dragging.oy) + 'px',
        })
      }
      const onUp = (u) => {
        window.removeEventListener('mousemove', onMove)
        window.removeEventListener('mouseup', onUp)
        const q = clampToImg(u, p)
        const left = Math.min(q.x, e.dragging.ox), top = Math.min(q.y, e.dragging.oy)
        const w = Math.abs(q.x - e.dragging.ox), h = Math.abs(q.y - e.dragging.oy)
        e.dragging = null
        node.properties = node.properties || {}
        if (w > 3 && h > 3) {
          node.properties.crop = {
            x: Math.round((left - p.x) / p.scale), y: Math.round((top - p.y) / p.scale),
            w: Math.round(w / p.scale), h: Math.round(h / p.scale),
          }
        }
        this._layout(node, e)
      }
      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', onUp)
    })
  }
}
