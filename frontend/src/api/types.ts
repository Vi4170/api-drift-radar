// Mirrors the backend Pydantic response models (see /docs on the API).

export type HealthStatus = 'unknown' | 'healthy' | 'unhealthy'
export type SchemaStatus = 'unknown' | 'baseline_created' | 'compatible' | 'drifted' | 'unavailable' | 'not_applicable'
export type Severity = 'info' | 'warning' | 'critical'
export type IncidentStatus = 'open' | 'resolved'
export type IncidentType = 'schema_drift' | 'availability'
export type CheckOutcome =
  | 'success_json'
  | 'success_non_json'
  | 'invalid_json'
  | 'unexpected_status'
  | 'timeout'
  | 'network_error'
  | 'blocked'
  | 'response_too_large'

export interface Page<T> {
  items: T[]
  total: number
  page: number
  page_size: number
}

export interface TokenResponse {
  access_token: string
  token_type: string
  expires_in: number
}

export interface User {
  id: string
  email: string
  created_at: string
}

export interface EndpointInput {
  name: string
  url: string
  method: 'GET'
  expected_status: number
  interval_seconds: number
  timeout_seconds: number
  headers: Record<string, string>
  is_active: boolean
}

export interface Endpoint extends EndpointInput {
  id: string
  created_at: string
  updated_at: string
  last_checked_at: string | null
  last_outcome: CheckOutcome | null
  last_status_code: number | null
  last_latency_ms: number | null
  health_status: HealthStatus
  schema_status: SchemaStatus
  schema_checked_at: string | null
  latest_schema_hash: string | null
  open_incident_count: number
  baseline_version: number | null
}

export interface CheckResult {
  id: string
  endpoint_id: string
  checked_at: string
  trigger: 'manual' | 'scheduled'
  outcome: CheckOutcome
  is_healthy: boolean
  status_code: number | null
  latency_ms: number | null
  response_size_bytes: number | null
  content_type: string | null
  error_message: string | null
  schema_status: SchemaStatus
  schema_hash: string | null
  drift_severity: Severity | null
  change_count: number
  baseline_id: string | null
  incident_id: string | null
  snapshot_id: string | null
}

export interface RecentCheck extends CheckResult {
  endpoint_name: string
}

export interface SchemaChange {
  path: string
  kind: string
  rule: string
  severity: Severity
  old: string | null
  new: string | null
  description: string
}

export interface SchemaNode {
  type: string
  nullable: boolean
  properties?: Record<string, SchemaNode>
  required?: string[]
  items?: SchemaNode | null
  types?: string[]
}

export interface Baseline {
  id: string
  endpoint_id: string
  version: number
  schema_hash: string
  is_current: boolean
  source_check_id: string | null
  approved_by_id: string | null
  approved_at: string
  replaced_at: string | null
}

export interface SchemaView {
  baseline: (Baseline & { json_schema: SchemaNode | null }) | null
  latest_schema_hash: string | null
  latest_schema: SchemaNode | null
  latest_check_id: string | null
  latest_checked_at: string | null
  latest_is_json: boolean
  comparison_available: boolean
  changes: SchemaChange[]
  max_severity: Severity | null
}

export interface Metrics {
  window_hours: number
  total_checks: number
  healthy_checks: number
  availability_percent: number | null
  avg_latency_ms: number | null
  p95_latency_ms: number | null
  series: { checked_at: string; latency_ms: number | null; is_healthy: boolean }[]
}

export interface Incident {
  id: string
  endpoint_id: string
  endpoint_name: string
  type: IncidentType
  status: IncidentStatus
  severity: Severity
  title: string
  summary: string
  occurrence_count: number
  first_seen_at: string
  last_seen_at: string
  resolved_at: string | null
  resolution: string | null
  baseline_id: string | null
}

export interface IncidentEvent {
  id: string
  created_at: string
  event_type: string
  message: string
  actor_id: string | null
  details: Record<string, unknown>
}

export interface IncidentDetail extends Incident {
  events: IncidentEvent[]
  changes: SchemaChange[]
  changes_available: boolean
}

export interface DashboardSummary {
  total_endpoints: number
  active_endpoints: number
  healthy_endpoints: number
  unhealthy_endpoints: number
  unknown_endpoints: number
  endpoints_with_open_drift: number
  open_incidents_by_severity: Partial<Record<Severity, number>>
  checks_last_24h: number
  availability_24h_percent: number | null
  avg_latency_24h_ms: number | null
  recent_incidents: Incident[]
  recent_checks: RecentCheck[]
  latency_series: { bucket_start: string; checks: number; healthy_checks: number; avg_latency_ms: number | null }[]
}
