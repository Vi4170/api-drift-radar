// Client-side mirrors of the API's validation rules. The API stays authoritative.
import type { EndpointInput } from '../api/types'

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/

export function validateAuth(mode: 'login' | 'register', email: string, password: string, confirm: string) {
  const errors: Record<string, string> = {}
  if (!EMAIL_RE.test(email.trim())) errors.email = 'Enter a valid email address'
  if (mode === 'register') {
    if (password.length < 10) errors.password = 'Use at least 10 characters'
    else if (password.length > 128) errors.password = 'Use at most 128 characters'
    if (confirm !== password) errors.confirm = 'Passwords do not match'
  } else if (!password) {
    errors.password = 'Enter your password'
  }
  return errors
}

export interface HeaderRow {
  name: string
  value: string
}

export interface FormValues {
  name: string
  url: string
  expected_status: string
  interval_seconds: string
  timeout_seconds: string
  is_active: boolean
  headers: HeaderRow[]
}

const HEADER_NAME = /^[A-Za-z0-9!#$%&'*+.^_`|~-]{1,64}$/
const FORBIDDEN_HEADERS = new Set([
  'host', 'content-length', 'transfer-encoding', 'connection', 'upgrade', 'te', 'trailer', 'keep-alive',
  'forwarded', 'x-real-ip', 'expect',
]) // prettier-ignore
const FORBIDDEN_PREFIXES = ['proxy-', 'x-forwarded-', 'sec-']

/** Client-side mirror of the API's validation rules (the API remains authoritative). */
export function validateEndpoint(v: FormValues): Record<string, string> {
  const errors: Record<string, string> = {}
  if (!v.name.trim()) errors.name = 'Name is required'
  else if (v.name.trim().length > 120) errors.name = 'Use at most 120 characters'
  try {
    const url = new URL(v.url.trim())
    if (!['http:', 'https:'].includes(url.protocol)) errors.url = 'Only http:// and https:// URLs are supported'
    else if (url.username || url.password) errors.url = 'Credentials in the URL are not allowed'
  } catch {
    errors.url = 'Enter a full URL, e.g. https://api.example.com/v1/users/1'
  }
  const status = Number(v.expected_status)
  if (!Number.isInteger(status) || status < 100 || status > 599)
    errors.expected_status = 'Use an HTTP status between 100 and 599'
  const interval = Number(v.interval_seconds)
  if (!Number.isInteger(interval) || interval < 30 || interval > 86400)
    errors.interval_seconds = 'Between 30 seconds and 24 hours (86400)'
  const timeout = Number(v.timeout_seconds)
  if (!Number.isFinite(timeout) || timeout < 1 || timeout > 30) errors.timeout_seconds = 'Between 1 and 30 seconds'
  const seen = new Set<string>()
  for (const h of v.headers) {
    if (!h.name && !h.value) continue
    const lower = h.name.toLowerCase()
    if (!HEADER_NAME.test(h.name)) errors.headers = `Invalid header name "${h.name}"`
    else if (FORBIDDEN_HEADERS.has(lower) || FORBIDDEN_PREFIXES.some((p) => lower.startsWith(p)))
      errors.headers = `"${h.name}" is managed by the monitor and cannot be set`
    else if (/[\r\n\0]/.test(h.value) || h.value.length > 1024) errors.headers = `Invalid value for "${h.name}"`
    else if (seen.has(lower)) errors.headers = `Duplicate header "${h.name}"`
    seen.add(lower)
  }
  if (v.headers.filter((h) => h.name).length > 20) errors.headers = 'At most 20 headers'
  return errors
}

export function toPayload(v: FormValues): EndpointInput {
  return {
    name: v.name.trim(),
    url: v.url.trim(),
    method: 'GET',
    expected_status: Number(v.expected_status),
    interval_seconds: Number(v.interval_seconds),
    timeout_seconds: Number(v.timeout_seconds),
    is_active: v.is_active,
    headers: Object.fromEntries(v.headers.filter((h) => h.name).map((h) => [h.name.trim(), h.value])),
  }
}
