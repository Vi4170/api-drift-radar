import { useState } from 'react'
import { Link, useNavigate } from 'react-router'
import { useEndpoints, type EndpointFilters } from '../api/hooks'
import { EmptyState, ErrorMessage, HealthBadge, Pagination, SchemaBadge, Spinner } from '../components/ui'
import { formatMs, relativeTime } from '../utils/format'

const PAGE_SIZE = 20

export function EndpointsPage() {
  const navigate = useNavigate()
  const [filters, setFilters] = useState<EndpointFilters>({ page: 1, page_size: PAGE_SIZE })
  const { data, isPending, error, isFetching } = useEndpoints(filters)
  const update = (patch: Partial<EndpointFilters>) => setFilters((f) => ({ ...f, page: 1, ...patch }))
  const filtered = !!(filters.search || filters.health || filters.schema_status || filters.is_active)

  return (
    <>
      <div className="page-header">
        <div>
          <h1>Endpoints</h1>
          <p className="muted">Every API you monitor, with its latest health and schema state.</p>
        </div>
        <Link className="btn btn-primary" to="/endpoints/new">
          + Add endpoint
        </Link>
      </div>

      <div className="toolbar" role="search">
        <label className="sr-only" htmlFor="ep-search">
          Search endpoints
        </label>
        <input
          id="ep-search"
          type="search"
          placeholder="Search name or URL…"
          value={filters.search ?? ''}
          onChange={(e) => update({ search: e.target.value })}
        />
        <label className="sr-only" htmlFor="ep-health">
          Health
        </label>
        <select id="ep-health" value={filters.health ?? ''} onChange={(e) => update({ health: e.target.value })}>
          <option value="">All health</option>
          <option value="healthy">Healthy</option>
          <option value="unhealthy">Unhealthy</option>
          <option value="unknown">Not checked</option>
        </select>
        <label className="sr-only" htmlFor="ep-schema">
          Schema status
        </label>
        <select
          id="ep-schema"
          value={filters.schema_status ?? ''}
          onChange={(e) => update({ schema_status: e.target.value })}
        >
          <option value="">All schema states</option>
          <option value="compatible">Compatible</option>
          <option value="baseline_created">Baseline created</option>
          <option value="drifted">Drifted</option>
          <option value="unavailable">Comparison unavailable</option>
          <option value="unknown">Unknown</option>
        </select>
        <label className="sr-only" htmlFor="ep-active">
          Monitoring
        </label>
        <select id="ep-active" value={filters.is_active ?? ''} onChange={(e) => update({ is_active: e.target.value })}>
          <option value="">Active & paused</option>
          <option value="true">Active</option>
          <option value="false">Paused</option>
        </select>
        {isFetching && !isPending && <span className="spinner spinner-sm" aria-label="Refreshing" />}
      </div>

      {isPending ? (
        <Spinner />
      ) : error ? (
        <ErrorMessage error={error} title="Could not load endpoints" />
      ) : data.items.length === 0 ? (
        <EmptyState title={filtered ? 'No endpoints match these filters' : 'No endpoints yet'}>
          {!filtered && (
            <Link className="btn btn-primary" to="/endpoints/new">
              Add your first endpoint
            </Link>
          )}
        </EmptyState>
      ) : (
        <div className="card table-card">
          <div className="table-wrap">
            <table className="table table-hover">
              <thead>
                <tr>
                  <th scope="col">Name</th>
                  <th scope="col">Health</th>
                  <th scope="col">Schema</th>
                  <th scope="col">Latency</th>
                  <th scope="col">Last check</th>
                  <th scope="col">Open incidents</th>
                </tr>
              </thead>
              <tbody>
                {data.items.map((ep) => (
                  <tr key={ep.id} onClick={() => navigate(`/endpoints/${ep.id}`)}>
                    <td>
                      <Link to={`/endpoints/${ep.id}`} className="cell-title" onClick={(e) => e.stopPropagation()}>
                        {ep.name}
                      </Link>
                      <span className="cell-sub mono">
                        {ep.url}
                        {!ep.is_active && <span className="tag">paused</span>}
                      </span>
                    </td>
                    <td>
                      <HealthBadge status={ep.health_status} />
                    </td>
                    <td>
                      <SchemaBadge status={ep.schema_status} />
                    </td>
                    <td>{formatMs(ep.last_latency_ms)}</td>
                    <td title={ep.last_checked_at ?? undefined}>{relativeTime(ep.last_checked_at)}</td>
                    <td>
                      {ep.open_incident_count > 0 ? <span className="count-bad">{ep.open_incident_count}</span> : '0'}
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
            onChange={(page) => setFilters((f) => ({ ...f, page }))}
          />
        </div>
      )}
    </>
  )
}
