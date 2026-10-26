import type { ReactNode } from 'react'
import { ApiError } from '../api/client'
import type { HealthStatus, SchemaStatus, Severity } from '../api/types'
import { humanize } from '../utils/format'

export function Spinner({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="loading" role="status" aria-live="polite">
      <span className="spinner" aria-hidden="true" />
      <span>{label}</span>
    </div>
  )
}

export function ErrorMessage({ error, title = 'Something went wrong' }: { error: unknown; title?: string }) {
  const message = error instanceof ApiError || error instanceof Error ? error.message : String(error)
  return (
    <div className="alert alert-error" role="alert">
      <strong>{title}</strong>
      <span>{message}</span>
    </div>
  )
}

export function EmptyState({ title, children }: { title: string; children?: ReactNode }) {
  return (
    <div className="empty">
      <p className="empty-title">{title}</p>
      {children}
    </div>
  )
}

const HEALTH_TONE: Record<HealthStatus, string> = { healthy: 'ok', unhealthy: 'bad', unknown: 'muted' }
const SCHEMA_TONE: Record<SchemaStatus, string> = {
  compatible: 'ok',
  baseline_created: 'ok',
  drifted: 'warn',
  unavailable: 'muted',
  not_applicable: 'muted',
  unknown: 'muted',
}
const SEVERITY_TONE: Record<Severity, string> = { info: 'info', warning: 'warn', critical: 'bad' }

function Badge({ tone, children, label }: { tone: string; children: ReactNode; label?: string }) {
  return (
    <span className={`badge badge-${tone}`} aria-label={label}>
      <span className="dot" aria-hidden="true" />
      {children}
    </span>
  )
}

export const HealthBadge = ({ status }: { status: HealthStatus }) => (
  <Badge tone={HEALTH_TONE[status]} label={`Health: ${status}`}>
    {status}
  </Badge>
)

export const SchemaBadge = ({ status }: { status: SchemaStatus }) => (
  <Badge tone={SCHEMA_TONE[status] ?? 'muted'} label={`Schema: ${humanize(status)}`}>
    {humanize(status)}
  </Badge>
)

export const SeverityBadge = ({ severity }: { severity: Severity }) => (
  <Badge tone={SEVERITY_TONE[severity]} label={`Severity: ${severity}`}>
    {severity}
  </Badge>
)

export const StatusPill = ({ open }: { open: boolean }) => (
  <Badge tone={open ? 'bad' : 'muted'}>{open ? 'open' : 'resolved'}</Badge>
)

export function StatCard({
  label,
  value,
  hint,
  tone,
}: {
  label: string
  value: ReactNode
  hint?: string
  tone?: string
}) {
  return (
    <div className={`card stat ${tone ? `stat-${tone}` : ''}`}>
      <span className="stat-label">{label}</span>
      <span className="stat-value">{value}</span>
      {hint && <span className="stat-hint">{hint}</span>}
    </div>
  )
}

export function Pagination({
  page,
  pageSize,
  total,
  onChange,
}: {
  page: number
  pageSize: number
  total: number
  onChange: (page: number) => void
}) {
  const pages = Math.max(1, Math.ceil(total / pageSize))
  if (total <= pageSize) return null
  return (
    <nav className="pagination" aria-label="Pagination">
      <button className="btn btn-ghost" disabled={page <= 1} onClick={() => onChange(page - 1)}>
        ← Previous
      </button>
      <span>
        Page {page} of {pages} · {total} total
      </span>
      <button className="btn btn-ghost" disabled={page >= pages} onClick={() => onChange(page + 1)}>
        Next →
      </button>
    </nav>
  )
}

export function Field({
  label,
  htmlFor,
  hint,
  error,
  children,
}: {
  label: string
  htmlFor: string
  hint?: string
  error?: string
  children: ReactNode
}) {
  return (
    <div className={`field ${error ? 'field-invalid' : ''}`}>
      <label htmlFor={htmlFor}>{label}</label>
      {children}
      {hint && !error && (
        <small id={`${htmlFor}-hint`} className="hint">
          {hint}
        </small>
      )}
      {error && (
        <small id={`${htmlFor}-error`} className="field-error" role="alert">
          {error}
        </small>
      )}
    </div>
  )
}
