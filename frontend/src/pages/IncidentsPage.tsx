import { Link, useSearchParams } from 'react-router'
import { useIncidents } from '../api/hooks'
import { EmptyState, ErrorMessage, Pagination, SeverityBadge, Spinner, StatusPill } from '../components/ui'
import { formatDateTime, humanize } from '../utils/format'

const PAGE_SIZE = 20

export function IncidentsPage() {
  // Filters live in the URL so a filtered view can be linked and survives reloads.
  const [params, setParams] = useSearchParams({ status: 'open' })
  const filters = {
    status: params.get('status') ?? '',
    severity: params.get('severity') ?? '',
    type: params.get('type') ?? '',
    endpoint_id: params.get('endpoint_id') ?? '',
    page: Number(params.get('page') ?? 1),
    page_size: PAGE_SIZE,
  }
  const { data, isPending, error } = useIncidents(filters)

  const setFilter = (key: string, value: string) => {
    const next = new URLSearchParams(params)
    next.set(key, value)
    next.delete('page')
    setParams(next)
  }

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Incidents</h1>
          <p className="muted">
            Schema drift and availability problems. Repeated observations are grouped into one incident.
          </p>
        </div>
      </div>

      <div className="toolbar">
        <label>
          <span className="sr-only">Status</span>
          <select aria-label="Status" value={filters.status} onChange={(e) => setFilter('status', e.target.value)}>
            <option value="">All statuses</option>
            <option value="open">Open</option>
            <option value="resolved">Resolved</option>
          </select>
        </label>
        <label>
          <span className="sr-only">Severity</span>
          <select
            aria-label="Severity"
            value={filters.severity}
            onChange={(e) => setFilter('severity', e.target.value)}
          >
            <option value="">All severities</option>
            <option value="critical">Critical</option>
            <option value="warning">Warning</option>
            <option value="info">Info</option>
          </select>
        </label>
        <label>
          <span className="sr-only">Type</span>
          <select aria-label="Type" value={filters.type} onChange={(e) => setFilter('type', e.target.value)}>
            <option value="">All types</option>
            <option value="schema_drift">Schema drift</option>
            <option value="availability">Availability</option>
          </select>
        </label>
        {filters.endpoint_id && (
          <button className="btn btn-ghost btn-sm" onClick={() => setFilter('endpoint_id', '')}>
            Clear endpoint filter ✕
          </button>
        )}
      </div>

      {isPending ? (
        <Spinner />
      ) : error ? (
        <ErrorMessage error={error} title="Could not load incidents" />
      ) : data.items.length === 0 ? (
        <EmptyState title="No incidents match these filters" />
      ) : (
        <div className="card table-card">
          <div className="table-wrap">
            <table className="table">
              <thead>
                <tr>
                  <th scope="col">Severity</th>
                  <th scope="col">Incident</th>
                  <th scope="col">Endpoint</th>
                  <th scope="col">First seen</th>
                  <th scope="col">Last seen</th>
                  <th scope="col">Seen</th>
                  <th scope="col">Status</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((i) => (
                  <tr key={i.id}>
                    <td>
                      <SeverityBadge severity={i.severity} />
                    </td>
                    <td>
                      <Link to={`/incidents/${i.id}`} className="cell-title">
                        {humanize(i.type)}
                      </Link>
                      <span className="cell-sub">{i.summary}</span>
                    </td>
                    <td>
                      <Link to={`/endpoints/${i.endpoint_id}`}>{i.endpoint_name}</Link>
                    </td>
                    <td>{formatDateTime(i.first_seen_at)}</td>
                    <td>{formatDateTime(i.last_seen_at)}</td>
                    <td>{i.occurrence_count}×</td>
                    <td>
                      <StatusPill open={i.status === 'open'} />
                      {i.resolution && <span className="cell-sub">{humanize(i.resolution)}</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <Pagination
            page={data.page}
            pageSize={data.page_size}
            total={data.total}
            onChange={(page) => {
              const next = new URLSearchParams(params)
              next.set('page', String(page))
              setParams(next)
            }}
          />
        </div>
      )}
    </>
  )
}
