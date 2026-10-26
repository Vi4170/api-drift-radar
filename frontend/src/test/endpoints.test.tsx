import { screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, describe, expect, it, vi } from 'vitest'
import type { Endpoint } from '../api/types'
import { HealthBadge, SchemaBadge } from '../components/ui'
import { EndpointForm } from '../pages/EndpointFormPage'
import { EndpointsPage } from '../pages/EndpointsPage'
import { toPayload, validateEndpoint, type FormValues } from '../utils/validation'
import { mockApi, renderApp } from './utils'

afterEach(() => vi.unstubAllGlobals())

const valid: FormValues = {
  name: 'Users',
  url: 'https://api.example.com/users/1',
  expected_status: '200',
  interval_seconds: '300',
  timeout_seconds: '10',
  is_active: true,
  headers: [{ name: 'X-Api-Version', value: '2' }],
}

export const sampleEndpoint: Endpoint = {
  id: 'e1',
  name: 'Users API',
  url: 'https://api.example.com/users/1',
  method: 'GET',
  expected_status: 200,
  interval_seconds: 300,
  timeout_seconds: 10,
  headers: {},
  is_active: true,
  created_at: '2026-01-01T00:00:00Z',
  updated_at: '2026-01-01T00:00:00Z',
  last_checked_at: null,
  last_outcome: null,
  last_status_code: null,
  last_latency_ms: 120,
  health_status: 'unhealthy',
  schema_status: 'drifted',
  schema_checked_at: null,
  latest_schema_hash: null,
  open_incident_count: 2,
  baseline_version: 1,
}

describe('validateEndpoint', () => {
  it('accepts a valid form and builds the payload', () => {
    expect(validateEndpoint(valid)).toEqual({})
    expect(toPayload(valid)).toMatchObject({ method: 'GET', interval_seconds: 300, headers: { 'X-Api-Version': '2' } })
  })

  it.each([
    [{ url: 'ftp://x.com' }, 'url'],
    [{ url: 'https://user:pw@x.com' }, 'url'],
    [{ url: 'not a url' }, 'url'],
    [{ interval_seconds: '10' }, 'interval_seconds'],
    [{ timeout_seconds: '60' }, 'timeout_seconds'],
    [{ expected_status: '42' }, 'expected_status'],
    [{ name: '  ' }, 'name'],
    [{ headers: [{ name: 'Host', value: 'evil' }] }, 'headers'],
    [{ headers: [{ name: 'X-Forwarded-For', value: '1.1.1.1' }] }, 'headers'],
    [{ headers: [{ name: 'bad name', value: 'x' }] }, 'headers'],
  ] as [Partial<FormValues>, string][])('rejects %j', (patch, field) => {
    expect(validateEndpoint({ ...valid, ...patch })).toHaveProperty(field)
  })
})

describe('EndpointForm', () => {
  it('shows field errors and does not submit invalid input', async () => {
    const calls = mockApi({})
    renderApp(<EndpointForm />)
    await userEvent.type(screen.getByLabelText('URL'), 'ftp://example.com')
    await userEvent.click(screen.getByRole('button', { name: 'Add endpoint' }))
    expect(screen.getByText('Name is required')).toBeInTheDocument()
    expect(screen.getByText('Only http:// and https:// URLs are supported')).toBeInTheDocument()
    expect(calls).toHaveLength(0)
  })

  it('submits a valid endpoint and surfaces SSRF rejections on the URL field', async () => {
    const calls = mockApi({
      'POST /endpoints': {
        status: 422,
        body: { error: { code: 'unsafe_url', message: 'URL points to a non-public IP address' } },
      },
    })
    renderApp(<EndpointForm />)
    await userEvent.type(screen.getByLabelText('Name'), 'Internal')
    await userEvent.type(screen.getByLabelText('URL'), 'http://10.0.0.1/admin')
    await userEvent.click(screen.getByRole('button', { name: 'Add endpoint' }))
    expect(await screen.findAllByText('URL points to a non-public IP address')).not.toHaveLength(0)
    expect(screen.getByLabelText('URL')).toHaveAttribute('aria-invalid', 'true')
    expect(calls[0]).toMatchObject({
      method: 'POST',
      body: { name: 'Internal', url: 'http://10.0.0.1/admin', method: 'GET' },
    })
  })

  it('adds custom headers', async () => {
    const calls = mockApi({ 'POST /endpoints': { status: 201, body: { ...sampleEndpoint, id: 'created-1' } } })
    renderApp(<EndpointForm />, { route: '/endpoints/new', path: '/endpoints/new' })
    await userEvent.type(screen.getByLabelText('Name'), 'Users')
    await userEvent.type(screen.getByLabelText('URL'), 'https://api.example.com/users/1')
    await userEvent.click(screen.getByRole('button', { name: '+ Add header' }))
    await userEvent.type(screen.getByLabelText('Header 1 name'), 'X-Api-Version')
    await userEvent.type(screen.getByLabelText('Header 1 value'), '2')
    await userEvent.click(screen.getByRole('button', { name: 'Add endpoint' }))
    expect(await screen.findByText('navigated away')).toBeInTheDocument()
    expect(calls[0].body).toMatchObject({ headers: { 'X-Api-Version': '2' } })
  })
})

describe('status display', () => {
  it('renders accessible health and schema badges', () => {
    renderApp(
      <>
        <HealthBadge status="healthy" />
        <SchemaBadge status="baseline_created" />
      </>,
    )
    expect(screen.getByLabelText('Health: healthy')).toHaveClass('badge-ok')
    expect(screen.getByLabelText('Schema: baseline created')).toHaveTextContent('baseline created')
  })
})

describe('EndpointsPage', () => {
  it('shows a loading state, then endpoint rows from the API', async () => {
    mockApi({ 'GET /endpoints': { body: { items: [sampleEndpoint], total: 1, page: 1, page_size: 20 } } })
    renderApp(<EndpointsPage />)
    expect(screen.getByRole('status')).toHaveTextContent('Loading')
    const row = (await screen.findByRole('link', { name: 'Users API' })).closest('tr')!
    expect(within(row).getByLabelText('Health: unhealthy')).toBeInTheDocument()
    expect(within(row).getByLabelText('Schema: drifted')).toBeInTheDocument()
    expect(within(row).getByText('120 ms')).toBeInTheDocument()
    expect(within(row).getByText('2')).toBeInTheDocument()
  })

  it('shows API errors', async () => {
    mockApi({ 'GET /endpoints': { status: 500, body: { error: { code: 'internal_error', message: 'Boom' } } } })
    renderApp(<EndpointsPage />)
    expect(await screen.findByRole('alert')).toHaveTextContent('Could not load endpoints')
  })

  it('sends search and filters to the API', async () => {
    const calls = mockApi({ 'GET /endpoints': { body: { items: [], total: 0, page: 1, page_size: 20 } } })
    renderApp(<EndpointsPage />)
    await screen.findByText('No endpoints yet')
    await userEvent.selectOptions(screen.getByLabelText('Health'), 'unhealthy')
    await screen.findByText('No endpoints match these filters')
    expect(calls.at(-1)!.url.searchParams.get('health')).toBe('unhealthy')
  })
})
