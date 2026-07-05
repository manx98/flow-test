// 代码补全：优先后端 JS 语义补全（/api/complete），失败回退本地静态候选。
// 用法：attachCompletion(textarea, onChange) —— onChange 在补全插入后调用以同步外部状态。
import { api } from '../api.js'

const PC = ['click', 'type', 'hotkey', 'findImage', 'findAll', 'findText', 'ocr', 'wait', 'log']
const DEVICE = ['click', 'type', 'hotkey', 'capture']
const FLOW = ['image', 'find_image', 'find_text', 'find_all', 'wait_appear', 'wait_vanish',
  'to_point', 'click', 'type_text', 'scroll', 'drag', 'delay', 'log', 'alert', 'get_var', 'set_var']
const VARS = ['get', 'set', 'keys']
const JSON_MEMBERS = ['parse', 'stringify']
const MATH = ['abs', 'ceil', 'floor', 'max', 'min', 'round', 'random']
const MEMBERS = { pc: PC, device: DEVICE, flow: FLOW, vars: VARS, JSON: JSON_MEMBERS, Math: MATH }
const GLOBALS = ['getArg', 'setResult', 'log', 'flow', 'vars', 'device', 'JSON', 'Math',
  'Array', 'Object', 'String', 'Number', 'Boolean', 'Date', 'RegExp', 'Error']
const KEYWORDS = ['break', 'case', 'catch', 'class', 'const', 'continue', 'default', 'do', 'else',
  'false', 'finally', 'for', 'function', 'if', 'let', 'new', 'null', 'return', 'switch', 'throw',
  'true', 'try', 'undefined', 'var', 'while']
const BUILTINS = ['parseInt', 'parseFloat', 'isFinite', 'isNaN', 'console']

const uniq = (a) => [...new Set(a)]
const bufferWords = (t) => uniq((t.match(/[A-Za-z_]\w{1,}/g) || []))

// 光标处正在输入的标识符前缀
const currentWord = (ta) => (/([A-Za-z_]\w*)?$/.exec(ta.value.slice(0, ta.selectionStart))[1]) || ''

// 光标的行列：line 1 基、column 0 基
function lineCol(ta) {
  const left = ta.value.slice(0, ta.selectionStart)
  const lines = left.split('\n')
  return { line: lines.length, column: lines[lines.length - 1].length }
}

// 何时触发补全：正在打标识符，或刚输入成员访问的点
function shouldOpen(ta) {
  const left = ta.value.slice(0, ta.selectionStart)
  return /[A-Za-z_]\w*$/.test(left) || /[A-Za-z_]\w*\.\s*$/.test(left)
}

// 当前光标处的候选词列表 + 正在输入的前缀
function candidates(text, pos) {
  const left = text.slice(0, pos)
  const word = (/([A-Za-z_]\w*)?$/.exec(left)[1]) || ''
  const before = left.slice(0, left.length - word.length)
  const mm = /([A-Za-z_]\w*)\.\s*$/.exec(before)
  let pool, memberAccess = false
  if (mm) {
    memberAccess = true
    pool = MEMBERS[mm[1]] || []        // 已知对象给成员，未知对象不提示
  } else {
    pool = [...GLOBALS, ...KEYWORDS, ...BUILTINS, ...bufferWords(text)]
  }
  if (!memberAccess && word.length < 1) return { word, list: [] }
  const list = uniq(pool).filter(w => w.startsWith(word)).sort().slice(0, 12)
  return { word, list }
}

// 估算 textarea 光标的屏幕坐标（镜像 div 测量）
function caretXY(ta) {
  const cs = getComputedStyle(ta)
  const div = document.createElement('div')
  for (const p of ['fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'letterSpacing',
    'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'borderTopWidth',
    'borderLeftWidth', 'boxSizing', 'whiteSpace', 'tabSize', 'wordSpacing']) div.style[p] = cs[p]
  Object.assign(div.style, { position: 'fixed', visibility: 'hidden', width: ta.clientWidth + 'px' })
  div.textContent = ta.value.slice(0, ta.selectionStart)
  const span = document.createElement('span'); span.textContent = '​'
  div.appendChild(span); document.body.appendChild(div)
  const r = ta.getBoundingClientRect()
  const x = r.left + span.offsetLeft - ta.scrollLeft
  const y = r.top + span.offsetTop - ta.scrollTop
  div.remove()
  return { x, y, lh: parseFloat(cs.lineHeight) || parseFloat(cs.fontSize) * 1.3 }
}

