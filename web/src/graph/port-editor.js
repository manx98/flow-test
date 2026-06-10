// 动态端口节点的统一「编辑」弹窗：批量增删改 入参/result/arg/工具/变量/出口 端口
// （含类型、描述、模块名/描述）。保存时差异应用，尽量保留已有连线（重命名不断线）。

// 可绑定的数据类型（与后端 _VAR_TYPES 对应）
const VAR_TYPES = ['match', 'point', 'text', 'number', 'bool', 'picture', 'mask', 'ocr', 'device', 'script']

// 每种节点的编辑配置：module=顶部模块字段；sections=分区(方向/筛选/是否选类型/是否带描述)
export const EDIT_CONFIG = {
  'var/set': { title: '变量', module: [], sections: [
    { label: '变量', dir: 'in', match: (p) => p.type !== 'exec', types: VAR_TYPES }] },
  'flow/sequence': { title: '顺序出口', module: [], sections: [
    { label: '出口', dir: 'out', match: (p) => p.type === 'exec', fixed: 'exec' }] },
  'script/exec': { title: 'Python 执行', module: [], sections: [
    { label: '入参', dir: 'in', match: (p) => p.type !== 'exec' && p.name !== 'script', types: VAR_TYPES },
    { label: 'result', dir: 'out', match: (p) => p.type !== 'exec', types: VAR_TYPES }] },
}

export const EDITABLE_TYPES = new Set(Object.keys(EDIT_CONFIG))

const portList = (node, dir) => (dir === 'in' ? node.inputs : node.outputs) || []

function applySection(node, sec, rows) {
  const find = (nm) => (sec.dir === 'in' ? node.findInputSlot(nm) : node.findOutputSlot(nm))
  const del = (s) => (sec.dir === 'in' ? node.removeInput(s) : node.removeOutput(s))
  const add = (nm, t) => (sec.dir === 'in' ? node.addInput(nm, t) : node.addOutput(nm, t))
  const cur = portList(node, sec.dir).filter(sec.match).map((p) => p.name)
  const keep = new Set(rows.filter((r) => r.orig).map((r) => r.orig))
  // 1) 删除：现有端口不在保留集
  for (const nm of cur) if (!keep.has(nm)) { const s = find(nm); if (s >= 0) del(s) }
  // 2) 已有端口：改名(保连线)/改类型(断旧连线)
  for (const r of rows) {
    if (!r.orig) continue
    const s = find(r.orig)
    if (s < 0) continue
    const port = portList(node, sec.dir)[s]
    const nt = sec.types ? r.type : (sec.fixed || port.type)
    if (port.type !== nt) {
      port.type = nt
      if (sec.dir === 'in') node.disconnectInput(s); else node.disconnectOutput(s)
    }
    if (port.name !== r.name) port.name = r.name
  }
  // 3) 新增
  for (const r of rows) if (!r.orig) add(r.name, sec.types ? r.type : (sec.fixed || 'any'))
}

