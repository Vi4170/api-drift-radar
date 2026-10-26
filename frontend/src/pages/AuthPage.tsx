import { useState, type FormEvent } from 'react'
import { Link, Navigate, useLocation, useNavigate } from 'react-router'
import { ApiError } from '../api/client'
import { useAuth } from '../auth/AuthContext'
import { Field } from '../components/ui'
import { validateAuth } from '../utils/validation'

export function AuthPage({ mode }: { mode: 'login' | 'register' }) {
  const { user, login, register, sessionExpired } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const isLogin = mode === 'login'

  if (user) return <Navigate to={(location.state as { from?: string } | null)?.from ?? '/'} replace />

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const found = validateAuth(mode, email, password, confirm)
    setErrors(found)
    setFormError(null)
    if (Object.keys(found).length) return
    setSubmitting(true)
    try {
      await (isLogin ? login : register)(email.trim(), password)
      navigate('/', { replace: true })
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.fieldErrors())
        setFormError(err.message)
      } else {
        setFormError('Unexpected error, please try again')
      }
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="auth-screen">
      <form className="card auth-card" onSubmit={onSubmit} noValidate aria-labelledby="auth-title">
        <div className="brand brand-lg">
          <span className="brand-mark" aria-hidden="true">
            ◎
          </span>
          API Drift Radar
        </div>
        <h1 id="auth-title">{isLogin ? 'Sign in' : 'Create your account'}</h1>
        {sessionExpired && isLogin && (
          <div className="alert alert-info" role="status">
            Your session expired. Please sign in again.
          </div>
        )}
        {formError && (
          <div className="alert alert-error" role="alert">
            {formError}
          </div>
        )}
        <Field label="Email" htmlFor="email" error={errors.email}>
          <input
            id="email"
            type="email"
            autoComplete="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            aria-invalid={!!errors.email}
            aria-describedby={errors.email ? 'email-error' : undefined}
          />
        </Field>
        <Field
          label="Password"
          htmlFor="password"
          error={errors.password}
          hint={isLogin ? undefined : 'At least 10 characters.'}
        >
          <input
            id="password"
            type="password"
            autoComplete={isLogin ? 'current-password' : 'new-password'}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            aria-invalid={!!errors.password}
            aria-describedby={errors.password ? 'password-error' : 'password-hint'}
          />
        </Field>
        {!isLogin && (
          <Field label="Confirm password" htmlFor="confirm" error={errors.confirm}>
            <input
              id="confirm"
              type="password"
              autoComplete="new-password"
              value={confirm}
              onChange={(e) => setConfirm(e.target.value)}
              aria-invalid={!!errors.confirm}
            />
          </Field>
        )}
        <button className="btn btn-primary btn-block" type="submit" disabled={submitting}>
          {submitting ? 'Please wait…' : isLogin ? 'Sign in' : 'Create account'}
        </button>
        <p className="muted center">
          {isLogin ? (
            <>
              No account yet? <Link to="/register">Create one</Link>
            </>
          ) : (
            <>
              Already registered? <Link to="/login">Sign in</Link>
            </>
          )}
        </p>
      </form>
    </div>
  )
}
