// 轻量 Python 语法着色：把代码转成带内联颜色的 HTML（供高亮 <pre> 层渲染）。
const KW = new Set(['and', 'as', 'assert', 'async', 'await', 'break', 'class', 'continue',
  'def', 'del', 'elif', 'else', 'except', 'False', 'finally', 'for', 'from', 'global', 'if',
  'import', 'in', 'is', 'lambda', 'None', 'nonlocal', 'not', 'or', 'pass', 'raise', 'return',
  'True', 'try', 'while', 'with', 'yield'])
const BI = new Set(['print', 'len', 'range', 'str', 'int', 'float', 'bool', 'list', 'dict',
  'set', 'tuple', 'enumerate', 'zip', 'min', 'max', 'sum', 'abs', 'round', 'sorted', 'any',
  'all', 'open', 'isinstance', 'repr', 'type', 'super', 'object', 'self', 'dev', 'visauto',
  'inp', 'out', 'vars', 'Pattern'])

const C = {
  comment: '#6a9955', string: '#ce9178', number: '#b5cea8',
  keyword: '#c586c0', builtin: '#4ec9b0', decorator: '#dcdcaa',
}

const esc = (s) => s.replace(/[&<>]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;' }[c]))

// 匹配：注释 / 字符串(含三引号) / 数字 / 装饰器 / 标识符；其余(空白、操作符)按原文转义保留
const RE = /(#[^\n]*)|("""[\s\S]*?"""|'''[\s\S]*?'''|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|(\b\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?\b)|(@[A-Za-z_]\w*)|([A-Za-z_]\w*)/g

export function highlightPython(code) {
  let out = '', last = 0, m
  RE.lastIndex = 0
  while ((m = RE.exec(code))) {
    out += esc(code.slice(last, m.index))
    const t = m[0]
    let color = null
    if (m[1]) color = C.comment
    else if (m[2]) color = C.string
    else if (m[3]) color = C.number
    else if (m[4]) color = C.decorator
    else if (m[5]) color = KW.has(t) ? C.keyword : (BI.has(t) ? C.builtin : null)
    out += color ? `<span style="color:${color}">${esc(t)}</span>` : esc(t)
    last = m.index + t.length
  }
  out += esc(code.slice(last))
  return out
}

const JS_KW = new Set(['break', 'case', 'catch', 'class', 'const', 'continue', 'debugger',
  'default', 'delete', 'do', 'else', 'export', 'extends', 'finally', 'for', 'function',
  'if', 'import', 'in', 'instanceof', 'let', 'new', 'return', 'switch', 'throw', 'try',
  'typeof', 'var', 'void', 'while', 'with', 'yield', 'async', 'await', 'true', 'false',
  'null', 'undefined'])
const JS_BI = new Set(['Array', 'Boolean', 'Date', 'Error', 'JSON', 'Math', 'Number',
  'Object', 'RegExp', 'String', 'console', 'getArg', 'setResult', 'log'])
const JS_RE = /(\/\/[^\n]*|\/\*[\s\S]*?\*\/)|(`(?:\\.|[^`\\])*`|"(?:\\.|[^"\\\n])*"|'(?:\\.|[^'\\\n])*')|(\b\d[\d_]*\.?\d*(?:[eE][+-]?\d+)?\b)|([A-Za-z_$][\w$]*)/g

export function highlightJavaScript(code) {
  let out = '', last = 0, m
  JS_RE.lastIndex = 0
  while ((m = JS_RE.exec(code))) {
    out += esc(code.slice(last, m.index))
    const t = m[0]
    let color = null
    if (m[1]) color = C.comment
    else if (m[2]) color = C.string
    else if (m[3]) color = C.number
    else if (m[4]) color = JS_KW.has(t) ? C.keyword : (JS_BI.has(t) ? C.builtin : null)
    out += color ? `<span style="color:${color}">${esc(t)}</span>` : esc(t)
    last = m.index + t.length
  }
  out += esc(code.slice(last))
  return out
}
