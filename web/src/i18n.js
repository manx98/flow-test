import { ref } from 'vue'

import en from './locales/en.js'
import zh from './locales/zh.js'

export const languages = [
  { code: 'zh', label: '中文' },
  { code: 'en', label: 'English' },
]

const messages = { zh, en }

const savedLocale = typeof localStorage !== 'undefined' ? localStorage.getItem('flow-test-locale') : ''
export const locale = ref(messages[savedLocale] ? savedLocale : 'zh')

export function setLocale(nextLocale) {
  if (!messages[nextLocale]) return
  locale.value = nextLocale
  try { localStorage.setItem('flow-test-locale', nextLocale) } catch (_) {}
}

export function getLocale() {
  return locale.value
}

export function t(path, fallback = '') {
  const parts = String(path || '').split('.')
  let cur = messages[locale.value]
  for (const part of parts) {
    if (!cur || typeof cur !== 'object' || !(part in cur)) return fallback
    cur = cur[part]
  }
  return typeof cur === 'string' ? cur : fallback
}

export function tr(path, vars = {}, fallback = '') {
  return t(path, fallback).replace(/\{(\w+)\}/g, (_, key) => vars[key] ?? '')
}

export function te(path) {
  return t(path, null) != null
}