// 深色面板 + textarea 风格，复用项目里弹窗观感
export function openPortEditor(node) {
  const cfg = EDIT_CONFIG[node._spec?.type]
  if (!cfg) return
  node.properties = node.properties || {}

  const mask = document.createElement('div')
  Object.assign(mask.style, { position: 'fixed', inset: '0', zIndex: 9999, background: 'rgba(0,0,0,0.5)', display: 'flex', alignItems: 'center', justifyContent: 'center' })
  const onKey = (e) => { if (e.key === 'Escape') close() }
  const close = () => { try { mask.remove() } catch (_) {} document.removeEventListener('keydown', onKey) }
  document.addEventListener('keydown', onKey)
  mask.addEventListener('mousedown', (e) => { if (e.target === mask) close() })

  const panel = document.createElement('div')
  Object.assign(panel.style, { width: 'min(640px, 94vw)', maxHeight: '86vh', overflow: 'auto', boxSizing: 'border-box', background: '#23262b', color: '#e6e6e6', borderRadius: '8px', padding: '14px 18px', boxShadow: '0 8px 32px rgba(0,0,0,0.5)', font: '13px system-ui, sans-serif', display: 'flex', flexDirection: 'column', gap: '10px' })
  panel.addEventListener('mousedown', (e) => e.stopPropagation())
  panel.addEventListener('wheel', (e) => e.stopPropagation())
  const h = document.createElement('div'); h.textContent = '编辑 ' + cfg.title; Object.assign(h.style, { fontSize: '15px', fontWeight: '700', color: '#fff' })
  panel.appendChild(h)

  // 顶部模块字段
  const moduleInputs = {}
  for (const f of cfg.module) {
    const wrap = document.createElement('label'); Object.assign(wrap.style, { display: 'flex', gap: '8px', alignItems: f.multiline ? 'flex-start' : 'center' })
    const lab = document.createElement('span'); lab.textContent = f.label; Object.assign(lab.style, { flex: '0 0 56px', color: '#9fd0ff' })
    const inp = document.createElement(f.multiline ? 'textarea' : 'input')
    inp.value = node.properties[f.key] ?? f.def ?? ''
    Object.assign(inp.style, { flex: '1', background: '#0d0d0d', color: '#ddd', border: '1px solid #333', borderRadius: '4px', padding: '4px 6px', font: '13px monospace', outline: 'none' })
    if (f.multiline) { inp.rows = 2; inp.wrap = 'off'; Object.assign(inp.style, { resize: 'vertical', whiteSpace: 'pre', overflowX: 'auto' }) }
    wrap.appendChild(lab); wrap.appendChild(inp); panel.appendChild(wrap)
    moduleInputs[f.key] = inp
  }

  // 分区行编辑
  const secRows = []   // [{sec, rows:[{orig,name,type,desc, el}], addRow}]
  const inputStyle = { background: '#0d0d0d', color: '#ddd', border: '1px solid #333', borderRadius: '4px', padding: '3px 5px', font: '12px monospace', outline: 'none' }
  for (const sec of cfg.sections) {
    const title = document.createElement('div'); title.textContent = '— ' + sec.label; Object.assign(title.style, { color: '#bcd', marginTop: '6px', fontSize: '12px' })
    panel.appendChild(title)
    const tbl = document.createElement('div'); Object.assign(tbl.style, { display: 'flex', flexDirection: 'column', gap: '4px' })
    panel.appendChild(tbl)
    const rows = []
    const mkRow = (orig, name, type, desc) => {
      const row = document.createElement('div'); Object.assign(row.style, { display: 'flex', gap: '6px', alignItems: sec.descProp ? 'flex-start' : 'center' })
      const nameI = document.createElement('input'); nameI.value = name || ''; nameI.placeholder = '名称'; Object.assign(nameI.style, { ...inputStyle, flex: '1' })
      row.appendChild(nameI)
      let typeS = null
      if (sec.types) {
        typeS = document.createElement('select'); Object.assign(typeS.style, { ...inputStyle, flex: '0 0 92px' })
        for (const t of sec.types) { const o = document.createElement('option'); o.value = o.textContent = t; typeS.appendChild(o) }
        typeS.value = type || sec.types[0]
        row.appendChild(typeS)
      }
      let descI = null
      if (sec.descProp) {
        descI = document.createElement('textarea'); descI.value = desc || ''; descI.placeholder = '描述（支持多行）'; descI.rows = 2; descI.wrap = 'off'
        Object.assign(descI.style, { ...inputStyle, flex: '1.3', resize: 'vertical', whiteSpace: 'pre', overflowX: 'auto', lineHeight: '1.4' })
        row.appendChild(descI)
      }
      const del = document.createElement('button'); del.textContent = '×'; Object.assign(del.style, { flex: '0 0 auto', cursor: 'pointer', border: 'none', borderRadius: '3px', background: '#5a2a2a', color: '#fdd', padding: '2px 8px' })
      const entry = { get orig() { return orig }, get name() { return nameI.value.trim() }, get type() { return typeS ? typeS.value : (sec.fixed || 'any') }, get desc() { return descI ? descI.value.trim() : '' } }
      del.addEventListener('click', () => { row.remove(); const i = rows.indexOf(entry); if (i >= 0) rows.splice(i, 1) })
      row.appendChild(del)
      tbl.appendChild(row); rows.push(entry)
    }
    // 现有端口 → 行
    const descMap = sec.descProp ? (node.properties[sec.descProp] || {}) : {}
    for (const p of portList(node, sec.dir).filter(sec.match)) mkRow(p.name, p.name, p.type, descMap[p.name])
    const addBtn = document.createElement('button'); addBtn.textContent = '+ 添加 ' + sec.label.split('（')[0]
    Object.assign(addBtn.style, { alignSelf: 'flex-start', cursor: 'pointer', border: '1px dashed #567', borderRadius: '4px', background: 'transparent', color: '#9cf', padding: '3px 10px', marginTop: '2px' })
    addBtn.addEventListener('click', () => mkRow(null, '', sec.types ? sec.types[0] : '', ''))
    panel.appendChild(addBtn)
    secRows.push({ sec, rows })
  }

  // 底部按钮
  const foot = document.createElement('div'); Object.assign(foot.style, { display: 'flex', justifyContent: 'flex-end', gap: '8px', marginTop: '8px' })
  const cancel = document.createElement('button'); cancel.textContent = '取消'
  const save = document.createElement('button'); save.textContent = '保存'
  for (const b of [cancel, save]) Object.assign(b.style, { padding: '5px 16px', cursor: 'pointer', borderRadius: '4px', border: 'none' })
  Object.assign(save.style, { background: '#2b6cb0', color: '#fff' }); Object.assign(cancel.style, { background: '#3a3a3a', color: '#ddd' })
  cancel.addEventListener('click', close)
  save.addEventListener('click', () => {
    // 校验名称非空/不重复（每区内）
    for (const { sec, rows } of secRows) {
      const names = rows.map((r) => r.name)
      if (names.some((n) => !n)) { alert('有端口名称为空'); return }
      if (new Set(names).size !== names.length) { alert(sec.label + ' 有重复名称'); return }
    }
    for (const f of cfg.module) node.properties[f.key] = moduleInputs[f.key].value
    for (const { sec, rows } of secRows) {
      applySection(node, sec, rows)
      if (sec.descProp) {
        const m = {}; for (const r of rows) m[r.name] = r.desc
        node.properties[sec.descProp] = m
      }
    }
    node.setDirtyCanvas && node.setDirtyCanvas(true, true)
    node.graph?._requestHistory && node.graph._requestHistory()
    close()
  })
  foot.appendChild(cancel); foot.appendChild(save); panel.appendChild(foot)

  mask.appendChild(panel); document.body.appendChild(mask)
}
