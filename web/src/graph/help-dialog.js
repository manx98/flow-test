// 组件说明弹窗：右键菜单「📖 组件说明」打开，展示节点描述 + 出入参 + 属性。
// 数据来自节点 _spec（即服务端 flow/catalog.py 的单一真源）。
import { t } from '../i18n.js'

// 基数/必选 → 中文连接说明
function conn(p) {
  const card = p.cardinality === '*' ? t('graph.help.multiConnect') : t('graph.help.singleConnect')
  return p.required ? card + ' · ' + t('graph.help.required') : card
}

// 类型徽标（带 catalog.types 里的颜色小点）
function typeTag(type, colors) {
  const span = document.createElement('span')
  Object.assign(span.style, { display: 'inline-flex', alignItems: 'center', gap: '4px', whiteSpace: 'nowrap' })
  const dot = document.createElement('span')
  Object.assign(dot.style, {
    width: '8px', height: '8px', borderRadius: '50%', flex: '0 0 auto',
    background: (colors && colors[type]) || '#888',
    boxShadow: '0 0 0 1px rgba(255,255,255,0.25)',
  })
  const txt = document.createElement('span'); txt.textContent = type
  span.appendChild(dot); span.appendChild(txt)
  return span
}

function makeTable(headers) {
  const table = document.createElement('table')
  Object.assign(table.style, { width: '100%', borderCollapse: 'collapse', margin: '4px 0 12px' })
  const thead = document.createElement('thead')
  const tr = document.createElement('tr')
  for (const h of headers) {
    const th = document.createElement('th')
    th.textContent = h
    Object.assign(th.style, {
      textAlign: 'left', padding: '4px 8px', fontWeight: '600', color: '#9fd0ff',
      borderBottom: '1px solid rgba(255,255,255,0.18)', whiteSpace: 'nowrap',
    })
    tr.appendChild(th)
  }
  thead.appendChild(tr); table.appendChild(thead)
  const tbody = document.createElement('tbody'); table.appendChild(tbody)
  return { table, tbody }
}

function addRow(tbody, cells) {
  const tr = document.createElement('tr')
  for (const c of cells) {
    const td = document.createElement('td')
    Object.assign(td.style, {
      padding: '4px 8px', borderBottom: '1px solid rgba(255,255,255,0.07)',
      verticalAlign: 'top', color: '#e6e6e6',
    })
    if (c instanceof Node) td.appendChild(c)
    else td.textContent = c == null || c === '' ? t('graph.help.empty') : String(c)
    tr.appendChild(td)
  }
  tbody.appendChild(tr)
}

function section(title) {
  const h = document.createElement('div')
  h.textContent = title
  Object.assign(h.style, { fontWeight: '600', fontSize: '13px', color: '#fff', margin: '10px 0 2px' })
  return h
}

// 等宽代码单元格（函数签名 / 注入名）
function codeCell(text) {
  const c = document.createElement('code')
  c.textContent = text
  Object.assign(c.style, { fontFamily: 'monospace', color: '#dcdcaa', userSelect: 'text' })
  c.addEventListener('mousedown', (e) => e.stopPropagation())
  return c
}

