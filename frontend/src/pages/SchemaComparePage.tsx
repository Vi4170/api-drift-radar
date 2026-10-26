import { useState } from 'react'
import { Link, useParams } from 'react-router'
import { useAcceptBaseline, useBaselines, useEndpoint, useSchemaView } from '../api/hooks'
import type { SchemaView } from '../api/types'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { SchemaDiffTable, SchemaPanel } from '../components/schema'
import { ErrorMessage, SeverityBadge, Spinner } from '../components/ui'
import { formatDateTime } from '../utils/format'

export function SchemaComparePage() {
  const { id = '' } = useParams()
  const endpoint = useEndpoint(id)
  const view = useSchemaView(id)
  const baselines = useBaselines(id)

  if (view.isPending || endpoint.isPending) return <Spinner />
  if (view.error || endpoint.error) return <ErrorMessage error={view.error ?? endpoint.error} />
  const v = view.data

  return (
    <>
      <div className="page-header">
        <div>
          <p className="breadcrumb">
            <Link to="/endpoints">Endpoints</Link> / <Link to={`/endpoints/${id}`}>{endpoint.data.name}</Link> /
          </p>
          <h1>Schema comparison</h1>
          <p className="muted">Approved baseline versus the most recently observed response structure.</p>
        </div>
      </div>

      <AcceptBaseline endpointId={id} view={v} />

      <section className="card">
        <div className="section-header">
          <h2>Differences</h2>
          {v.max_severity && <SeverityBadge severity={v.max_severity} />}
        </div>
        {!v.baseline ? (
          <p className="muted">No baseline yet — run a check that returns JSON to create one.</p>
        ) : !v.comparison_available ? (
          <p className="muted">
            Comparison unavailable: a schema document could not be loaded from the document store.
          </p>
        ) : (
          <SchemaDiffTable changes={v.changes} />
        )}
      </section>

      <div className="two-col">
        <SchemaPanel
          title={v.baseline ? `Approved baseline v${v.baseline.version}` : 'Approved baseline'}
          schema={v.baseline?.json_schema ?? null}
          changes={v.changes}
          empty="No approved baseline."
        />
        <SchemaPanel
          title={`Latest observed${v.latest_checked_at ? ` · ${formatDateTime(v.latest_checked_at)}` : ''}`}
          schema={v.latest_schema}
          changes={v.changes}
          empty="No schema observed yet."
        />
      </div>

      <section className="card table-card">
        <h2>Baseline history</h2>
        {baselines.isPending ? (
          <Spinner />
        ) : baselines.error ? (
          <ErrorMessage error={baselines.error} />
        ) : baselines.data.length === 0 ? (
          <p className="muted">No baselines yet.</p>
        ) : (
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Version</th>
                  <th scope="col">Approved</th>
                  <th scope="col">How</th>
                  <th scope="col">Replaced</th>
                  <th scope="col">Schema hash</th>
                </tr>
              </thead>
              <tbody>
                {baselines.data.map((b) => (
                  <tr key={b.id}>
                    <td>
                      v{b.version} {b.is_current && <span className="tag tag-ok">current</span>}
                    </td>
                    <td>{formatDateTime(b.approved_at)}</td>
                    <td>{b.approved_by_id ? 'accepted by you' : 'first response (automatic)'}</td>
                    <td>{formatDateTime(b.replaced_at)}</td>
                    <td className="mono">{b.schema_hash.slice(0, 12)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </>
  )
}

export function AcceptBaseline({ endpointId, view }: { endpointId: string; view: SchemaView }) {
  const accept = useAcceptBaseline(endpointId)
  const [open, setOpen] = useState(false)
  const [done, setDone] = useState<number | null>(null)
  const differs =
    !!view.baseline && view.latest_schema_hash !== null && view.latest_schema_hash !== view.baseline.schema_hash
  if (!differs && done === null) return null

  return (
    <section className="card callout" aria-live="polite">
      {done !== null ? (
        <p>
          <strong>Baseline v{done} accepted.</strong> Future checks are compared against it.
        </p>
      ) : (
        <>
          <div>
            <h2>The latest response differs from the approved baseline</h2>
            <p className="muted">
              The baseline stays unchanged until you explicitly accept the new structure.
              {!view.latest_is_json && ' The latest response is not JSON, so it cannot become a baseline.'}
            </p>
          </div>
          <button
            className="btn btn-primary"
            disabled={!view.latest_is_json || !view.latest_check_id}
            onClick={() => setOpen(true)}
          >
            Accept as new baseline…
          </button>
        </>
      )}
      <ConfirmDialog
        open={open}
        title="Accept the latest schema as the new baseline?"
        confirmLabel={`Accept as v${(view.baseline?.version ?? 0) + 1}`}
        busy={accept.isPending}
        onCancel={() => setOpen(false)}
        onConfirm={() =>
          accept.mutate(view.latest_check_id!, {
            onSuccess: (b) => {
              setOpen(false)
              setDone(b.version)
            },
          })
        }
      >
        <p>
          Baseline v{view.baseline?.version} will be retired and kept in history. The open drift incident will be
          resolved as <em>baseline accepted</em>.
        </p>
        <p>
          <strong>{view.changes.length}</strong> change{view.changes.length === 1 ? '' : 's'} will become the new normal
          {view.max_severity === 'critical' && ', including critical (potentially breaking) changes'}.
        </p>
        {accept.error && <ErrorMessage error={accept.error} title="Could not accept baseline" />}
      </ConfirmDialog>
    </section>
  )
}
