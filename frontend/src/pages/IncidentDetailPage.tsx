import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { useIncident, useResolveIncident } from '../api/hooks'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { SchemaDiffTable } from '../components/schema'
import { ErrorMessage, SeverityBadge, Spinner, StatusPill } from '../components/ui'
import { formatDateTime, humanize } from '../utils/format'

export function IncidentDetailPage() {
  const { id = '' } = useParams()
  const incident = useIncident(id)
  const resolve = useResolveIncident(id)
  const [open, setOpen] = useState(false)
  const [note, setNote] = useState('')

  if (incident.isPending) return <Spinner />
  if (incident.error) return <ErrorMessage error={incident.error} title="Could not load incident" />
  const i = incident.data
  const isOpen = i.status === 'open'

  return (
    <>
      <div className="page-header">
        <div>
          <p className="breadcrumb">
            <Link to="/incidents">Incidents</Link> /
          </p>
          <h1>{i.title}</h1>
          <p className="badges">
            <SeverityBadge severity={i.severity} /> <StatusPill open={isOpen} />{' '}
            <span className="tag">{humanize(i.type)}</span>
          </p>
        </div>
        <div className="actions">
          {isOpen && i.type === 'schema_drift' && (
            <Link className="btn btn-primary" to={`/endpoints/${i.endpoint_id}/schema`}>
              Review & accept schema…
            </Link>
          )}
          {isOpen && (
            <button className="btn btn-ghost" onClick={() => setOpen(true)}>
              Resolve manually
            </button>
          )}
        </div>
      </div>

      <section className="card">
        <dl className="kv">
          <dt>Endpoint</dt>
          <dd>
            <Link to={`/endpoints/${i.endpoint_id}`}>{i.endpoint_name}</Link>
          </dd>
          <dt>First seen</dt>
          <dd>{formatDateTime(i.first_seen_at)}</dd>
          <dt>Last seen</dt>
          <dd>{formatDateTime(i.last_seen_at)}</dd>
          <dt>Observed</dt>
          <dd>{i.occurrence_count} time(s)</dd>
          {i.resolved_at && (
            <>
              <dt>Resolved</dt>
              <dd>
                {formatDateTime(i.resolved_at)} · {humanize(i.resolution)}
              </dd>
            </>
          )}
          <dt>Summary</dt>
          <dd>{i.summary}</dd>
        </dl>
      </section>

      {i.type === 'schema_drift' && (
        <section className="card">
          <h2>Schema changes</h2>
          {i.changes_available ? (
            <SchemaDiffTable changes={i.changes} />
          ) : (
            <p className="muted">Detailed change records are unavailable (document store unreachable or not stored).</p>
          )}
        </section>
      )}

      <section className="card">
        <h2>History</h2>
        <ol className="timeline">
          {i.events.map((e) => (
            <li key={e.id}>
              <time dateTime={e.created_at}>{formatDateTime(e.created_at)}</time>
              <strong>{humanize(e.event_type)}</strong>
              <span>{e.message}</span>
            </li>
          ))}
        </ol>
      </section>

      <ConfirmDialog
        open={open}
        title="Resolve this incident?"
        confirmLabel="Resolve incident"
        busy={resolve.isPending}
        onCancel={() => setOpen(false)}
        onConfirm={() => resolve.mutate(note, { onSuccess: () => setOpen(false) })}
      >
        <p>
          {i.type === 'schema_drift'
            ? 'The approved baseline is not changed. If the drift is still present, the next check opens a new incident — accept the new schema instead if this change is expected.'
            : 'If the endpoint is still failing, the next check opens a new incident.'}
        </p>
        <label className="field">
          <span>Resolution note (optional)</span>
          <textarea value={note} maxLength={500} rows={3} onChange={(e) => setNote(e.target.value)} />
        </label>
        {resolve.error && <ErrorMessage error={resolve.error} />}
      </ConfirmDialog>
    </>
  )
}