// 打开组件说明弹窗。spec=节点 _spec；colors=catalog.types 颜色表。
export function showNodeHelp(spec, colors) {
  if (!spec) return
  const mask = document.createElement('div')
  Object.assign(mask.style, {
    position: 'fixed', inset: '0', zIndex: 9999, background: 'rgba(0,0,0,0.5)',
    display: 'flex', alignItems: 'center', justifyContent: 'center',
  })
  const close = () => { try { mask.remove() } catch (_) {} document.removeEventListener('keydown', onKey) }
  const onKey = (e) => { if (e.key === 'Escape') close() }
  document.addEventListener('keydown', onKey)
  mask.addEventListener('mousedown', (e) => { if (e.target === mask) close() })

  const panel = document.createElement('div')
  Object.assign(panel.style, {
    width: 'min(680px, 92vw)', maxHeight: '85vh', overflow: 'auto', boxSizing: 'border-box',
    background: '#23262b', color: '#e6e6e6', borderRadius: '8px', padding: '16px 20px',
    boxShadow: '0 8px 32px rgba(0,0,0,0.5)', fontSize: '12px', lineHeight: '1.6',
    fontFamily: 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif',
  })
  panel.addEventListener('wheel', (e) => e.stopPropagation())

  // 标题栏：标题 + 类型 + 关闭
  const head = document.createElement('div')
  Object.assign(head.style, { display: 'flex', alignItems: 'baseline', gap: '10px', marginBottom: '6px' })
  const title = document.createElement('div')
  title.textContent = spec.title || spec.type
  Object.assign(title.style, { fontSize: '17px', fontWeight: '700', color: '#fff' })
  const typeCode = document.createElement('code')
  typeCode.textContent = spec.type
  Object.assign(typeCode.style, { color: '#9aa', fontSize: '12px' })
  const cat = document.createElement('span')
  cat.textContent = spec.category || ''
  Object.assign(cat.style, {
    marginLeft: 'auto', fontSize: '11px', color: '#bcd', padding: '1px 8px',
    border: '1px solid rgba(255,255,255,0.2)', borderRadius: '10px',
  })
  const btn = document.createElement('button')
  btn.textContent = '✕'; btn.title = t('graph.help.closeTitle')
  Object.assign(btn.style, {
    cursor: 'pointer', border: 'none', background: 'transparent', color: '#bbb',
    fontSize: '16px', lineHeight: '1', padding: '0 2px',
  })
  btn.addEventListener('click', close)
  head.appendChild(title); head.appendChild(typeCode); head.appendChild(cat); head.appendChild(btn)
  panel.appendChild(head)

  // 描述
  if (spec.description) {
    const d = document.createElement('div')
    d.textContent = spec.description
    Object.assign(d.style, { color: '#cfd6dd', margin: '2px 0 6px' })
    panel.appendChild(d)
  }

  // 对应脚本函数：在脚本节点里等价调用此组件
  if (spec.script) {
    const row = document.createElement('div')
    Object.assign(row.style, {
      display: 'flex', alignItems: 'center', gap: '8px', margin: '6px 0',
      padding: '6px 10px', background: 'rgba(120,180,255,0.08)',
      border: '1px solid rgba(120,180,255,0.25)', borderRadius: '6px',
    })
    const lbl = document.createElement('span')
    lbl.textContent = t('graph.help.scriptFunction')
    Object.assign(lbl.style, { color: '#9fd0ff', flex: '0 0 auto', fontSize: '11px' })
    const code = document.createElement('code')
    code.textContent = spec.script
    Object.assign(code.style, {
      flex: '1', color: '#e6e6e6', fontFamily: 'monospace', userSelect: 'text',
      cursor: 'text', wordBreak: 'break-all',
    })
    code.addEventListener('mousedown', (e) => e.stopPropagation())
    const copy = document.createElement('button')
    copy.textContent = '⧉'; copy.title = t('graph.help.copyFunction')
    Object.assign(copy.style, {
      flex: '0 0 auto', cursor: 'pointer', border: 'none', borderRadius: '3px',
      background: 'rgba(255,255,255,0.12)', color: '#fff', padding: '1px 6px', lineHeight: '1',
    })
    copy.addEventListener('click', async () => {
      try { await navigator.clipboard.writeText(spec.script) } catch (_) {}
      copy.textContent = '✓'; setTimeout(() => { copy.textContent = '⧉' }, 1000)
    })
    row.appendChild(lbl); row.appendChild(code); row.appendChild(copy)
    panel.appendChild(row)
  }

  // 注入对象 + 内置函数
  if (spec.injects && spec.injects.length) {
    panel.appendChild(section(t('graph.help.injects')))
    const { table, tbody } = makeTable([t('graph.help.name'), t('graph.help.description')])
    for (const o of spec.injects) addRow(tbody, [codeCell(o.name), o.desc])
    panel.appendChild(table)
  }
  if (spec.functions && spec.functions.length) {
    panel.appendChild(section(t('graph.help.functions')))
    const { table, tbody } = makeTable([t('graph.help.function'), t('graph.help.description')])
    for (const f of spec.functions) addRow(tbody, [codeCell(f.sig), f.desc])
    panel.appendChild(table)
  }

  const ports = (list, label) => {
    if (!list || !list.length) return
    panel.appendChild(section(label))
    const { table, tbody } = makeTable([
      t('graph.help.name'), t('graph.help.type'), t('graph.help.connection'), t('graph.help.description'),
    ])
    for (const p of list) addRow(tbody, [p.name, typeTag(p.type, colors), conn(p), p.desc])
    panel.appendChild(table)
  }
  ports(spec.inputs, t('graph.help.inputs'))
  ports(spec.outputs, t('graph.help.outputs'))

  if (spec.properties && spec.properties.length) {
    panel.appendChild(section(t('graph.help.properties')))
    const { table, tbody } = makeTable([
      t('graph.help.name'), t('graph.help.type'), t('graph.help.defaultValue'), t('graph.help.description'),
    ])
    for (const pr of spec.properties) {
      const def = pr.default === '' || pr.default == null ? t('graph.help.empty') : String(pr.default)
      addRow(tbody, [pr.name, pr.type, def, pr.desc])
    }
    panel.appendChild(table)
  }

  mask.appendChild(panel)
  document.body.appendChild(mask)
}
