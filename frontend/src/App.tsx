import { lazy, Suspense } from 'react'
import { Link, Route, Routes } from 'react-router'
import { RequireAuth } from './components/Layout'
import { AuthPage } from './pages/AuthPage'
import { EndpointFormPage } from './pages/EndpointFormPage'
import { EndpointsPage } from './pages/EndpointsPage'
import { IncidentDetailPage } from './pages/IncidentDetailPage'
import { IncidentsPage } from './pages/IncidentsPage'
import { SchemaComparePage } from './pages/SchemaComparePage'
import { EmptyState, Spinner } from './components/ui'

// Chart-heavy pages are split into their own chunks (Recharts is the largest dependency).
const DashboardPage = lazy(() => import('./pages/DashboardPage').then((m) => ({ default: m.DashboardPage })))
const EndpointDetailPage = lazy(() =>
  import('./pages/EndpointDetailPage').then((m) => ({ default: m.EndpointDetailPage })),
)

export default function App() {
  return (
    <Suspense fallback={<Spinner />}>
      <Routes>
        <Route path="/login" element={<AuthPage mode="login" />} />
        <Route path="/register" element={<AuthPage mode="register" />} />
        <Route element={<RequireAuth />}>
          <Route index element={<DashboardPage />} />
          <Route path="endpoints" element={<EndpointsPage />} />
          <Route path="endpoints/new" element={<EndpointFormPage />} />
          <Route path="endpoints/:id" element={<EndpointDetailPage />} />
          <Route path="endpoints/:id/edit" element={<EndpointFormPage />} />
          <Route path="endpoints/:id/schema" element={<SchemaComparePage />} />
          <Route path="incidents" element={<IncidentsPage />} />
          <Route path="incidents/:id" element={<IncidentDetailPage />} />
          <Route
            path="*"
            element={
              <EmptyState title="Page not found">
                <Link to="/">Back to the dashboard</Link>
              </EmptyState>
            }
          />
        </Route>
      </Routes>
    </Suspense>
  )
}
