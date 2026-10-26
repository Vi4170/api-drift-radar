import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { api } from './client'
import type {
  Baseline,
  CheckResult,
  DashboardSummary,
  Endpoint,
  EndpointInput,
  Incident,
  IncidentDetail,
  Metrics,
  Page,
  SchemaView,
} from './types'

export interface EndpointFilters {
  search?: string
  health?: string
  schema_status?: string
  is_active?: string
  page?: number
  page_size?: number
}

export interface IncidentFilters {
  status?: string
  severity?: string
  type?: string
  endpoint_id?: string
  page?: number
  page_size?: number
}

export const keys = {
  dashboard: ['dashboard'] as const,
  endpoints: (f?: EndpointFilters) => ['endpoints', f ?? {}] as const,
  endpoint: (id: string) => ['endpoint', id] as const,
  checks: (id: string, page: number) => ['endpoint', id, 'checks', page] as const,
  schema: (id: string) => ['endpoint', id, 'schema'] as const,
  baselines: (id: string) => ['endpoint', id, 'baselines'] as const,
  metrics: (id: string, hours: number) => ['endpoint', id, 'metrics', hours] as const,
  incidents: (f?: IncidentFilters) => ['incidents', f ?? {}] as const,
  incident: (id: string) => ['incident', id] as const,
}

const REFRESH_MS = 30_000

export const useDashboard = () =>
  useQuery({
    queryKey: keys.dashboard,
    queryFn: () => api.get<DashboardSummary>('/dashboard/summary'),
    refetchInterval: REFRESH_MS,
  })

export const useEndpoints = (filters: EndpointFilters) =>
  useQuery({
    queryKey: keys.endpoints(filters),
    queryFn: () => api.get<Page<Endpoint>>('/endpoints', { ...filters }),
    placeholderData: keepPreviousData,
    refetchInterval: REFRESH_MS,
  })

export const useEndpoint = (id: string, enabled = true) =>
  useQuery({
    queryKey: keys.endpoint(id),
    queryFn: () => api.get<Endpoint>(`/endpoints/${id}`),
    refetchInterval: REFRESH_MS,
    enabled,
  })

export const useChecks = (id: string, page: number) =>
  useQuery({
    queryKey: keys.checks(id, page),
    queryFn: () => api.get<Page<CheckResult>>(`/endpoints/${id}/checks`, { page, page_size: 10 }),
    placeholderData: keepPreviousData,
  })

export const useSchemaView = (id: string) =>
  useQuery({ queryKey: keys.schema(id), queryFn: () => api.get<SchemaView>(`/endpoints/${id}/schema`) })

export const useBaselines = (id: string) =>
  useQuery({ queryKey: keys.baselines(id), queryFn: () => api.get<Baseline[]>(`/endpoints/${id}/baselines`) })

export const useMetrics = (id: string, hours: number) =>
  useQuery({
    queryKey: keys.metrics(id, hours),
    queryFn: () => api.get<Metrics>(`/endpoints/${id}/metrics`, { window_hours: hours }),
  })

export const useIncidents = (filters: IncidentFilters) =>
  useQuery({
    queryKey: keys.incidents(filters),
    queryFn: () => api.get<Page<Incident>>('/incidents', { ...filters }),
    placeholderData: keepPreviousData,
    refetchInterval: REFRESH_MS,
  })

export const useIncident = (id: string) =>
  useQuery({ queryKey: keys.incident(id), queryFn: () => api.get<IncidentDetail>(`/incidents/${id}`) })

/** After any write, refresh everything derived from endpoints/checks/incidents. */
function useInvalidateAll() {
  const qc = useQueryClient()
  return () =>
    Promise.all(
      ['dashboard', 'endpoints', 'endpoint', 'incidents', 'incident'].map((k) =>
        qc.invalidateQueries({ queryKey: [k] }),
      ),
    )
}

export function useCreateEndpoint() {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (body: EndpointInput) => api.post<Endpoint>('/endpoints', body),
    onSuccess: invalidate,
  })
}

export function useUpdateEndpoint(id: string) {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (body: Partial<EndpointInput>) => api.patch<Endpoint>(`/endpoints/${id}`, body),
    onSuccess: invalidate,
  })
}

export function useDeleteEndpoint() {
  const invalidate = useInvalidateAll()
  return useMutation({ mutationFn: (id: string) => api.delete(`/endpoints/${id}`), onSuccess: invalidate })
}

export function useRunCheck(id: string) {
  const invalidate = useInvalidateAll()
  return useMutation({ mutationFn: () => api.post<CheckResult>(`/endpoints/${id}/checks`), onSuccess: invalidate })
}

export function useAcceptBaseline(id: string) {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (checkId: string) => api.post<Baseline>(`/endpoints/${id}/baseline`, { check_id: checkId }),
    onSuccess: invalidate,
  })
}

export function useResolveIncident(id: string) {
  const invalidate = useInvalidateAll()
  return useMutation({
    mutationFn: (note: string) => api.post<IncidentDetail>(`/incidents/${id}/resolve`, { note }),
    onSuccess: invalidate,
  })
}
