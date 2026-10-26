import { Link } from 'react-router'
import { useDashboard } from '../api/hooks'
import { LatencyChart } from '../components/charts'
import {
  EmptyState,
  ErrorMessage,
  HealthBadge,
  SchemaBadge,
  SeverityBadge,
  Spinner,
  StatCard,
  StatusPill,
} from '../components/ui'
import { formatMs, formatPercent, humanize, plural, relativeTime } from '../utils/format'

export function DashboardPage() {
  const { data, isPending, error } = useDashboard()
  if (isPending) return <Spinner />
  if (error) return <ErrorMessage error={error} title="Could not load the dashboard" />

  const openTotal = Object.values(data.open_incidents_by_severity).reduce((a, b) => a + (b ?? 0), 0)

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Dashboard</h1>
          <p className="muted">Health and schema drift across your monitored APIs.</p>
        </div>
        <Link className="btn btn-primary" to="/endpoints/new">
          + Add endpoint
        </Link>
      </div>

      {data.total_endpoints === 0 ? (
        <EmptyState title="No endpoints yet">
          <p className="muted">Register an API endpoint to start tracking its health and response schema.</p>
          <Link className="btn btn-primary" to="/endpoints/new">
            Add your first endpoint
          </Link>
        </EmptyState>
      ) : (
        <>
          <div className="stats-grid">
            <StatCard
              label="Endpoints"
              value={data.total_endpoints}
              hint={`${data.active_endpoints} actively monitored`}
            />
            <StatCard
              label="Healthy"
              value={data.healthy_endpoints}
              tone="ok"
              hint={`${data.unknown_endpoints} not yet checked`}
            />
            <StatCard
              label="Unhealthy"
              value={data.unhealthy_endpoints}
              tone={data.unhealthy_endpoints ? 'bad' : undefined}
            />
            <StatCard
              label="With open drift"
              value={data.endpoints_with_open_drift}
              tone={data.endpoints_with_open_drift ? 'warn' : undefined}
              hint={`${openTotal} open incident${openTotal === 1 ? '' : 's'}`}
            />
            <StatCard
              label="Availability (24h)"
              value={formatPercent(data.availability_24h_percent)}
              hint={plural(data.checks_last_24h, 'check')}
            />
            <StatCard label="Avg latency (24h)" value={formatMs(data.avg_latency_24h_ms)} />
          </div>

          <section className="card">
            <h2>Response time · last 24 hours</h2>
            <LatencyChart
              label="Average latency per hour across all endpoints"
              data={data.latency_series.map((b) => ({ time: b.bucket_start, latency: b.avg_latency_ms }))}
            />
          </section>

          <div className="two-col">
            <section className="card">
              <div className="section-header">
                <h2>Recent incidents</h2>
                <Link to="/incidents">View all</Link>
              </div>
              {data.recent_incidents.length === 0 ? (
                <p className="muted">No incidents recorded. 🎉</p>
              ) : (
                <ul className="list">
                  {data.recent_incidents.map((i) => (
                    <li key={i.id}>
                      <Link to={`/incidents/${i.id}`} className="list-link">
                        <SeverityBadge severity={i.severity} />
                        <span className="list-main">
                          <strong>{i.endpoint_name}</strong>
                          <span className="muted">
                            {humanize(i.type)} · {relativeTime(i.last_seen_at)}
                          </span>
                        </span>
                        <StatusPill open={i.status === 'open'} />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="card">
              <h2>Recent activity</h2>
              {data.recent_checks.length === 0 ? (
                <p className="muted">No checks have run yet. Open an endpoint and run a manual check.</p>
              ) : (
                <ul className="list">
                  {data.recent_checks.map((c) => (
                    <li key={c.id}>
                      <Link to={`/endpoints/${c.endpoint_id}`} className="list-link">
                        <HealthBadge status={c.is_healthy ? 'healthy' : 'unhealthy'} />
                        <span className="list-main">
                          <strong>{c.endpoint_name}</strong>
                          <span className="muted">
                            {humanize(c.outcome)} · {c.status_code ?? '—'} · {formatMs(c.latency_ms)} · {c.trigger} ·{' '}
                            {relativeTime(c.checked_at)}
                          </span>
                        </span>
                        <SchemaBadge status={c.schema_status} />
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </>
      )}
    </>
  )
}
