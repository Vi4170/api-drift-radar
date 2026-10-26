import { screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { SchemaChange, SchemaView } from '../api/types'
import { SchemaDiffTable, SchemaPanel } from '../components/schema'
import { IncidentsPage } from '../pages/IncidentsPage'
import { AcceptBaseline } from '../pages/SchemaComparePage'
import { mockApi, renderApp } from './utils'

afterEach(() => vi.unstubAllGlobals())

const changes: SchemaChange[] = [
  {
    path: '$.user_id',
    kind: 'type_changed',
    rule: 'type_changed.incompatible',
    severity: 'critical',
    old: 'number',
    new: 'string',
    description: 'Type changed from number to string',
  },
  {
    path: '$.profile.zip',
    kind: 'field_added',
    rule: 'field_added',
    severity: 'info',
    old: null,
    new: 'string',
    description: 'New field appeared',
  },
]

const view: SchemaView = {
  baseline: {
    id: 'b1',
    endpoint_id: 'e1',
    version: 1,
    schema_hash: 'aaa',
    is_current: true,
    source_check_id: 'c0',
    approved_by_id: null,
    approved_at: '2026-01-01T00:00:00Z',
    replaced_at: null,
    json_schema: null,
  },
  latest_schema_hash: 'bbb',
  latest_schema: null,
  latest_check_id: 'c9',
  latest_checked_at: '2026-01-02T00:00:00Z',
  latest_is_json: true,
  comparison_available: true,
  changes,
  max_severity: 'critical',
}

describe('SchemaDiffTable', () => {
  it('renders paths, old/new types and severity', () => {
    renderApp(<SchemaDiffTable changes={changes} />)
    const row = screen.getByText('$.user_id').closest('tr')!
    expect(within(row).getByText('number')).toHaveClass('type-old')
    expect(within(row).getByText('string')).toHaveClass('type-new')
    expect(within(row).getByLabelText('Severity: critical')).toBeInTheDocument()
    expect(within(row).getByText('type changed')).toBeInTheDocument()
  })

  it('renders an explicit no-change message', () => {
    renderApp(<SchemaDiffTable changes={[]} />)
    expect(screen.getByText(/No differences/)).toBeInTheDocument()
  })

  it('highlights changed nested paths in the schema tree', () => {
    const schema = {
      type: 'object',
      nullable: false,
      required: ['profile'],
      properties: {
        profile: {
          type: 'object',
          nullable: false,
          required: ['zip'],
          properties: { zip: { type: 'string', nullable: false } },
        },
      },
    }
    renderApp(<SchemaPanel title="Latest" schema={schema} changes={changes} empty="none" />)
    expect(screen.getByText('zip').closest('li')).toHaveClass('tree-info')
    expect(screen.getByText('profile').closest('li')).not.toHaveClass('tree-info')
  })
})

describe('AcceptBaseline', () => {
  it('requires explicit confirmation before accepting', async () => {
    const calls = mockApi({ 'POST /endpoints/e1/baseline': { status: 201, body: { ...view.baseline, version: 2 } } })
    renderApp(<AcceptBaseline endpointId="e1" view={view} />)

    await userEvent.click(screen.getByRole('button', { name: 'Accept as new baseline…' }))
    expect(screen.getByRole('heading', { name: /Accept the latest schema/ })).toBeInTheDocument()
    expect(screen.getByText(/including critical/)).toBeInTheDocument()
    expect(calls).toHaveLength(0) // opening the dialog does nothing yet

    await userEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(calls).toHaveLength(0)

    await userEvent.click(screen.getByRole('button', { name: 'Accept as new baseline…' }))
    await userEvent.click(screen.getByRole('button', { name: 'Accept as v2' }))
    expect(await screen.findByText(/Baseline v2 accepted/)).toBeInTheDocument()
    expect(calls).toEqual([expect.objectContaining({ method: 'POST', body: { check_id: 'c9' } })])
  })

  it('cannot accept a non-JSON response', () => {
    renderApp(<AcceptBaseline endpointId="e1" view={{ ...view, latest_is_json: false }} />)
    expect(screen.getByRole('button', { name: 'Accept as new baseline…' })).toBeDisabled()
  })

  it('is hidden when the latest schema matches the baseline', () => {
    renderApp(<AcceptBaseline endpointId="e1" view={{ ...view, latest_schema_hash: 'aaa' }} />)
    expect(screen.queryByRole('button', { name: /Accept/ })).not.toBeInTheDocument()
  })
})

describe('IncidentsPage', () => {
  const incident = {
    id: 'i1',
    endpoint_id: 'e1',
    endpoint_name: 'Users API',
    type: 'schema_drift',
    status: 'open',
    severity: 'critical',
    title: 'Schema drift detected',
    summary: '2 schema change(s)',
    occurrence_count: 3,
    first_seen_at: '2026-01-01T00:00:00Z',
    last_seen_at: '2026-01-02T00:00:00Z',
    resolved_at: null,
    resolution: null,
    baseline_id: 'b1',
  }

  it('defaults to open incidents and filters by severity and type', async () => {
    const calls = mockApi({ 'GET /incidents': { body: { items: [incident], total: 1, page: 1, page_size: 20 } } })
    renderApp(<IncidentsPage />)
    expect(await screen.findByText('Users API')).toBeInTheDocument()
    expect(screen.getByText('3×')).toBeInTheDocument()
    expect(calls[0].url.searchParams.get('status')).toBe('open')

    await userEvent.selectOptions(screen.getByLabelText('Severity'), 'critical')
    await userEvent.selectOptions(screen.getByLabelText('Type'), 'schema_drift')
    await waitFor(() => {
      const last = calls.at(-1)!.url.searchParams
      expect([last.get('severity'), last.get('type'), last.get('status')]).toEqual(['critical', 'schema_drift', 'open'])
    })
  })

  it('shows an empty state', async () => {
    mockApi({ 'GET /incidents': { body: { items: [], total: 0, page: 1, page_size: 20 } } })
    renderApp(<IncidentsPage />)
    expect(await screen.findByText('No incidents match these filters')).toBeInTheDocument()
  })
})
