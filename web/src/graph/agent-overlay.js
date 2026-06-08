// Agent 展示：在「Agent 展示」节点画面区用 DOM 滚动显示所连 Agent 的每步执行过程。
// 由 App.vue 收到 agent_step 事件后调用 onStep(agentId, ev) 追加。
import { LiteGraph } from 'litegraph.js'

const RESIZE_PAD = 12

export class AgentTraceOverlay {
  constructor(lgcanvas, container) {
    this.canvas = lgcanvas
    this.container = container
    this.entries = new Map()   // 展示节点 -> { box }
  }

  ensure(node) {
    let e = this.entries.get(node)
    if (e) return e
    const box = document.createElement('div')
    Object.assign(box.style, {
      position: 'absolute', zIndex: 45, overflow: 'auto', background: '#0d0d0d',
      border: '1px solid #333', boxSizing: 'border-box', color: '#cdd',
      fontFamily: 'monospace', whiteSpace: 'pre-wrap', wordBreak: 'break-word',
      pointerEvents: 'auto', padding: '4px',
    })
    // 不让滚动/选择冒泡到画布
    box.addEventListener('mousedown', (ev) => ev.stopPropagation())
    box.addEventListener('wheel', (ev) => ev.stopPropagation())
    this.container.appendChild(box)
    e = { box }
    this.entries.set(node, e)
    return e
  }

  remove(node) {
    const e = this.entries.get(node)
    if (!e) return
    this.entries.delete(node)
    try { e.box.remove() } catch (_) {}
  }

  // 运行开始时清空各展示节点
  clearAll() {
    for (const e of this.entries.values()) e.box.innerHTML = ''
  }

  // 展示节点上游的 Agent 节点 id（经 trace 输入）
  _agentId(node) {
    const slot = (node.inputs || []).findIndex((i) => i.name === 'trace')
    if (slot < 0) return null
    const up = node.getInputNode(slot)
    return up && up._spec?.type === 'agent/run' ? up.id : null
  }

  // App.vue 收到 agent_step 事件时调用：把该步追加到对应 Agent 的展示节点
  onStep(agentId, ev) {
    for (const [node, e] of this.entries) {
      if (this._agentId(node) !== agentId) continue
      const div = document.createElement('div')
      Object.assign(div.style, { borderBottom: '1px solid #1f1f1f', padding: '2px 0' })
      const head = document.createElement('div')
      head.textContent = `▸ 第${ev.step}步  ${ev.reasoning || ''}`
      head.style.color = '#9fd0ff'
      const body = document.createElement('div')
      body.style.color = ev.finish ? (ev.success ? '#7bd88f' : '#e98') : '#cdd'
      body.textContent = ev.finish
        ? `  ✓ finish(success=${ev.success})：${ev.result || ''}`
        : `  🔧 ${ev.tool}(${ev.args}) = ${ev.result}`
      div.appendChild(head); div.appendChild(body)
      e.box.appendChild(div)
      e.box.scrollTop = e.box.scrollHeight
    }
  }

  update(nodes) {
    for (const node of [...this.entries.keys()]) {
      if (!nodes.includes(node)) this.remove(node)
    }
    for (const node of nodes) {
      if (node._spec?.type === 'agent/display') this._place(node, this.ensure(node))
    }
  }

  _bodyTop(node) {
    const slotH = LiteGraph.NODE_SLOT_HEIGHT || 20
    const rows = Math.max(node.inputs?.length || 0, node.outputs?.length || 0)
    return rows * slotH + 8
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
      fontSize: (11 * scale) + 'px',
    })
  }
}
