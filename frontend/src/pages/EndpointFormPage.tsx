import { useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router'
import { ApiError } from '../api/client'
import { useCreateEndpoint, useEndpoint, useUpdateEndpoint } from '../api/hooks'
import type { Endpoint } from '../api/types'
import { ErrorMessage, Field, Spinner } from '../components/ui'
import { toPayload, validateEndpoint, type FormValues } from '../utils/validation'

function fromEndpoint(ep?: Endpoint): FormValues {
  return {
    name: ep?.name ?? '',
    url: ep?.url ?? '',
    expected_status: String(ep?.expected_status ?? 200),
    interval_seconds: String(ep?.interval_seconds ?? 300),
    timeout_seconds: String(ep?.timeout_seconds ?? 10),
    is_active: ep?.is_active ?? true,
    headers: Object.entries(ep?.headers ?? {}).map(([name, value]) => ({ name, value })),
  }
}

export function EndpointFormPage() {
  const { id } = useParams()
  const existing = useEndpoint(id ?? '', !!id)
  if (!id) return <EndpointForm />
  if (existing.isPending) return <Spinner />
  if (existing.error) return <ErrorMessage error={existing.error} title="Could not load endpoint" />
  return <EndpointForm endpoint={existing.data} />
}

export function EndpointForm({ endpoint }: { endpoint?: Endpoint }) {
  const navigate = useNavigate()
  const create = useCreateEndpoint()
  const update = useUpdateEndpoint(endpoint?.id ?? '')
  const [values, setValues] = useState<FormValues>(() => fromEndpoint(endpoint))
  const [errors, setErrors] = useState<Record<string, string>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const mutation = endpoint ? update : create
  const set = <K extends keyof FormValues>(key: K, value: FormValues[K]) => setValues((v) => ({ ...v, [key]: value }))

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    const found = validateEndpoint(values)
    setErrors(found)
    setFormError(null)
    if (Object.keys(found).length) return
    try {
      const saved = await mutation.mutateAsync(toPayload(values))
      navigate(`/endpoints/${saved.id}`)
    } catch (err) {
      if (err instanceof ApiError) {
        setErrors(err.code === 'unsafe_url' ? { url: err.message } : err.fieldErrors())
        setFormError(err.message)
      } else setFormError('Unexpected error, please try again')
    }
  }

  const input = (key: 'name' | 'url' | 'expected_status' | 'interval_seconds' | 'timeout_seconds') => ({
    id: key,
    value: values[key],
    onChange: (e: React.ChangeEvent<HTMLInputElement>) => set(key, e.target.value),
    'aria-invalid': !!errors[key],
    'aria-describedby': errors[key] ? `${key}-error` : `${key}-hint`,
  })

  return (
    <>
      <div className="page-header">
        <div>
          <h1>{endpoint ? `Edit ${endpoint.name}` : 'Add endpoint'}</h1>
          <p className="muted">
            Only GET requests are sent. Private, loopback and cloud-metadata addresses are refused.
          </p>
        </div>
      </div>
      <form className="card form" onSubmit={onSubmit} noValidate aria-label="Endpoint settings">
        {formError && (
          <div className="alert alert-error" role="alert">
            {formError}
          </div>
        )}
        <Field label="Name" htmlFor="name" error={errors.name} hint="A short label, unique within your account.">
          <input {...input('name')} maxLength={120} placeholder="Users API" />
        </Field>
        <Field
          label="URL"
          htmlFor="url"
          error={errors.url}
          hint="Full http(s) URL of a public endpoint. Redirects are not followed."
        >
          <input {...input('url')} type="url" inputMode="url" placeholder="https://api.example.com/v1/users/1" />
        </Field>
        <div className="form-row">
          <Field
            label="Expected status"
            htmlFor="expected_status"
            error={errors.expected_status}
            hint="Any other status is unhealthy."
          >
            <input {...input('expected_status')} type="number" min={100} max={599} />
          </Field>
          <Field
            label="Interval (seconds)"
            htmlFor="interval_seconds"
            error={errors.interval_seconds}
            hint="How often the worker checks (min 30)."
          >
            <input {...input('interval_seconds')} type="number" min={30} max={86400} step={30} />
          </Field>
          <Field
            label="Timeout (seconds)"
            htmlFor="timeout_seconds"
            error={errors.timeout_seconds}
            hint="Total time allowed per request."
          >
            <input {...input('timeout_seconds')} type="number" min={1} max={30} step={0.5} />
          </Field>
        </div>

        <fieldset className="field">
          <legend>Request headers (optional)</legend>
          <small className="hint">
            Sent with every check, e.g. <code>Accept-Language</code> or an API key. Stored in the database and shown to
            you only; avoid production secrets.
          </small>
          {values.headers.map((h, i) => (
            <div className="header-row" key={i}>
              <input
                aria-label={`Header ${i + 1} name`}
                placeholder="X-Api-Version"
                value={h.name}
                onChange={(e) =>
                  set(
                    'headers',
                    values.headers.map((r, j) => (j === i ? { ...r, name: e.target.value } : r)),
                  )
                }
              />
              <input
                aria-label={`Header ${i + 1} value`}
                placeholder="2"
                value={h.value}
                onChange={(e) =>
                  set(
                    'headers',
                    values.headers.map((r, j) => (j === i ? { ...r, value: e.target.value } : r)),
                  )
                }
              />
              <button
                type="button"
                className="btn btn-ghost btn-sm"
                aria-label={`Remove header ${i + 1}`}
                onClick={() =>
                  set(
                    'headers',
                    values.headers.filter((_, j) => j !== i),
                  )
                }
              >
                ✕
              </button>
            </div>
          ))}
          {errors.headers && (
            <small className="field-error" role="alert">
              {errors.headers}
            </small>
          )}
          <button
            type="button"
            className="btn btn-ghost btn-sm"
            onClick={() => set('headers', [...values.headers, { name: '', value: '' }])}
          >
            + Add header
          </button>
        </fieldset>

        <label className="checkbox">
          <input type="checkbox" checked={values.is_active} onChange={(e) => set('is_active', e.target.checked)} />
          Monitor on a schedule (uncheck to pause; manual checks still work)
        </label>

        <div className="form-actions">
          <Link className="btn btn-ghost" to={endpoint ? `/endpoints/${endpoint.id}` : '/endpoints'}>
            Cancel
          </Link>
          <button className="btn btn-primary" type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? 'Saving…' : endpoint ? 'Save changes' : 'Add endpoint'}
          </button>
        </div>
      </form>
    </>
  )
}