export function attachCompletion(ta, onChange) {
  const box = document.createElement('div')
  Object.assign(box.style, {
    position: 'fixed', zIndex: 1000, display: 'none', minWidth: '120px', maxHeight: '180px',
    overflow: 'auto', background: '#1b1b1b', border: '1px solid #444', borderRadius: '4px',
    font: '12px monospace', color: '#ddd', boxShadow: '0 4px 12px rgba(0,0,0,.5)',
  })
  document.body.appendChild(box)
  let items = [], active = 0, curWord = ''
  let reqSeq = 0, timer = null

  const close = () => { box.style.display = 'none'; items = [] }
  // 唯一候选就是已输入的词时无意义（提示栏只会重复你刚打的字），不弹
  const useful = (list) => list.length > 0 && !(list.length === 1 && list[0] === curWord)

  const show = (list) => {
    if (!list.length) return close()
    items = list; active = 0
    box.innerHTML = ''
    list.forEach((w, i) => {
      const it = document.createElement('div')
      it.textContent = w
      Object.assign(it.style, { padding: '2px 8px', cursor: 'pointer', whiteSpace: 'nowrap' })
      it.addEventListener('mousedown', (ev) => { ev.preventDefault(); accept(i) })
      box.appendChild(it)
    })
    const { x, y, lh } = caretXY(ta)
    box.style.left = x + 'px'; box.style.top = (y + lh) + 'px'
    box.style.display = 'block'
    paint()
  }

  // 先用本地基础候选即时显示（关键字/内置/全局/缓冲区词），再用后端语义结果增强
  const query = async () => {
    if (!shouldOpen(ta)) return close()
    curWord = currentWord(ta)
    const code = ta.value, pos = ta.selectionStart
    const local = candidates(code, pos).list
    if (useful(local)) show(local)               // 立即反馈，基础语法永不缺失
    const { line, column } = lineCol(ta)
    const seq = ++reqSeq
    try {
      const comps = await api.complete(code, line, column)
      if (seq !== reqSeq) return                 // 过期响应丢弃
      const names = comps.map(c => c.name)       // 保留精确匹配（如 import os 的 os）
      const merged = uniq([...names, ...local])  // 后端语义 + 本地基础
      if (useful(merged)) show(merged)
      else close()
    } catch (_) {
      if (!local.length) close()                 // 后端失败且本地无候选才关闭
    }
  }

  const open = () => { clearTimeout(timer); timer = setTimeout(query, 120) }
  const paint = () => {
    ;[...box.children].forEach((c, i) => { c.style.background = i === active ? '#2d4a6b' : 'transparent' })
    box.children[active]?.scrollIntoView({ block: 'nearest' })
  }
  const accept = (i) => {
    const w = items[i]
    const pos = ta.selectionStart
    const start = pos - curWord.length
    ta.value = ta.value.slice(0, start) + w + ta.value.slice(pos)
    ta.selectionStart = ta.selectionEnd = start + w.length
    close()
    onChange && onChange()
  }

  // 捕获阶段抢先处理导航键，阻止冒泡到节点的 Tab/拖动等
  ta.addEventListener('keydown', (ev) => {
    if (box.style.display === 'none') return
    if (ev.key === 'ArrowDown') { ev.preventDefault(); ev.stopImmediatePropagation(); active = (active + 1) % items.length; paint() }
    else if (ev.key === 'ArrowUp') { ev.preventDefault(); ev.stopImmediatePropagation(); active = (active - 1 + items.length) % items.length; paint() }
    else if (ev.key === 'Enter' || ev.key === 'Tab') { ev.preventDefault(); ev.stopImmediatePropagation(); accept(active) }
    else if (ev.key === 'Escape') { ev.preventDefault(); ev.stopImmediatePropagation(); close() }
  }, true)

  ta.addEventListener('input', open)
  ta.addEventListener('blur', () => setTimeout(close, 120))

  return () => { try { box.remove() } catch (_) {} }   // 销毁：移除下拉框
}
