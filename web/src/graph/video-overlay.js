// 把 <video> 绝对定位覆盖在节点画面区，随平移/缩放同步；并转发鼠标键盘到设备。
import { LiteGraph } from 'litegraph.js'

// Qt/RDP 用的规范键名
const SPECIAL = {
  Enter: 'enter', Backspace: 'backspace', Tab: 'tab', Escape: 'esc', Delete: 'delete',
  ArrowUp: 'up', ArrowDown: 'down', ArrowLeft: 'left', ArrowRight: 'right',
  Home: 'home', End: 'end', PageUp: 'pageup', PageDown: 'pagedown',
}
const BTN = ['left', 'middle', 'right']

// 设备分辨率宽高比（无则退回 16:9）
function aspectOf(conn) {
  return conn.width && conn.height ? conn.width / conn.height : 16 / 9
}

// 顶部留给端口行 + 按钮 widgets 的高度（节点单位）：让画面落到它们下方。
function headerHeight(node) {
  const slotH = LiteGraph.NODE_SLOT_HEIGHT || 20
  const wh = LiteGraph.NODE_WIDGET_HEIGHT || 20
  const rows = Math.max(node.inputs?.length || 0, node.outputs?.length || 0)
  const widgets = node.widgets ? node.widgets.length : 0
  return rows * slotH + widgets * (wh + 4) + 6
}

export class VideoOverlay {
  constructor(lgcanvas, container) {
    this.canvas = lgcanvas
    this.container = container
    this.entries = new Map()   // 人机交互节点 -> { video, conn }
  }

  // node：人机交互节点；conn：其上游设备的 DeviceConnection（共享视频轨）。
  attach(node, conn) {
    const video = document.createElement('video')
    video.autoplay = true
    video.muted = true
    video.tabIndex = 0
    Object.assign(video.style, {
      position: 'absolute', objectFit: 'fill', background: '#000',
      zIndex: 50, outline: 'none', cursor: 'default',
    })
    this._bindInput(video, conn)
    this.container.appendChild(video)
    conn.attachVideo(video)

    // 视频盖住了 LiteGraph 自带的缩放角，自己加一个右下角手柄调节节点尺寸。
    const grip = document.createElement('div')
    Object.assign(grip.style, {
      position: 'absolute', width: '16px', height: '16px', zIndex: 51,
      cursor: 'nwse-resize', pointerEvents: 'auto',
      background: 'linear-gradient(135deg, transparent 45%, #6cf 45%)',
    })
    this._bindResize(node, grip, conn)
    this.container.appendChild(grip)

    // 画面在端口行下方按设备宽高比铺满整宽：节点高 = 顶部端口区 + 画面高
    node.size[1] = headerHeight(node) + node.size[0] / aspectOf(conn)

    this.entries.set(node, { video, conn, grip })
    this._place(node, video, grip)   // 立即定位，避免等下一帧重绘时铺满界面
    return video
  }

  // 仅移除显示面与输入转发；设备连接的生命周期归设备节点管。
  detach(node) {
    const e = this.entries.get(node)
    if (!e) return
    this.entries.delete(node)
    try { e.conn.detachVideo(e.video) } catch (_) {}
    try { e.video.remove() } catch (_) {}
    try { e.grip.remove() } catch (_) {}
  }

  has(node) { return this.entries.has(node) }

  connOf(node) { return this.entries.get(node)?.conn || null }

  // 每帧重定位（在 LGraphCanvas 的 onDrawForeground 里调用）
  update() {
    for (const [node, { video, grip }] of this.entries) this._place(node, video, grip)
  }

  // 按节点在画布上的位置/尺寸把 <video> 与缩放手柄绝对定位到画面区。
  _place(node, video, grip) {
    const ds = this.canvas.ds
    const rect = this.canvas.canvas.getBoundingClientRect()
    const crect = this.container.getBoundingClientRect()
    const scale = ds.scale
    const head = headerHeight(node) * scale   // 顶部端口行区域，画面让到其下方
    const x = rect.left - crect.left + (node.pos[0] + ds.offset[0]) * scale
    const y = rect.top - crect.top + (node.pos[1] + ds.offset[1]) * scale
    const w = node.size[0] * scale
    const h = node.size[1] * scale
    video.style.left = x + 'px'
    video.style.top = (y + head) + 'px'
    video.style.width = w + 'px'
    video.style.height = Math.max(0, h - head) + 'px'
    if (grip) {
      grip.style.left = (x + w - 16) + 'px'
      grip.style.top = (y + h - 16) + 'px'
    }
  }

  // 拖右下角手柄改 node.size：宽度跟随拖动，高度按设备宽高比等比换算。
  _bindResize(node, grip, conn) {
    const onMove = (ev) => {
      const scale = this.canvas.ds.scale
      const w = Math.max(120, this._rs.w + (ev.clientX - this._rs.x) / scale)
      node.size[0] = w
      node.size[1] = headerHeight(node) + w / aspectOf(conn)   // 画面区保持设备比例
      this.canvas.setDirty(true, true)
    }
    const onUp = () => {
      window.removeEventListener('mousemove', onMove)
      window.removeEventListener('mouseup', onUp)
    }
    grip.addEventListener('mousedown', (ev) => {
      ev.preventDefault(); ev.stopPropagation()
      this._rs = { x: ev.clientX, y: ev.clientY, w: node.size[0], h: node.size[1] }
      window.addEventListener('mousemove', onMove)
      window.addEventListener('mouseup', onUp)
    })
  }

  _devCoords(video, conn, ev) {
    const r = video.getBoundingClientRect()
    const x = Math.round((ev.clientX - r.left) / r.width * conn.width)
    const y = Math.round((ev.clientY - r.top) / r.height * conn.height)
    return { x: Math.max(0, x), y: Math.max(0, y) }
  }

  _bindInput(video, conn) {
    video.addEventListener('mousemove', (ev) => {
      const { x, y } = this._devCoords(video, conn, ev)
      conn.send({ t: 'move', x, y })
    })
    video.addEventListener('mousedown', (ev) => {
      ev.preventDefault(); video.focus()
      const { x, y } = this._devCoords(video, conn, ev)
      conn.send({ t: 'down', x, y, button: BTN[ev.button] || 'left' })
    })
    video.addEventListener('mouseup', (ev) => {
      const { x, y } = this._devCoords(video, conn, ev)
      conn.send({ t: 'up', x, y, button: BTN[ev.button] || 'left' })
    })
    video.addEventListener('contextmenu', (ev) => ev.preventDefault())
    video.addEventListener('wheel', (ev) => {
      ev.preventDefault()
      const { x, y } = this._devCoords(video, conn, ev)
      conn.send({ t: 'scroll', x, y, dy: ev.deltaY < 0 ? 1 : -1 })
    }, { passive: false })
    video.addEventListener('keydown', (ev) => {
      const name = SPECIAL[ev.key]
      if (name) { conn.send({ t: 'key', name, down: true }); conn.send({ t: 'key', name, down: false }); ev.preventDefault() }
      else if (ev.key.length === 1 && !ev.ctrlKey && !ev.metaKey) { conn.send({ t: 'text', text: ev.key }); ev.preventDefault() }
    })
  }
}
