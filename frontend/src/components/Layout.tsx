import { Navigate, NavLink, Outlet, useLocation } from 'react-router'
import { useAuth } from '../auth/AuthContext'
import { Spinner } from './ui'

export function RequireAuth() {
  const { user, isLoading } = useAuth()
  const location = useLocation()
  if (isLoading) return <Spinner label="Restoring session…" />
  if (!user) return <Navigate to="/login" replace state={{ from: location.pathname }} />
  return <Layout />
}

function Layout() {
  const { user, logout } = useAuth()
  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="sidebar">
        <div className="brand">
          <span className="brand-mark" aria-hidden="true">
            ◎
          </span>
          API Drift Radar
        </div>
        <nav aria-label="Main">
          <NavLink to="/" end>
            Dashboard
          </NavLink>
          <NavLink to="/endpoints">Endpoints</NavLink>
          <NavLink to="/incidents">Incidents</NavLink>
        </nav>
        <div className="account">
          <span className="account-email" title={user?.email}>
            {user?.email}
          </span>
          <button className="btn btn-ghost btn-sm" onClick={logout}>
            Log out
          </button>
        </div>
      </header>
      <main id="main" className="content">
        <Outlet />
      </main>
    </div>
  )
}
