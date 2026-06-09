import { LiteGraph } from 'litegraph.js'
import { t } from '../i18n.js'

function translateText(text) {
  const key = String(text || '').trim()
  return t(`litegraph.menu.${key}`, null)
}

function translateHtml(html) {
  const text = String(html || '').replace(/<[^>]+>/g, '').trim()
  const translated = translateText(text)
  return translated ? String(html).replace(text, translated) : null
}

export function installLiteGraphI18n() {
  const OriginalContextMenu = LiteGraph.ContextMenu
  if (!OriginalContextMenu?.prototype || OriginalContextMenu.prototype._flowTestI18n) return

  function LocalizedContextMenu(values, options = {}, refWindow) {
    const nextOptions = { ...options }
    const translatedTitle = translateText(nextOptions.title)
    if (translatedTitle) nextOptions.title = translatedTitle
    return Reflect.construct(OriginalContextMenu, [values, nextOptions, refWindow], OriginalContextMenu)
  }
  Object.setPrototypeOf(LocalizedContextMenu, OriginalContextMenu)
  LocalizedContextMenu.prototype = OriginalContextMenu.prototype

  const addItem = OriginalContextMenu.prototype.addItem
  OriginalContextMenu.prototype.addItem = function (name, value, options) {
    const element = addItem.call(this, name, value, options)
    if (!element || element.classList?.contains('separator')) return element

    const shown = value?.title ?? name
    const translated = translateHtml(shown)
    if (translated) element.innerHTML = translated
    return element
  }

  OriginalContextMenu.prototype._flowTestI18n = true
  LiteGraph.ContextMenu = LocalizedContextMenu
}
