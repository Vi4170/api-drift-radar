import { useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { ApiError } from '../api/client'
import {
  useChecks,
  useDeleteEndpoint,
  useEndpoint,
  useIncidents,
  useMetrics,
  useRunCheck,
  useSchemaView,
  useUpdateEndpoint,
} from '../api/hooks'
import type { CheckResult } from '../api/types'
import { LatencyChart } from '../components/charts'
import { ConfirmDialog } from '../components/ConfirmDialog'
import { SchemaDiffTable } from '../components/schema'
import {
  EmptyState,
  ErrorMessage,
  HealthBadge,
  Pagination,
  SchemaBadge,
  SeverityBadge,
  Spinner,
  StatCard,
} from '../components/ui'
import {
  formatDateTime,
  formatInterval,
  formatMs,
  formatPercent,
  humanize,
  plural,
  relativeTime,
} from '../utils/format'

export function EndpointDetailPage() {
  const { id = '' } = useParams()
  const navigate = useNavigate()
  const endpoint = useEndpoint(id)
  const schema = useSchemaView(id)
  const [hours, setHours] = useState(24)
  const metrics = useMetrics(id, hours)
  const [historyPage, setHistoryPage] = useState(1)
  const checks = useChecks(id, historyPage)
  const incidents = useIncidents({ endpoint_id: id, status: 'open', page_size: 10 })
  const runCheck = useRunCheck(id)
  const update = useUpdateEndpoint(id)
  const remove = useDeleteEndpoint()
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [lastResult, setLastResult] = useState<CheckResult | null>(null)

  if (endpoint.isPending) return <Spinner />
  if (endpoint.error) {
    return endpoint.error instanceof ApiError && endpoint.error.status === 404 ? (
      <EmptyState title="Endpoint not found">
        <Link to="/endpoints">Back to endpoints</Link>
      </EmptyState>
    ) : (
      <ErrorMessage error={endpoint.error} />
    )
  }
  const ep = endpoint.data

  const onRunCheck = () => {
    setLastResult(null)
    runCheck.mutate(undefined, { onSuccess: setLastResult })
  }

  return (
    <>
      <div className="page-header">
        <div>
          <p className="breadcrumb">
            <Link to="/endpoints">Endpoints</Link> /
          </p>
          <h1>
            {ep.name} {!ep.is_active && <span className="tag">paused</span>}
          </h1>
          <p className="mono muted break">
            {ep.method} {ep.url}
          </p>
        </div>
        <div className="actions">
          <button className="btn btn-primary" onClick={onRunCheck} disabled={runCheck.isPending}>
            {runCheck.isPending ? 'Checking…' : 'Run check now'}
          </button>
          <button
            className="btn btn-ghost"
            disabled={update.isPending}
            onClick={() => update.mutate({ is_active: !ep.is_active })}
          >
            {ep.is_active ? 'Pause monitoring' : 'Resume monitoring'}
          </button>
          <Link className="btn btn-ghost" to={`/endpoints/${ep.id}/edit`}>
            Edit
          </Link>
          <button className="btn btn-danger-ghost" onClick={() => setConfirmDelete(true)}>
            Delete
          </button>
        </div>
      </div>

      {runCheck.error && <ErrorMessage error={runCheck.error} title="Check could not run" />}
      {update.error && <ErrorMessage error={update.error} title="Could not update monitoring" />}
      {lastResult && (
        <div className={`alert ${lastResult.is_healthy ? 'alert-success' : 'alert-error'}`} role="status">
          <strong>Check finished: {humanize(lastResult.outcome)}</strong>
          <span>
            HTTP {lastResult.status_code ?? '—'} in {formatMs(lastResult.latency_ms)} · schema{' '}
            {humanize(lastResult.schema_status)}
            {lastResult.error_message ? ` · ${lastResult.error_message}` : ''}
          </span>
        </div>
      )}

      <div className="stats-grid">
        <StatCard
          label="Health"
          value={<HealthBadge status={ep.health_status} />}
          hint={`Last check ${relativeTime(ep.last_checked_at)}`}
        />
        <StatCard
          label="Schema"
          value={<SchemaBadge status={ep.schema_status} />}
          hint={ep.baseline_version ? `Baseline v${ep.baseline_version}` : 'No baseline yet'}
        />
        <StatCard label="Last response" value={ep.last_status_code ?? '—'} hint={humanize(ep.last_outcome)} />
        <StatCard
          label="Latency"
          value={formatMs(ep.last_latency_ms)}
          hint={`p95 ${formatMs(metrics.data?.p95_latency_ms)}`}
        />
        <StatCard
          label={`Availability (${hours}h)`}
          value={formatPercent(metrics.data?.availability_percent)}
          hint={plural(metrics.data?.total_checks ?? 0, 'check')}
        />
      </div>

      <div className="two-col">
        <section className="card">
          <h2>Configuration</h2>
          <dl className="kv">
            <dt>Expected status</dt>
            <dd>{ep.expected_status}</dd>
            <dt>Interval</dt>
            <dd>every {formatInterval(ep.interval_seconds)}</dd>
            <dt>Timeout</dt>
            <dd>{ep.timeout_seconds}s</dd>
            <dt>Scheduled monitoring</dt>
            <dd>{ep.is_active ? 'active' : 'paused'}</dd>
            <dt>Custom headers</dt>
            <dd>{Object.keys(ep.headers).length ? Object.keys(ep.headers).join(', ') : 'none'}</dd>
            <dt>Created</dt>
            <dd>{formatDateTime(ep.created_at)}</dd>
          </dl>
        </section>

        <section className="card">
          <div className="section-header">
            <h2>Open incidents</h2>
            <Link to={`/incidents?endpoint_id=${ep.id}`}>History</Link>
          </div>
          {incidents.isPending ? (
            <Spinner />
          ) : incidents.error ? (
            <ErrorMessage error={incidents.error} />
          ) : incidents.data.items.length === 0 ? (
            <p className="muted">No open incidents.</p>
          ) : (
            <ul className="list">
              {incidents.data.items.map((i) => (
                <li key={i.id}>
                  <Link className="list-link" to={`/incidents/${i.id}`}>
                    <SeverityBadge severity={i.severity} />
                    <span className="list-main">
                      <strong>{i.title}</strong>
                      <span className="muted">
                        seen {i.occurrence_count}× · since {relativeTime(i.first_seen_at)}
                      </span>
                    </span>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <section className="card">
        <div className="section-header">
          <h2>Schema</h2>
          <Link className="btn btn-ghost btn-sm" to={`/endpoints/${ep.id}/schema`}>
            Compare schemas & manage baseline →
          </Link>
        </div>
        {schema.isPending ? (
          <Spinner />
        ) : schema.error ? (
          <ErrorMessage error={schema.error} />
        ) : !schema.data.baseline ? (
          <p className="muted">
            No approved baseline yet. The first successful JSON response becomes baseline v1 automatically.
          </p>
        ) : (
          <>
            <dl className="kv kv-inline">
              <dt>Approved baseline</dt>
              <dd>
                v{schema.data.baseline.version} ·{' '}
                {schema.data.baseline.approved_by_id ? 'accepted manually' : 'initial'} ·{' '}
                {formatDateTime(schema.data.baseline.approved_at)}
              </dd>
              <dt>Latest observed schema</dt>
              <dd className="mono">
                {schema.data.latest_schema_hash?.slice(0, 12) ?? '—'} · {formatDateTime(schema.data.latest_checked_at)}
              </dd>
            </dl>
            {schema.data.comparison_available ? (
              <SchemaDiffTable changes={schema.data.changes} />
            ) : (
              <p className="muted">Schema comparison unavailable (schema documents could not be loaded).</p>
            )}
          </>
        )}
      </section>

      <section className="card">
        <div className="section-header">
          <h2>Response time</h2>
          <label>
            <span className="sr-only">Time window</span>
            <select value={hours} onChange={(e) => setHours(Number(e.target.value))}>
              <option value={1}>Last hour</option>
              <option value={24}>Last 24 hours</option>
              <option value={168}>Last 7 days</option>
              <option value={720}>Last 30 days</option>
            </select>
          </label>
        </div>
        {metrics.isPending ? (
          <Spinner />
        ) : metrics.error ? (
          <ErrorMessage error={metrics.error} />
        ) : (
          <LatencyChart
            label={`Latency of ${ep.name}`}
            data={metrics.data.series.map((p) => ({ time: p.checked_at, latency: p.latency_ms }))}
          />
        )}
      </section>

      <section className="card table-card">
        <h2>Check history</h2>
        {checks.isPending ? (
          <Spinner />
        ) : checks.error ? (
          <ErrorMessage error={checks.error} />
        ) : checks.data.items.length === 0 ? (
          <p className="muted">No checks yet. Use “Run check now” or wait for the scheduler.</p>
        ) : (
          <>
            <div className="table-wrap">
              <table className="table">
                <thead>
                  <tr>
                    <th scope="col">Time</th>
                    <th scope="col">Trigger</th>
                    <th scope="col">Outcome</th>
                    <th scope="col">Status</th>
                    <th scope="col">Latency</th>
                    <th scope="col">Size</th>
                    <th scope="col">Schema</th>
                  </tr>
                </thead>
                <tbody>
                  {checks.data.items.map((c) => (
                    <tr key={c.id}>
                      <td title={c.checked_at}>{formatDateTime(c.checked_at)}</td>
                      <td>{c.trigger}</td>
                      <td>
                        <HealthBadge status={c.is_healthy ? 'healthy' : 'unhealthy'} /> {humanize(c.outcome)}
                        {c.error_message && <span className="cell-sub">{c.error_message}</span>}
                      </td>
                      <td>{c.status_code ?? '—'}</td>
                      <td>{formatMs(c.latency_ms)}</td>
                      <td>{c.response_size_bytes !== null ? `${c.response_size_bytes} B` : '—'}</td>
                      <td>
                        <SchemaBadge status={c.schema_status} />
                        {c.drift_severity && <SeverityBadge severity={c.drift_severity} />}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <Pagination page={historyPage} pageSize={10} total={checks.data.total} onChange={setHistoryPage} />
          </>
        )}
      </section>

      <ConfirmDialog
        open={confirmDelete}
        title={`Delete ${ep.name}?`}
        confirmLabel="Delete endpoint"
        tone="danger"
        busy={remove.isPending}
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => remove.mutate(ep.id, { onSuccess: () => navigate('/endpoints', { replace: true }) })}
      >
        <p>This permanently removes the endpoint, its check history, baselines, incidents and stored snapshots.</p>
        {remove.error && <ErrorMessage error={remove.error} />}
      </ConfirmDialog>
    </>
  )
}
